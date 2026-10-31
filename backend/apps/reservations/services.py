"""Règles de gestion des réservations (PLA-04 à PLA-12, REF-03, REF-05 à REF-07, RG-01 à RG-03, RG-06, RG-07).

Toutes les transitions passent par ce module : contrôle des droits (rôle × périmètre), verrou de ligne
(`select_for_update`), journal d'audit et notifications après validation de la transaction.
"""

from __future__ import annotations

import logging
from collections.abc import Iterable
from dataclasses import dataclass, field
from datetime import date, datetime, time, timedelta
from typing import Any

from django.db import IntegrityError, transaction
from django.db.backends.postgresql.psycopg_any import DateTimeTZRange
from django.db.models import Q, QuerySet
from django.utils import timezone
from django.utils.formats import date_format

from apps.audit.services import instantane, journaliser
from apps.communication.services import notifier
from apps.habilitations.services import exiger
from apps.noyau.exceptions import ErreurMetier, ErreurValidation
from apps.noyau.numerotation import numero
from apps.noyau.parametres import parametre
from apps.referentiel.models import Espace, Fermeture, HoraireOuverture
from apps.usagers.models import Contact, Usager

from . import conditions
from .models import STATUTS_BLOQUANTS, Dossier, ListeAttente, Occurrence, Reservation, TypeReservation, Verrou
from .recurrence import PARIS, generer_plages, valider_regle

journal = logging.getLogger(__name__)
SYSTEME = "système"
TRANSITIONS = {
    "demande": {"en_instruction", "option", "validee", "refusee", "annulee"},
    "en_instruction": {"option", "validee", "refusee", "annulee"},
    "option": {"validee", "refusee", "annulee", "en_instruction"},
    "validee": {"confirmee", "annulee", "realisee"},
    "confirmee": {"annulee", "realisee"},
    "realisee": {"cloturee"},
    "cloturee": set(),
    "refusee": set(),
    "annulee": set(),
}


@dataclass
class Conflit:
    occurrence_id: int
    reservation_id: int
    dossier: str
    usager: str
    espace: str
    debut: datetime
    fin: datetime

    def en_dict(self) -> dict[str, Any]:
        return {
            "occurrence": self.occurrence_id, "reservation": self.reservation_id, "dossier": self.dossier, "usager": self.usager,
            "espace": self.espace, "debut": self.debut.isoformat(), "fin": self.fin.isoformat(),
        }


@dataclass
class Apercu:
    plages: list[tuple[datetime, datetime]]
    conflits: list[Conflit] = field(default_factory=list)
    hors_horaires: list[datetime] = field(default_factory=list)
    fermetures: list[datetime] = field(default_factory=list)


def _texte_date(instant: datetime) -> str:
    return date_format(timezone.localtime(instant), "l j F Y à H\\hi")


def _verifier_transition(reservation: Reservation, cible: str) -> None:
    if cible not in TRANSITIONS[reservation.statut]:
        raise ErreurMetier(
            f"Passage impossible de « {reservation.get_statut_display()} » à « {dict(Reservation._meta.get_field('statut').choices)[cible]} ».",
            code="transition_interdite",
        )


# --- Horaires, fermetures, conflits -------------------------------------------------------------


def dans_les_horaires(espace: Espace, debut: datetime, fin: datetime) -> bool:
    """REF-03 : sans horaire saisi, l'espace est ouvert ; sinon le créneau tient dans une plage du jour."""
    from apps.referentiel.calendrier import est_vacances

    horaires = HoraireOuverture.objects.filter(espace=espace)
    if not horaires.exists():
        return True
    local_debut, local_fin = timezone.localtime(debut, PARIS), timezone.localtime(fin, PARIS)
    if local_fin.date() != local_debut.date() and local_fin.time() != time(0, 0):
        return False
    jour = local_debut.date()
    du_jour = horaires.filter(jour_semaine=local_debut.weekday())
    propres = du_jour.filter(saison__debut__lte=jour, saison__fin__gte=jour)
    candidates = propres if propres.exists() else du_jour.filter(saison__isnull=True)
    if est_vacances(jour):
        candidates = candidates.filter(pendant_vacances=True)
    fin_locale = local_fin.time() if local_fin.time() != time(0, 0) else time(23, 59, 59)
    return any(h.debut <= local_debut.time() and fin_locale <= h.fin for h in candidates)


def fermetures_touchant(espace: Espace, debut: datetime, fin: datetime) -> QuerySet[Fermeture]:
    lies = espace.ids_lies()
    return Fermeture.objects.filter(Q(espace_id__in=lies) | Q(site_id=espace.batiment.site_id), debut__lt=fin, fin__gt=debut)


def conflits(espace: Espace, debut: datetime, fin: datetime, exclure: Iterable[int] = ()) -> list[Conflit]:
    """RG-01 : occurrences bloquantes qui occupent une feuille de cet espace sur la période.

    Pour une feuille partageable (REF-07), il y a conflit si la capacité simultanée est atteinte ou si une
    occupation exclusive (réservation de l'espace englobant) la couvre.
    """
    plage = DateTimeTZRange(debut, fin, "[)")
    trouves: dict[int, Conflit] = {}
    for feuille in espace.feuilles():
        verrous = Verrou.objects.filter(feuille=feuille, plage__overlap=plage).exclude(occurrence_id__in=list(exclure))
        verrous = verrous.select_related("occurrence__reservation__dossier__usager", "occurrence__espace")
        if feuille.partageable and feuille.pk == espace.pk:
            exclusifs = [v for v in verrous if not v.partage]
            if not exclusifs and verrous.count() < feuille.capacite_simultanee:
                continue
            retenus = exclusifs or list(verrous)
        else:
            retenus = list(verrous)
        for v in retenus:
            o = v.occurrence
            trouves[o.pk] = Conflit(o.pk, o.reservation_id, o.reservation.dossier.numero, o.reservation.dossier.usager.nom, o.espace.nom, o.debut, o.fin)
    return sorted(trouves.values(), key=lambda c: c.debut)


def poser_verrous(occurrence: Occurrence) -> None:
    """Pose les verrous d'une occurrence bloquante ; la contrainte d'exclusion tranche les accès concurrents."""
    if occurrence.statut not in STATUTS_BLOQUANTS or occurrence.verrous.exists():
        return
    feuilles = occurrence.espace.feuilles()
    partageables = [f.pk for f in feuilles if f.partageable]
    if partageables:
        list(Espace.objects.select_for_update().filter(pk__in=partageables))
    trouves = conflits(occurrence.espace, occurrence.debut, occurrence.fin, exclure=[occurrence.pk])
    if trouves:
        raise ErreurMetier(
            f"Créneau déjà occupé le {_texte_date(occurrence.debut)} ({trouves[0].usager}, dossier {trouves[0].dossier}).",
            code="conflit", details={"conflits": [c.en_dict() for c in trouves]},
        )
    plage = DateTimeTZRange(occurrence.debut, occurrence.fin, "[)")
    try:
        with transaction.atomic():
            for feuille in feuilles:
                Verrou.objects.create(occurrence=occurrence, feuille=feuille, plage=plage, partage=feuille.partageable and feuille.pk == occurrence.espace_id)
    except IntegrityError as erreur:
        raise ErreurMetier(
            f"Créneau pris à l'instant par une autre validation ({_texte_date(occurrence.debut)}). Rechargez le planning.",
            code="conflit_concurrent",
        ) from erreur


def retirer_verrous(occurrence: Occurrence) -> None:
    occurrence.verrous.all().delete()


# --- Création et récurrences --------------------------------------------------------------------


def apercu(espace: Espace, plages_ou_reservation: Reservation | list[tuple[datetime, datetime]], exclure: Iterable[int] = ()) -> Apercu:
    plages = generer_plages(plages_ou_reservation) if isinstance(plages_ou_reservation, Reservation) else plages_ou_reservation
    resultat = Apercu(plages)
    for debut, fin in plages:
        resultat.conflits.extend(conflits(espace, debut, fin, exclure))
        if not dans_les_horaires(espace, debut, fin):
            resultat.hors_horaires.append(debut)
        if fermetures_touchant(espace, debut, fin).exists():
            resultat.fermetures.append(debut)
    return resultat


@transaction.atomic
def creer_dossier(
    *, acteur: Any, usager: Usager, type_reservation: TypeReservation, objet: str, contact: Contact | None = None,
    origine: str = "guichet", **champs: Any,
) -> Dossier:
    if usager.statut in {"suspendu", "anonymise"}:
        raise ErreurMetier("Cet usager ne peut pas déposer de demande (compte suspendu).", code="usager_suspendu")
    annee = timezone.localdate().year
    dossier = Dossier.objects.create(
        numero=numero("D", annee), usager=usager, type_reservation=type_reservation, objet=objet, contact=contact, origine=origine,
        cree_par=acteur if hasattr(acteur, "habilitations") else None, depose_le=None if champs.get("brouillon") else timezone.now(),
        **champs,
    )
    journaliser("creer_dossier", dossier, apres=instantane(dossier), acteur=acteur)
    return dossier


def _valider_creneau(espace: Espace, reservation: Reservation, forcer_horaires: bool) -> list[tuple[datetime, datetime]]:
    if not espace.actif:
        raise ErreurValidation("Cet espace n'est pas réservable.", code="espace_inactif")
    plages = generer_plages(reservation)
    if not plages:
        raise ErreurValidation("Aucune séance : vérifiez la période, les jours et les exclusions (vacances, fériés).", code="aucune_occurrence")
    duree_max = int(parametre("reservations.duree_max_minutes"))
    for debut, fin in plages:
        if reservation.recurrence and (fin - debut).total_seconds() / 60 > duree_max:
            raise ErreurValidation("Durée de séance supérieure au maximum autorisé.", code="duree_excessive")
        if not forcer_horaires and not dans_les_horaires(espace, debut, fin):
            raise ErreurValidation(f"Le {_texte_date(debut)} est en dehors des horaires d'ouverture de {espace.nom}.", code="hors_horaires")
    return plages


@transaction.atomic
def ajouter_reservation(
    dossier: Dossier, *, acteur: Any, espace: Espace, date_debut: date, date_fin: date, heure_debut: time, heure_fin: time,
    recurrence: str = "", exclure_vacances: bool = True, exclure_feries: bool = True, exdates: list[date] | None = None,
    forcer_horaires: bool = False,
) -> Reservation:
    """PLA-04 : la réservation est créée en « demande » ; ses occurrences sont matérialisées sans verrou (RG-02)."""
    if acteur != SYSTEME and hasattr(acteur, "habilitations"):
        exiger(acteur, "creer_reservation", espace)
    reservation = Reservation(
        dossier=dossier, espace=espace, date_debut=date_debut, date_fin=date_fin, heure_debut=heure_debut, heure_fin=heure_fin,
        recurrence=valider_regle(recurrence), exclure_vacances=exclure_vacances, exclure_feries=exclure_feries, exdates=exdates or [],
    )
    plages = _valider_creneau(espace, reservation, forcer_horaires)
    reservation.save()
    Occurrence.objects.bulk_create([Occurrence(reservation=reservation, espace=espace, debut=d, fin=f, statut="demande") for d, f in plages])
    journaliser("ajouter_reservation", reservation, apres={**instantane(reservation), "occurrences": len(plages)}, acteur=acteur)
    return reservation


def _occurrences_modifiables(reservation: Reservation, a_partir: datetime | None = None) -> QuerySet[Occurrence]:
    qs = reservation.occurrences.exclude(statut__in=["realisee", "cloturee", "annulee"])
    return qs.filter(debut__gte=a_partir) if a_partir else qs


def rematerialiser(reservation: Reservation, a_partir: datetime | None = None) -> None:
    """Recalcule les occurrences futures non modifiées individuellement selon la règle courante."""
    a_partir = a_partir or timezone.now()
    for occurrence in _occurrences_modifiables(reservation, a_partir).filter(modifiee_individuellement=False):
        retirer_verrous(occurrence)
        occurrence.delete()
    existantes = {o.debut for o in reservation.occurrences.all()}
    for debut, fin in generer_plages(reservation):
        if debut >= a_partir and debut not in existantes:
            occurrence = Occurrence.objects.create(reservation=reservation, espace=reservation.espace, debut=debut, fin=fin, statut=reservation.statut)
            poser_verrous(occurrence)


# --- Transitions --------------------------------------------------------------------------------


def _verrouiller(reservation: Reservation) -> Reservation:
    return Reservation.objects.select_for_update().select_related("dossier__usager", "dossier__type_reservation", "espace__batiment").get(pk=reservation.pk)


def _contexte(reservation: Reservation, **autres: Any) -> dict[str, Any]:
    return {"dossier": reservation.dossier, "reservation": reservation, **autres}


@transaction.atomic
def instruire(reservation: Reservation, *, acteur: Any) -> Reservation:
    reservation = _verrouiller(reservation)
    exiger(acteur, "instruire_reservation", reservation)
    _verifier_transition(reservation, "en_instruction")
    return _changer_statut(reservation, "en_instruction", acteur)


def _changer_statut(reservation: Reservation, statut: str, acteur: Any, **champs: Any) -> Reservation:
    avant = {"statut": reservation.statut}
    reservation.statut = statut
    for cle, valeur in champs.items():
        setattr(reservation, cle, valeur)
    reservation.save()
    reservation.occurrences.exclude(statut__in=["annulee", "realisee", "cloturee"]).update(statut=statut)
    journaliser(f"reservation_{statut}", reservation, avant=avant, apres={"statut": statut, **{k: str(v) for k, v in champs.items()}}, acteur=acteur)
    return reservation


@transaction.atomic
def mettre_en_option(reservation: Reservation, *, acteur: Any, jours: int | None = None) -> Reservation:
    """PLA-08 : pré-réservation avec date d'expiration ; ne bloque pas le créneau (RG-02)."""
    reservation = _verrouiller(reservation)
    exiger(acteur, "valider_reservation", reservation)
    _verifier_transition(reservation, "option")
    expire = timezone.now() + timedelta(days=jours if jours is not None else int(parametre("options.duree_jours")))
    return _changer_statut(reservation, "option", acteur, option_expire_le=expire, option_relancee_le=None)


@transaction.atomic
def valider(reservation: Reservation, *, acteur: Any) -> Reservation:
    """Valide la demande : les occurrences deviennent bloquantes et posent leurs verrous (RG-01)."""
    reservation = _verrouiller(reservation)
    exiger(acteur, "valider_reservation", reservation)
    _verifier_transition(reservation, "validee")
    _changer_statut(reservation, "validee", acteur, valide_par=acteur if hasattr(acteur, "habilitations") else None, valide_le=timezone.now())
    for occurrence in reservation.occurrences.filter(statut="validee"):
        poser_verrous(occurrence)
    manques = conditions.conditions_manquantes(reservation)
    notifier("reservation_validee", _contexte(reservation, conditions="; ".join(manques)), usager=reservation.dossier.usager, objet=reservation)
    return reservation


@transaction.atomic
def refuser(reservation: Reservation, *, acteur: Any, motif: str, alternatives: str = "") -> Reservation:
    reservation = _verrouiller(reservation)
    exiger(acteur, "valider_reservation", reservation)
    if not motif.strip():
        raise ErreurValidation("Le refus doit être motivé.", code="motif_requis")
    _verifier_transition(reservation, "refusee")
    _changer_statut(reservation, "refusee", acteur, motif_refus=motif.strip())
    notifier("reservation_refusee", _contexte(reservation, motif=motif, alternatives=alternatives), usager=reservation.dossier.usager, objet=reservation)
    return reservation


@transaction.atomic
def confirmer(reservation: Reservation, *, acteur: Any) -> Reservation:
    """RG-06 : confirmation seulement si toutes les conditions du type de réservation sont réunies."""
    reservation = _verrouiller(reservation)
    exiger(acteur, "confirmer_reservation", reservation)
    _verifier_transition(reservation, "confirmee")
    manques = conditions.conditions_manquantes(reservation)
    if manques:
        raise ErreurMetier("Confirmation impossible : " + " ; ".join(manques) + ".", code="conditions_non_remplies", details={"manques": manques})
    _changer_statut(reservation, "confirmee", acteur, confirme_le=timezone.now())
    notifier("reservation_confirmee", _contexte(reservation), usager=reservation.dossier.usager, objet=reservation)
    return reservation


def est_tardive(occurrence: Occurrence, instant: datetime | None = None) -> bool:
    instant = instant or timezone.now()
    return occurrence.debut - instant < timedelta(hours=int(parametre("annulation.delai_tardif_heures")))


def _annuler_occurrence(occurrence: Occurrence, motif: str, par_usager: bool, acteur: Any, notifier_usager: bool = True) -> Occurrence:
    tardive = par_usager and est_tardive(occurrence)
    avant = {"statut": occurrence.statut}
    occurrence.statut = "annulee"
    occurrence.annulee_le = timezone.now()
    occurrence.motif_annulation = motif
    occurrence.annulation_tardive = tardive
    occurrence.annulee_par_usager = par_usager
    occurrence.save()
    retirer_verrous(occurrence)
    journaliser("annuler_occurrence", occurrence, avant=avant, apres={"motif": motif, "tardive": tardive, "par_usager": par_usager}, acteur=acteur)
    proposer_liste_attente(occurrence)
    if notifier_usager and not par_usager:
        notifier(
            "occurrence_annulee", {"date": _texte_date(occurrence.debut), "espace": occurrence.espace.nom, "motif": motif},
            usager=occurrence.reservation.dossier.usager, objet=occurrence,
        )
    return occurrence


@transaction.atomic
def annuler_occurrence(occurrence: Occurrence, *, acteur: Any, motif: str, par_usager: bool = False) -> Occurrence:
    """PLA-10 : annulation d'une séance ; tardive (RG-08) si l'usager annule dans le délai paramétré."""
    occurrence = Occurrence.objects.select_for_update().select_related("reservation__dossier__usager", "espace__batiment").get(pk=occurrence.pk)
    if hasattr(acteur, "habilitations"):
        exiger(acteur, "annuler_reservation", occurrence)
    if occurrence.statut in {"annulee", "realisee", "cloturee", "refusee"}:
        raise ErreurMetier("Cette séance ne peut plus être annulée.", code="transition_interdite")
    if not motif.strip():
        raise ErreurValidation("Indiquez le motif de l'annulation.", code="motif_requis")
    return _annuler_occurrence(occurrence, motif.strip(), par_usager, acteur)


@transaction.atomic
def annuler(reservation: Reservation, *, acteur: Any, motif: str, par_usager: bool = False) -> Reservation:
    """Annule la réservation et toutes ses séances à venir."""
    reservation = _verrouiller(reservation)
    if hasattr(acteur, "habilitations"):
        exiger(acteur, "annuler_reservation", reservation)
    _verifier_transition(reservation, "annulee")
    if not motif.strip():
        raise ErreurValidation("Indiquez le motif de l'annulation.", code="motif_requis")
    for occurrence in reservation.occurrences.filter(debut__gte=timezone.now()).exclude(statut__in=["annulee", "realisee", "cloturee"]):
        _annuler_occurrence(occurrence, motif.strip(), par_usager, acteur, notifier_usager=False)
    reservation.statut = "annulee"
    reservation.motif_annulation = motif.strip()
    reservation.annulee_le = timezone.now()
    reservation.annulee_par_usager = par_usager
    reservation.save()
    journaliser("annuler_reservation", reservation, apres={"motif": motif, "par_usager": par_usager}, acteur=acteur)
    if not par_usager:
        notifier("occurrence_annulee", {"date": reservation.description, "espace": reservation.espace.nom, "motif": motif},
                 usager=reservation.dossier.usager, objet=reservation)
    return reservation


@transaction.atomic
def saisir_presence(occurrence: Occurrence, *, acteur: Any, presence: str, debut_reel: datetime | None = None, fin_reel: datetime | None = None) -> Occurrence:
    """PLA-11 : présence et heures réelles ; une séance passée validée ou confirmée devient « réalisée »."""
    occurrence = Occurrence.objects.select_for_update().get(pk=occurrence.pk)
    if hasattr(acteur, "habilitations"):
        exiger(acteur, "cloturer_reservation", occurrence)
    if presence not in {"present", "absent_signale", "absent_non_signale"}:
        raise ErreurValidation("Présence inconnue.", code="presence_invalide")
    if occurrence.statut not in {"validee", "confirmee", "realisee"}:
        raise ErreurMetier("La présence se saisit sur une séance validée ou confirmée.", code="transition_interdite")
    if occurrence.debut > timezone.now() + timedelta(hours=1):
        raise ErreurMetier("La présence ne peut pas être saisie avant la séance.", code="seance_future")
    if debut_reel and fin_reel and fin_reel <= debut_reel:
        raise ErreurValidation("L'heure de fin réelle doit suivre l'heure de début.", code="heures_invalides")
    occurrence.presence = presence
    occurrence.debut_reel, occurrence.fin_reel = debut_reel, fin_reel
    occurrence.statut = "realisee"
    occurrence.save()
    journaliser("saisir_presence", occurrence, apres={"presence": presence}, acteur=acteur)
    return occurrence


@transaction.atomic
def cloturer(reservation: Reservation, *, acteur: Any) -> Reservation:
    reservation = _verrouiller(reservation)
    exiger(acteur, "cloturer_reservation", reservation)
    if reservation.occurrences.filter(fin__gt=timezone.now()).exclude(statut__in=["annulee"]).exists():
        raise ErreurMetier("Des séances sont encore à venir : clôture impossible.", code="seances_a_venir")
    reservation.occurrences.filter(statut__in=["validee", "confirmee"]).update(statut="realisee")
    reservation.statut = "realisee"
    _verifier_transition(reservation, "cloturee")
    return _changer_statut(reservation, "cloturee", acteur)


def marquer_realisees() -> int:
    """Tâche quotidienne : les séances passées validées ou confirmées deviennent réalisées."""
    return Occurrence.objects.filter(fin__lt=timezone.now(), statut__in=["validee", "confirmee"]).update(statut="realisee")


# --- Modifications : cette séance, celle-ci et les suivantes, toute la série (PLA-04) ---------------


@transaction.atomic
def deplacer_occurrence(occurrence: Occurrence, *, acteur: Any, espace: Espace, debut: datetime, fin: datetime, forcer_horaires: bool = False) -> Occurrence:
    """PLA-02 / « cette séance seulement » : contrôle de conflit côté serveur puis déplacement."""
    occurrence = Occurrence.objects.select_for_update().select_related("reservation__dossier", "espace").get(pk=occurrence.pk)
    exiger(acteur, "valider_reservation", occurrence)
    exiger(acteur, "valider_reservation", espace)
    if occurrence.statut in {"annulee", "realisee", "cloturee", "refusee"}:
        raise ErreurMetier("Cette séance ne peut plus être déplacée.", code="transition_interdite")
    if fin <= debut:
        raise ErreurValidation("La fin doit suivre le début.", code="heures_invalides")
    if not forcer_horaires and not dans_les_horaires(espace, debut, fin):
        raise ErreurValidation("Nouveau créneau en dehors des horaires d'ouverture.", code="hors_horaires")
    avant = {"espace": occurrence.espace_id, "debut": occurrence.debut.isoformat(), "fin": occurrence.fin.isoformat()}
    retirer_verrous(occurrence)
    if occurrence.debut_origine is None:
        occurrence.debut_origine, occurrence.espace_origine = occurrence.debut, occurrence.espace
    occurrence.espace, occurrence.debut, occurrence.fin = espace, debut, fin
    occurrence.modifiee_individuellement = True
    occurrence.signalement = ""
    occurrence.save()
    poser_verrous(occurrence)
    journaliser("deplacer_occurrence", occurrence, avant=avant, apres={"espace": espace.pk, "debut": debut.isoformat(), "fin": fin.isoformat()}, acteur=acteur)
    return occurrence


CHAMPS_SERIE = {"espace", "heure_debut", "heure_fin", "date_fin", "recurrence", "exclure_vacances", "exclure_feries", "exdates"}


@transaction.atomic
def modifier_serie(reservation: Reservation, *, acteur: Any, **changements: Any) -> Reservation:
    """« Toute la série » : nouvelle règle appliquée aux séances futures non modifiées individuellement."""
    reservation = _verrouiller(reservation)
    exiger(acteur, "valider_reservation", reservation)
    inconnus = set(changements) - CHAMPS_SERIE
    if inconnus:
        raise ErreurValidation("Champs non modifiables : " + ", ".join(sorted(inconnus)), code="champs_invalides")
    if "espace" in changements:
        exiger(acteur, "valider_reservation", changements["espace"])
    avant = instantane(reservation)
    for cle, valeur in changements.items():
        setattr(reservation, cle, valider_regle(valeur) if cle == "recurrence" else valeur)
    _valider_creneau(reservation.espace, reservation, forcer_horaires=False)
    reservation.save()
    rematerialiser(reservation)
    journaliser("modifier_serie", reservation, avant=avant, apres=instantane(reservation), acteur=acteur)
    return reservation


@transaction.atomic
def modifier_suivantes(occurrence: Occurrence, *, acteur: Any, **changements: Any) -> Reservation:
    """« Celle-ci et les suivantes » : la série est coupée la veille ; une nouvelle réservation porte la suite."""
    occurrence = Occurrence.objects.select_related("reservation").get(pk=occurrence.pk)
    origine = _verrouiller(occurrence.reservation)
    exiger(acteur, "valider_reservation", origine)
    jour = timezone.localtime(occurrence.debut, PARIS).date()
    if jour <= origine.date_debut:
        return modifier_serie(origine, acteur=acteur, **changements)
    suite = Reservation.objects.get(pk=origine.pk)
    suite.pk = None
    suite._state.adding = True
    suite.date_debut = jour
    for cle, valeur in changements.items():
        if cle not in CHAMPS_SERIE:
            raise ErreurValidation(f"Champ non modifiable : {cle}", code="champs_invalides")
        setattr(suite, cle, valider_regle(valeur) if cle == "recurrence" else valeur)
    if "espace" in changements:
        exiger(acteur, "valider_reservation", changements["espace"])
    _valider_creneau(suite.espace, suite, forcer_horaires=False)
    origine.date_fin = jour - timedelta(days=1)
    origine.save()
    a_partir = datetime.combine(jour, time.min, tzinfo=PARIS)
    for o in origine.occurrences.filter(debut__gte=a_partir).exclude(statut__in=["realisee", "cloturee"]):
        retirer_verrous(o)
        o.delete()
    suite.save()
    for debut, fin in generer_plages(suite):
        nouvelle = Occurrence.objects.create(reservation=suite, espace=suite.espace, debut=debut, fin=fin, statut=suite.statut)
        poser_verrous(nouvelle)
    journaliser("modifier_suivantes", suite, avant={"reservation_origine": origine.pk, "jour": jour.isoformat()}, apres=instantane(suite), acteur=acteur)
    return suite


# --- Options (RG-07) ----------------------------------------------------------------------------


def traiter_options(maintenant: datetime | None = None) -> dict[str, int]:
    """Tâche planifiée idempotente : relance avant expiration, puis libération d'une option expirée et relancée."""
    maintenant = maintenant or timezone.now()
    delai = timedelta(days=int(parametre("options.relance_jours_avant")))
    bilan = {"relancees": 0, "liberees": 0}
    for reservation in Reservation.objects.filter(statut="option", option_relancee_le__isnull=True, option_expire_le__lte=maintenant + delai):
        with transaction.atomic():
            r = _verrouiller(reservation)
            if r.statut != "option" or r.option_relancee_le is not None:
                continue
            r.option_relancee_le = maintenant
            if r.option_expire_le and r.option_expire_le <= maintenant:
                r.option_expire_le = maintenant + timedelta(days=1)  # délai de grâce après une relance tardive
            r.save(update_fields=["option_relancee_le", "option_expire_le"])
            notifier("option_relance", _contexte(r, expire_le=_texte_date(r.option_expire_le)), usager=r.dossier.usager, objet=r)
            journaliser("relancer_option", r, apres={"expire_le": r.option_expire_le.isoformat()}, acteur=SYSTEME)
            bilan["relancees"] += 1
    for reservation in Reservation.objects.filter(statut="option", option_relancee_le__isnull=False, option_expire_le__lte=maintenant):
        with transaction.atomic():
            r = _verrouiller(reservation)
            if r.statut != "option":
                continue
            _changer_statut(r, "annulee", SYSTEME, motif_annulation="Option expirée après relance", annulee_le=maintenant)
            notifier("option_expiree", _contexte(r), usager=r.dossier.usager, objet=r)
            bilan["liberees"] += 1
    return bilan


# --- Liste d'attente (PLA-09) -------------------------------------------------------------------


@transaction.atomic
def inscrire_liste_attente(*, acteur: Any, espace: Espace, debut: datetime, fin: datetime, usager: Usager, contact: Contact | None = None) -> ListeAttente:
    if hasattr(acteur, "habilitations"):
        exiger(acteur, "creer_reservation", espace)
    inscription = ListeAttente.objects.create(espace=espace, debut=debut, fin=fin, usager=usager, contact=contact)
    journaliser("inscrire_liste_attente", inscription, acteur=acteur)
    return inscription


def proposer_liste_attente(occurrence: Occurrence) -> ListeAttente | None:
    """À la libération d'un créneau, le premier inscrit dont la demande tient dans la place libérée est prévenu."""
    if occurrence.debut <= timezone.now():
        return None
    candidats = ListeAttente.objects.filter(
        espace_id__in=occurrence.espace.ids_lies(), statut="attente", debut__gte=occurrence.debut, fin__lte=occurrence.fin
    ).order_by("cree_le")
    for inscription in candidats:
        if not conflits(inscription.espace, inscription.debut, inscription.fin):
            inscription.statut = "proposee"
            inscription.notifie_le = timezone.now()
            inscription.save(update_fields=["statut", "notifie_le"])
            notifier(
                "liste_attente_place", {"espace": inscription.espace.nom, "date": _texte_date(inscription.debut)},
                usager=inscription.usager, contacts=[inscription.contact] if inscription.contact else [], objet=inscription,
            )
            return inscription
    return None


# --- Alternatives (PLA-07) ----------------------------------------------------------------------


def alternatives(espace: Espace, debut: datetime, fin: datetime, nombre: int = 3) -> list[dict[str, Any]]:
    """Propose des créneaux libres : même espace plus tôt ou plus tard le même jour, espace de même
    famille sur le même site au même horaire, puis même créneau les semaines suivantes."""
    duree = fin - debut
    propositions: list[dict[str, Any]] = []

    def essayer(e: Espace, d: datetime, raison: str) -> None:
        f = d + duree
        if len(propositions) < nombre and d > timezone.now() and not conflits(e, d, f) and dans_les_horaires(e, d, f) and not fermetures_touchant(e, d, f).exists():
            cle = (e.pk, d)
            if all((p["espace"], p["debut"]) != (e.pk, d.isoformat()) for p in propositions) and cle:
                propositions.append({"espace": e.pk, "espace_nom": e.nom, "debut": d.isoformat(), "fin": f.isoformat(), "raison": raison})

    for decalage in (30, -30, 60, -60, 90, -90, 120, -120):
        essayer(espace, debut + timedelta(minutes=decalage), "même espace, autre horaire")
    voisins = Espace.objects.filter(famille=espace.famille, batiment__site=espace.batiment.site, actif=True).exclude(pk__in=espace.ids_lies())
    for voisin in voisins:
        essayer(voisin, debut, "autre espace de même type sur le site")
    for semaines in (1, 2, 3):
        essayer(espace, debut + timedelta(weeks=semaines), "même créneau, semaine suivante")
    return propositions


# --- Fermetures exceptionnelles (REF-06) ---------------------------------------------------------


@transaction.atomic
def enregistrer_fermeture(fermeture: Fermeture, *, acteur: Any) -> list[Occurrence]:
    """Signale les séances touchées et prévient les usagers concernés (une notification par usager)."""
    espaces = [e.pk for e in fermeture.espaces_concernes()]
    lies: set[int] = set()
    for e in Espace.objects.filter(pk__in=espaces):
        lies |= e.ids_lies()
    touchees = list(
        Occurrence.objects.filter(espace_id__in=lies, debut__lt=fermeture.fin, fin__gt=fermeture.debut)
        .exclude(statut__in=["annulee", "refusee", "realisee", "cloturee"])
        .select_related("reservation__dossier__usager", "espace")
    )
    par_usager: dict[int, list[Occurrence]] = {}
    for occurrence in touchees:
        occurrence.signalement = f"Fermeture : {fermeture.motif}"
        occurrence.save(update_fields=["signalement"])
        par_usager.setdefault(occurrence.reservation.dossier.usager_id, []).append(occurrence)
    lieu = fermeture.espace.nom if fermeture.espace else fermeture.site.nom if fermeture.site else ""
    for occurrences in par_usager.values():
        usager = occurrences[0].reservation.dossier.usager
        notifier(
            "fermeture_exceptionnelle",
            {"lieu": lieu, "debut": _texte_date(fermeture.debut), "fin": _texte_date(fermeture.fin), "motif": fermeture.motif,
             "seances": "\n".join(f"- {o.espace.nom}, {_texte_date(o.debut)}" for o in occurrences)},
            usager=usager, objet=fermeture,
        )
    journaliser("enregistrer_fermeture", fermeture, apres={"occurrences_touchees": len(touchees)}, acteur=acteur)
    return touchees


# --- Priorité municipale (PLA-12) ----------------------------------------------------------------


@transaction.atomic
def imposer_priorite_municipale(
    reservation: Reservation, *, acteur: Any, motif: str, deplacements: dict[int, tuple[Espace, datetime, datetime] | None] | None = None,
) -> Reservation:
    """Valide une réservation de la Ville en déplaçant (ou annulant sans frais) les séances qui la gênent."""
    reservation = _verrouiller(reservation)
    exiger(acteur, "deplacer_priorite", reservation)
    if reservation.dossier.usager.type != "service_municipal":
        raise ErreurMetier("La priorité municipale ne s'applique qu'aux réservations des services de la Ville.", code="non_municipal")
    if not motif.strip():
        raise ErreurValidation("Indiquez la manifestation ou le motif.", code="motif_requis")
    deplacements = deplacements or {}
    a_traiter: dict[int, Occurrence] = {}
    for occurrence in reservation.occurrences.exclude(statut__in=["annulee", "refusee"]):
        for conflit in conflits(occurrence.espace, occurrence.debut, occurrence.fin, exclure=[occurrence.pk]):
            a_traiter[conflit.occurrence_id] = Occurrence.objects.select_related("reservation__dossier__usager", "espace").get(pk=conflit.occurrence_id)
    for identifiant, gene in a_traiter.items():
        cible = deplacements.get(identifiant)
        ancien = _texte_date(gene.debut)
        if cible is not None:
            espace, debut, fin = cible
            deplacer_occurrence(gene, acteur=acteur, espace=espace, debut=debut, fin=fin, forcer_horaires=True)
            nouveau = f"{espace.nom}, {_texte_date(debut)}"
        else:
            _annuler_occurrence(gene, f"Priorité municipale : {motif}", par_usager=False, acteur=acteur, notifier_usager=False)
            nouveau = ""
        notifier(
            "priorite_municipale", {"manifestation": reservation.dossier.objet, "date": ancien, "espace": gene.espace.nom, "nouveau": nouveau, "motif": motif},
            usager=gene.reservation.dossier.usager, objet=gene,
        )
    if reservation.statut in {"demande", "en_instruction", "option"}:
        _changer_statut(reservation, "validee", acteur, valide_par=acteur, valide_le=timezone.now())
    for occurrence in reservation.occurrences.filter(statut__in=STATUTS_BLOQUANTS):
        poser_verrous(occurrence)
    journaliser("priorite_municipale", reservation, apres={"motif": motif, "seances_traitees": len(a_traiter)}, acteur=acteur)
    return reservation
