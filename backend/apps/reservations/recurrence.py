"""Récurrences RFC 5545 (PLA-04) : génération des occurrences en heure de Paris, exclusions, description lisible.

Les calculs se font en heure locale (Europe/Paris) puis sont stockés en UTC : un créneau « 18 h – 20 h »
reste à 18 h après le changement d'heure d'octobre ou de mars.
"""

from __future__ import annotations

import re
from datetime import UTC, date, datetime, time, timedelta
from typing import TYPE_CHECKING
from zoneinfo import ZoneInfo

from dateutil.rrule import rrulestr

from apps.noyau.exceptions import ErreurValidation

if TYPE_CHECKING:
    from apps.referentiel.models import Saison

    from .models import Reservation

PARIS = ZoneInfo("Europe/Paris")
JOURS = {"MO": "lundi", "TU": "mardi", "WE": "mercredi", "TH": "jeudi", "FR": "vendredi", "SA": "samedi", "SU": "dimanche"}
MAX_OCCURRENCES = 400
JOUR = r"(MO|TU|WE|TH|FR|SA|SU)"
JOUR_ORDINAL = re.compile(rf"^([+-]?[1-5])?{JOUR}$")


def heure(t: time) -> str:
    return f"{t.hour} h" if t.minute == 0 else f"{t.hour} h {t.minute:02d}"


def _refus(detail: str) -> ErreurValidation:
    return ErreurValidation(f"Règle de récurrence non acceptée : {detail}", code="recurrence_invalide")


def valider_regle(regle: str) -> str:
    """Grammaire restreinte, dont chaque combinaison produit au moins une date par semestre.

    Une règle qui ne produit jamais de date (`BYMONTHDAY=99`, février tous les douze mois…) ferait
    itérer `dateutil` jusqu'à l'an 9999 : elle est refusée ici, avant tout calcul (déni de service).
    FREQ=DAILY|WEEKLY|MONTHLY ; INTERVAL 1 à 52 (1 à 6 en mensuel) ; BYDAY jours simples, ou un jour
    ordinal ±1 à 5 en mensuel ; BYMONTHDAY 1 à 31 ou -1 à -7 en mensuel ; UNTIL ou COUNT (1 à 400) ; WKST.
    """
    regle = regle.strip().upper().removeprefix("RRULE:")
    if not regle:
        return ""
    if len(regle) > 200:
        raise _refus("règle trop longue.")
    parties: dict[str, str] = {}
    for morceau in regle.split(";"):
        cle, egal, valeur = morceau.partition("=")
        if not egal or not valeur or cle in parties:
            raise _refus(f"« {morceau} ».")
        parties[cle] = valeur
    inconnues = set(parties) - {"FREQ", "INTERVAL", "BYDAY", "BYMONTHDAY", "UNTIL", "COUNT", "WKST"}
    if inconnues:
        raise _refus("éléments non pris en charge : " + ", ".join(sorted(inconnues)) + ".")
    frequence = parties.get("FREQ")
    if frequence not in {"DAILY", "WEEKLY", "MONTHLY"}:
        raise _refus("fréquence quotidienne, hebdomadaire ou mensuelle attendue.")
    intervalle = parties.get("INTERVAL", "1")
    maximum = 6 if frequence == "MONTHLY" else 52
    if not intervalle.isdigit() or not 1 <= int(intervalle) <= maximum:
        raise _refus(f"intervalle entre 1 et {maximum}.")
    if "BYDAY" in parties:
        jours = parties["BYDAY"].split(",")
        if len(jours) > 7 or len(set(jours)) != len(jours):
            raise _refus("jours de la semaine.")
        for jour in jours:
            correspondance = JOUR_ORDINAL.match(jour)
            if correspondance is None:
                raise _refus(f"jour « {jour} ».")
            if correspondance.group(1) and (frequence != "MONTHLY" or len(jours) > 1):
                raise _refus("un jour ordinal (ex. 1MO, -1FR) n'est admis qu'en mensuel, seul.")
    if "BYMONTHDAY" in parties:
        valeur = parties["BYMONTHDAY"]
        if frequence != "MONTHLY" or "BYDAY" in parties or not re.fullmatch(r"-?\d{1,2}", valeur):
            raise _refus("jour du mois admis seulement en mensuel, sans jour de semaine.")
        if not (1 <= int(valeur) <= 31 or -7 <= int(valeur) <= -1):
            raise _refus("jour du mois entre 1 et 31 (ou -1 à -7 depuis la fin du mois).")
    if "UNTIL" in parties and "COUNT" in parties:
        raise _refus("UNTIL et COUNT ne peuvent pas être combinés.")
    if "UNTIL" in parties and not re.fullmatch(r"\d{8}(T\d{6}Z?)?", parties["UNTIL"]):
        raise _refus("date de fin UNTIL (AAAAMMJJ).")
    if "COUNT" in parties and (not parties["COUNT"].isdigit() or not 1 <= int(parties["COUNT"]) <= MAX_OCCURRENCES):
        raise _refus(f"nombre de séances COUNT entre 1 et {MAX_OCCURRENCES}.")
    if "WKST" in parties and parties["WKST"] not in {"MO", "SU"}:
        raise _refus("WKST=MO ou WKST=SU.")
    return regle


def saisons_couvrant(debut: date, fin: date) -> list[Saison]:
    from apps.referentiel.models import Saison

    return list(Saison.objects.filter(debut__lte=fin, fin__gte=debut))


def jours_exclus_pour(reservation: Reservation) -> set[date]:
    from apps.referentiel.calendrier import feries_calcules, jours_exclus

    avec_saison = reservation.dossier_id is not None and reservation.dossier.saison_id is not None
    saisons = [reservation.dossier.saison] if avec_saison else saisons_couvrant(reservation.date_debut, reservation.date_fin)
    exclus: set[date] = set()
    for saison in saisons:
        if saison is not None:
            exclus |= jours_exclus(saison, vacances=reservation.exclure_vacances, feries=reservation.exclure_feries)
    if reservation.exclure_feries:
        for annee in range(reservation.date_debut.year, reservation.date_fin.year + 1):
            exclus |= set(feries_calcules(annee))
    return exclus


def _instant_local(jour: date, heure_locale: time) -> datetime:
    """Instant d'heure de Paris ; une heure qui n'existe pas (passage à l'heure d'été) est refusée."""
    instant = datetime.combine(jour, heure_locale, tzinfo=PARIS)
    if instant.astimezone(UTC).astimezone(PARIS).replace(tzinfo=None) != instant.replace(tzinfo=None):
        raise ErreurValidation(
            f"{heure(heure_locale)} n'existe pas le {jour:%d/%m/%Y} (passage à l'heure d'été) : choisissez un autre horaire.",
            code="heure_inexistante",
        )
    return instant


def plage_locale(jour: date, debut: time, fin: time, jour_fin: date | None = None) -> tuple[datetime, datetime]:
    """Début et fin conscients du fuseau ; une fin avant le début désigne le lendemain (créneau de nuit)."""
    d = _instant_local(jour, debut)
    f = _instant_local(jour_fin or jour, fin)
    if f <= d:
        f = _instant_local((jour_fin or jour) + timedelta(days=1), fin)
    return d, f


def generer_plages(reservation: Reservation) -> list[tuple[datetime, datetime]]:
    """Plages (début, fin) de la réservation, exclusions appliquées (vacances zone C, fériés, exdates)."""
    regle = valider_regle(reservation.recurrence)
    if not regle:
        return [plage_locale(reservation.date_debut, reservation.heure_debut, reservation.heure_fin, reservation.date_fin)]
    depart = datetime.combine(reservation.date_debut, reservation.heure_debut)
    if "UNTIL=" not in regle and "COUNT=" not in regle:
        regle += ";UNTIL=" + reservation.date_fin.strftime("%Y%m%d") + "T235959"
    regle = re.sub(r"UNTIL=(\d{8})(T\d{6})?Z?", lambda m: f"UNTIL={m.group(1)}{m.group(2) or 'T235959'}", regle)
    exclus = jours_exclus_pour(reservation) | set(reservation.exdates)
    plages = []
    for instant in rrulestr(f"RRULE:{regle}", dtstart=depart):
        if instant.date() > reservation.date_fin:
            break
        if instant.date() in exclus:
            continue
        plages.append(plage_locale(instant.date(), reservation.heure_debut, reservation.heure_fin))
        if len(plages) > MAX_OCCURRENCES:
            raise ErreurValidation(
                f"Plus de {MAX_OCCURRENCES} séances : réduisez la période ou la fréquence.", code="trop_d_occurrences"
            )
    return plages


def decrire(reservation: Reservation) -> str:
    """« tous les mardis de 18 h à 20 h, hors vacances scolaires et jours fériés, du 7 septembre 2026 au 26 juin 2027 »."""
    from django.utils.formats import date_format

    horaires = f"de {heure(reservation.heure_debut)} à {heure(reservation.heure_fin)}"
    regle = (reservation.recurrence or "").upper()
    if not regle:
        if reservation.date_debut == reservation.date_fin:
            return f"le {date_format(reservation.date_debut, 'l j F Y')} {horaires}"
        return f"du {date_format(reservation.date_debut, 'j F Y')} {heure(reservation.heure_debut)} au {date_format(reservation.date_fin, 'j F Y')} {heure(reservation.heure_fin)}"
    parties = dict(p.split("=", 1) for p in regle.removeprefix("RRULE:").split(";") if "=" in p)
    intervalle = int(parties.get("INTERVAL", "1"))
    jours = [JOURS[j[-2:]] for j in parties.get("BYDAY", "").split(",") if j[-2:] in JOURS]
    if parties.get("FREQ") == "WEEKLY":
        pluriel = [f"{j}s" for j in jours] or ["semaines"]
        liste = ", ".join(pluriel[:-1]) + (" et " if len(pluriel) > 1 else "") + pluriel[-1]
        texte = f"tous les {liste}" if intervalle == 1 else f"un {', un '.join(jours)} sur {intervalle}"
    elif parties.get("FREQ") == "DAILY":
        texte = "tous les jours" if intervalle == 1 else f"tous les {intervalle} jours"
    else:
        texte = "tous les mois" if intervalle == 1 else f"tous les {intervalle} mois"
    exclusions = [
        e
        for e, actif in (("vacances scolaires", reservation.exclure_vacances), ("jours fériés", reservation.exclure_feries))
        if actif
    ]
    hors = f", hors {' et '.join(exclusions)}" if exclusions else ""
    periode = f", du {date_format(reservation.date_debut, 'j F Y')} au {date_format(reservation.date_fin, 'j F Y')}"
    return f"{texte} {horaires}{hors}{periode}"
