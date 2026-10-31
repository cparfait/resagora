"""Cautions (CAU-01 à CAU-07, RG-11) : réception, restitution après l'état des lieux de sortie, retenue motivée
validée par un second agent au-delà du seuil, journal inaltérable, état exportable, alerte de délai."""

from __future__ import annotations

import csv
import io
from datetime import date, timedelta
from typing import Any

from django.conf import settings
from django.db import transaction
from django.db.models import QuerySet
from django.utils import timezone

from apps.audit.services import journaliser
from apps.communication.services import notifier
from apps.habilitations.models import Utilisateur
from apps.noyau.exceptions import ErreurMetier, ErreurValidation
from apps.noyau.montants import euros
from apps.noyau.parametres import parametre
from apps.noyau.tableur import cellule_sure
from apps.reservations.models import Occurrence, Reservation

from .facturation import _controler
from .models import Caution, EtatDesLieux, MouvementCaution
from .tarification import categorie, caution_exigee, tarif_de_reference

TRANSITIONS = {
    "attendue": {"recue"},
    "recue": {"restituable", "retenue_a_valider", "retenue_partielle", "retenue_totale"},
    "restituable": {"restituee", "retenue_a_valider", "retenue_partielle", "retenue_totale"},
    "retenue_a_valider": {"retenue_partielle", "retenue_totale", "restituable"},
    "retenue_partielle": {"solde_restitue"},
    "solde_restitue": {"encaissee"},
    "retenue_totale": {"encaissee"},
    "restituee": set(),
    "encaissee": set(),
}


def _mouvement(caution: Caution, action: str, cible: str, acteur: Any, *, montant: int = 0, motif: str = "") -> None:
    if cible not in TRANSITIONS[caution.statut]:
        raise ErreurMetier(
            f"Une caution « {caution.get_statut_display()} » ne peut pas passer à cet état.", code="transition_caution"
        )
    MouvementCaution.objects.create(
        caution=caution,
        action=action,
        statut_avant=caution.statut,
        statut_apres=cible,
        montant=montant,
        motif=motif,
        agent=str(acteur)[:200],
    )
    journaliser(
        f"caution_{action}", caution, avant={"statut": caution.statut}, apres={"statut": cible, "montant": montant}, acteur=acteur
    )
    caution.statut = cible


def preparer(reservation: Reservation) -> Caution | None:
    """CAU-01 : à la validation, la caution prévue par la grille pour l'espace et l'usager est attendue."""
    if not reservation.dossier.type_reservation.exige_caution or Caution.objects.filter(reservation=reservation).exists():
        return None
    montant = caution_exigee(reservation.espace, reservation.dossier.usager, reservation.date_debut)
    if montant <= 0:
        return None
    caution = Caution.objects.create(
        dossier=reservation.dossier, reservation=reservation, usager=reservation.dossier.usager, montant=montant
    )
    MouvementCaution.objects.create(
        caution=caution, action="attendue", statut_avant="", statut_apres="attendue", montant=montant, agent="système"
    )
    return caution


@transaction.atomic
def recevoir(caution: Caution, *, acteur: Any, mode: str, reference: str, jour: date | None = None) -> Caution:
    caution = Caution.objects.select_for_update().get(pk=caution.pk)
    _controler(acteur, "gerer_caution", caution)
    if mode not in dict(Caution.MODES):
        raise ErreurValidation("Mode de dépôt inconnu.", code="mode_invalide")
    if not reference.strip():
        raise ErreurValidation("Indiquez la référence du dépôt (n° de chèque, de consignation…).", code="reference_requise")
    _mouvement(
        caution, "recue", "recue", acteur, montant=caution.montant, motif=f"{dict(Caution.MODES)[mode]} — {reference.strip()}"
    )
    caution.mode, caution.reference, caution.recue_le = mode, reference.strip()[:100], jour or timezone.localdate()
    if _restituable(caution):
        # Caution déposée après un état des lieux de sortie déjà conforme : elle est aussitôt restituable.
        _mouvement(caution, "restituable", "restituable", acteur, motif="État des lieux de sortie déjà conforme")
    caution.save()
    return caution


#: Un état des lieux de sortie se fait en fin de séance : 15 minutes d'avance au plus sur l'heure de fin (RG-11).
AVANCE_SORTIE = timedelta(minutes=15)


def degats_sur_la_reservation(caution: Caution) -> bool:
    """Des dégâts relevés à la sortie d'une séance quelconque de la réservation bloquent la restitution (RG-11)."""
    return EtatDesLieux.objects.filter(occurrence__reservation=caution.reservation, moment="sortie", constat="degats").exists()


def _restituable(caution: Caution) -> bool:
    etat = etat_de_sortie(caution)
    return etat is not None and etat.constat == "conforme" and not degats_sur_la_reservation(caution)


def etat_de_sortie(caution: Caution) -> EtatDesLieux | None:
    derniere = caution.reservation.occurrences.exclude(statut__in=["annulee", "refusee"]).order_by("-debut").first()
    if derniere is None:
        return None
    return EtatDesLieux.objects.filter(occurrence=derniere, moment="sortie").first()


@transaction.atomic
def constater_sortie(
    occurrence: Occurrence,
    *,
    acteur: Any,
    constat: str,
    observations: str = "",
    photos: list[Any] | None = None,
    source: str = "backoffice",
    constate_le: Any = None,
) -> EtatDesLieux:
    """État des lieux de sortie, établi après la séance : sans dégât, la caution devient restituable (RG-11)."""
    _controler(acteur, "gerer_caution" if source == "backoffice" else "utiliser_mobile", occurrence)
    if occurrence.statut in {"annulee", "refusee"}:
        raise ErreurMetier("Cette séance est annulée : pas d'état des lieux de sortie.", code="seance_annulee")
    maintenant = timezone.now()
    constate_le = constate_le or maintenant
    if occurrence.fin > maintenant + timedelta(minutes=30) or constate_le < occurrence.fin - AVANCE_SORTIE:
        raise ErreurMetier("L'état des lieux de sortie s'établit à la fin de la séance, pas avant.", code="seance_non_terminee")
    if constate_le > maintenant + timedelta(minutes=5):
        raise ErreurValidation("Heure du constat postérieure à sa saisie : vérifiez l'heure de l'appareil.", code="heure_future")
    if constat not in {"conforme", "degats"}:
        raise ErreurValidation("Constat inconnu.", code="constat_invalide")
    if constat == "degats" and len(observations.strip()) < 5:
        raise ErreurValidation("Décrivez les dégâts constatés.", code="observations_requises")
    etat, cree = EtatDesLieux.objects.get_or_create(
        occurrence=occurrence,
        moment="sortie",
        defaults={
            "constat": constat,
            "observations": observations.strip(),
            "agent": acteur if isinstance(acteur, Utilisateur) else None,
            "source": source,
            "constate_le": constate_le,
        },
    )
    if not cree:
        raise ErreurMetier("L'état des lieux de sortie de cette séance est déjà établi.", code="etat_des_lieux_existant")
    if photos:
        etat.photos.set(photos)
    journaliser("etat_des_lieux_sortie", etat, apres={"constat": constat, "source": source}, acteur=acteur)
    for caution in Caution.objects.select_for_update().filter(reservation=occurrence.reservation, statut="recue"):
        if constat == "conforme" and _restituable(caution):
            _mouvement(caution, "restituable", "restituable", acteur, motif="État des lieux de sortie conforme")
            caution.save()
    if constat == "degats":
        # Le régisseur statue sur une retenue (CAU-04) : il est prévenu dès la réception du constat.
        notifier(
            "etat_des_lieux_degats",
            {
                "espace": occurrence.espace.nom,
                "debut": timezone.localtime(occurrence.debut).strftime("%d/%m/%Y %H:%M"),
                "usager": occurrence.reservation.dossier.usager.nom,
                "dossier": occurrence.reservation.dossier.numero,
                "observations": observations.strip()[:500],
                "lien": f"{settings.BACKOFFICE_URL}/finances/cautions",
            },
            courriels=[str(parametre("portail.service_courriel"))],
            objet=etat,
        )
    return etat


@transaction.atomic
def restituer(caution: Caution, *, acteur: Any, jour: date | None = None) -> Caution:
    """CAU-03, RG-11 : restitution seulement après l'état des lieux de sortie, et s'il est conforme."""
    caution = Caution.objects.select_for_update().get(pk=caution.pk)
    _controler(acteur, "gerer_caution", caution)
    if caution.statut == "retenue_partielle":
        # CAU-02 : après une retenue partielle, le solde (montant moins la retenue) est restitué et tracé.
        solde = caution.montant - caution.montant_retenu
        _mouvement(caution, "solde_restitue", "solde_restitue", acteur, montant=solde, motif="Restitution du solde après retenue")
        caution.restituee_le = jour or timezone.localdate()
        caution.save()
        notifier(
            "caution_restituee",
            {"caution": caution, "montant": euros(solde), "dossier": caution.dossier},
            usager=caution.usager,
            objet=caution,
        )
        return caution
    etat = etat_de_sortie(caution)
    if etat is None:
        raise ErreurMetier("La caution ne peut être restituée qu'après l'état des lieux de sortie.", code="etat_des_lieux_requis")
    if (etat.constat != "conforme" or degats_sur_la_reservation(caution)) and caution.statut != "restituable":
        raise ErreurMetier("Des dégâts ont été constatés : statuez d'abord sur une retenue.", code="degats_constates")
    _mouvement(caution, "restituee", "restituee", acteur, montant=caution.montant)
    caution.restituee_le = jour or timezone.localdate()
    caution.save()
    notifier(
        "caution_restituee",
        {"caution": caution, "montant": euros(caution.montant), "dossier": caution.dossier},
        usager=caution.usager,
        objet=caution,
    )
    return caution


@transaction.atomic
def proposer_retenue(caution: Caution, *, acteur: Any, montant: int, motif: str, photos: list[Any] | None = None) -> Caution:
    """CAU-04 : motif, photos et montant ; au-delà du seuil, un second agent doit valider (CAU-05)."""
    caution = Caution.objects.select_for_update().get(pk=caution.pk)
    _controler(acteur, "proposer_retenue", caution)
    if caution.statut not in {"recue", "restituable"}:
        raise ErreurMetier("Une retenue se propose sur une caution reçue, avant toute décision.", code="transition_caution")
    if etat_de_sortie(caution) is None:
        raise ErreurMetier(
            "Une retenue se fonde sur l'état des lieux de sortie : établissez-le d'abord.", code="etat_des_lieux_requis"
        )
    if not 0 < montant <= caution.montant:
        raise ErreurValidation(f"La retenue est comprise entre 0,01 € et {euros(caution.montant)}.", code="montant_invalide")
    if len(motif.strip()) < 10:
        raise ErreurValidation("Motivez la retenue (nature des dégâts, devis ou coût de remise en état).", code="motif_requis")
    if not photos:
        raise ErreurValidation("Joignez au moins une photo des dégâts.", code="photos_requises")
    caution.montant_retenu, caution.motif_retenue, caution.retenue_proposee_par = (
        montant,
        motif.strip(),
        acteur if isinstance(acteur, Utilisateur) else None,
    )
    caution.photos_retenue.set(photos)
    seuil = int(parametre("caution.seuil_double_validation_centimes"))
    # Après un refus du second agent, toute nouvelle proposition repasse par la validation, quel que soit le montant.
    deja_refusee = caution.mouvements.filter(action="retenue_rejetee").exists()
    if montant > seuil or deja_refusee:
        _mouvement(caution, "retenue_proposee", "retenue_a_valider", acteur, montant=montant, motif=motif)
        caution.save()
        return caution
    return _appliquer_retenue(caution, acteur)


@transaction.atomic
def valider_retenue(caution: Caution, *, acteur: Any, accepter: bool, commentaire: str = "") -> Caution:
    """CAU-05 : le second agent ne peut pas être celui qui a proposé la retenue."""
    caution = Caution.objects.select_for_update().get(pk=caution.pk)
    _controler(acteur, "valider_retenue", caution)
    if caution.statut != "retenue_a_valider":
        raise ErreurMetier("Aucune retenue n'attend de validation.", code="transition_caution")
    if caution.retenue_proposee_par_id is not None and caution.retenue_proposee_par_id == getattr(acteur, "pk", None):
        raise ErreurMetier("Un autre agent doit valider la retenue que vous avez proposée.", code="double_controle")
    if not accepter:
        _mouvement(caution, "retenue_rejetee", "restituable", acteur, motif=commentaire or "Retenue non validée")
        caution.montant_retenu, caution.motif_retenue = 0, ""
        caution.save()
        return caution
    return _appliquer_retenue(caution, acteur)


def _appliquer_retenue(caution: Caution, acteur: Any) -> Caution:
    cible = "retenue_totale" if caution.montant_retenu == caution.montant else "retenue_partielle"
    _mouvement(caution, "retenue", cible, acteur, montant=caution.montant_retenu, motif=caution.motif_retenue)
    caution.save()
    notifier(
        "caution_retenue",
        {
            "caution": caution,
            "dossier": caution.dossier,
            "montant_retenu": euros(caution.montant_retenu),
            "montant_restitue": euros(caution.montant - caution.montant_retenu),
            "motif": caution.motif_retenue,
        },
        usager=caution.usager,
        objet=caution,
    )
    return caution


@transaction.atomic
def encaisser_retenue(caution: Caution, *, acteur: Any, reference: str) -> Caution:
    caution = Caution.objects.select_for_update().get(pk=caution.pk)
    _controler(acteur, "gerer_caution", caution)
    if len(reference.strip()) < 3:
        raise ErreurValidation("Indiquez la référence de l'encaissement (titre, chèque).", code="reference_requise")
    if caution.statut == "retenue_partielle":
        raise ErreurMetier("Restituez d'abord le solde de la caution, puis encaissez la retenue.", code="solde_a_restituer")
    _mouvement(caution, "encaissee", "encaissee", acteur, montant=caution.montant_retenu, motif=reference.strip())
    caution.save()
    return caution


def en_alerte(jour: date | None = None) -> QuerySet[Caution]:
    """CAU-07 : cautions reçues ou restituables dont le délai de restitution après la dernière séance est dépassé."""
    jour = jour or timezone.localdate()
    limite = jour - timedelta(days=int(parametre("caution.delai_restitution_jours")))
    return (
        Caution.objects.filter(
            statut__in=["recue", "restituable", "retenue_a_valider", "retenue_partielle"], reservation__date_fin__lt=limite
        )
        .select_related("usager", "dossier", "reservation__espace")
        .order_by("reservation__date_fin")
    )


def etat_csv(cautions: QuerySet[Caution]) -> bytes:
    """CAU-06 : état exportable (tableur, séparateur point-virgule, montants en euros)."""
    sortie = io.StringIO()
    ecrivain = csv.writer(sortie, delimiter=";")
    ecrivain.writerow(
        [
            "Dossier",
            "Usager",
            "Espace",
            "Fin d'occupation",
            "Montant",
            "État",
            "Mode",
            "Référence",
            "Reçue le",
            "Retenue",
            "Restituée le",
        ]
    )
    for c in cautions.select_related("dossier", "usager", "reservation__espace"):
        ecrivain.writerow(
            [
                cellule_sure(c.dossier.numero),
                cellule_sure(c.usager.nom),
                cellule_sure(c.reservation.espace.nom),
                f"{c.reservation.date_fin:%d/%m/%Y}",
                euros(c.montant),
                c.get_statut_display(),
                c.get_mode_display() if c.mode else "",
                cellule_sure(c.reference),
                f"{c.recue_le:%d/%m/%Y}" if c.recue_le else "",
                euros(c.montant_retenu) if c.montant_retenu else "",
                f"{c.restituee_le:%d/%m/%Y}" if c.restituee_le else "",
            ]
        )
    return ("﻿" + sortie.getvalue()).encode("utf-8")


def caution_manquante(reservation: Reservation) -> str | None:
    """RG-06 « caution reçue »."""
    caution = Caution.objects.filter(reservation=reservation).first() or preparer(reservation)
    if caution is None:
        # Refus par défaut (D-021) : sans tarif de référence, le montant de la caution n'est pas connu.
        try:
            tarif = tarif_de_reference(reservation.espace, categorie(reservation.dossier.usager), reservation.date_debut)
        except ErreurMetier:
            return "caution : aucun tarif de référence ne fixe son montant (grille tarifaire à compléter)"
        return None if tarif.caution_centimes <= 0 else f"déposer la caution de {euros(tarif.caution_centimes)}"
    return None if caution.statut != "attendue" else f"déposer la caution de {euros(caution.montant)}"
