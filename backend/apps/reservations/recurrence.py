"""Récurrences RFC 5545 (PLA-04) : génération des occurrences en heure de Paris, exclusions, description lisible.

Les calculs se font en heure locale (Europe/Paris) puis sont stockés en UTC : un créneau « 18 h – 20 h »
reste à 18 h après le changement d'heure d'octobre ou de mars.
"""

from __future__ import annotations

import re
from datetime import date, datetime, time, timedelta
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
REGLE_AUTORISEE = re.compile(r"^(FREQ=(DAILY|WEEKLY|MONTHLY))(;(INTERVAL=\d{1,2}|BYDAY=(\+?-?\d?(MO|TU|WE|TH|FR|SA|SU),?)+|UNTIL=\d{8}(T\d{6}Z?)?|COUNT=\d{1,3}|BYMONTHDAY=-?\d{1,2}|WKST=(MO|SU)))*$")


def heure(t: time) -> str:
    return f"{t.hour} h" if t.minute == 0 else f"{t.hour} h {t.minute:02d}"


def valider_regle(regle: str) -> str:
    regle = regle.strip().upper().removeprefix("RRULE:")
    if regle and not REGLE_AUTORISEE.match(regle):
        raise ErreurValidation("Règle de récurrence non reconnue (FREQ, INTERVAL, BYDAY, UNTIL ou COUNT).", code="recurrence_invalide")
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


def plage_locale(jour: date, debut: time, fin: time, jour_fin: date | None = None) -> tuple[datetime, datetime]:
    """Début et fin conscients du fuseau ; une fin avant le début désigne le lendemain (créneau de nuit)."""
    d = datetime.combine(jour, debut, tzinfo=PARIS)
    f = datetime.combine(jour_fin or jour, fin, tzinfo=PARIS)
    if f <= d:
        f = datetime.combine((jour_fin or jour) + timedelta(days=1), fin, tzinfo=PARIS)
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
            raise ErreurValidation(f"Plus de {MAX_OCCURRENCES} séances : réduisez la période ou la fréquence.", code="trop_d_occurrences")
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
    exclusions = [e for e, actif in (("vacances scolaires", reservation.exclure_vacances), ("jours fériés", reservation.exclure_feries)) if actif]
    hors = f", hors {' et '.join(exclusions)}" if exclusions else ""
    periode = f", du {date_format(reservation.date_debut, 'j F Y')} au {date_format(reservation.date_fin, 'j F Y')}"
    return f"{texte} {horaires}{hors}{periode}"
