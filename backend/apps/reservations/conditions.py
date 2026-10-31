"""Conditions de confirmation d'une réservation (RG-06), calculées et jamais stockées en booléen libre.

Le type de réservation indique les conditions qui s'appliquent : pièces justificatives, convention
signée, acompte payé, caution reçue. Chaque condition est vérifiée par le module qui la porte
(`enregistrer_verification`) : pièces (ici), convention (documents), acompte et caution (finances).
Refus par défaut : une condition exigée sans vérification disponible est « manquante ».
Une condition constatée hors application (ex. chèque de caution remis au guichet) peut être attestée
par un agent habilité à valider, avec motif ; l'attestation est journalisée (`attester`).
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

from django.utils import timezone

if TYPE_CHECKING:
    from .models import Reservation


@dataclass(frozen=True)
class Condition:
    code: str
    libelle: str
    applicable: Callable[[Reservation], bool]
    manque: Callable[[Reservation], str | None]  # None si satisfaite, sinon ce qu'il manque


REGISTRE: dict[str, Condition] = {}
VERIFICATIONS: dict[str, Callable[[Reservation], str | None]] = {}


def enregistrer(condition: Condition) -> None:
    REGISTRE[condition.code] = condition


def enregistrer_verification(code: str, verification: Callable[[Reservation], str | None]) -> None:
    """Le module qui porte la condition (documents, finances) fournit sa vérification."""
    VERIFICATIONS[code] = verification


def _attestee(reservation: Reservation, code: str) -> bool:
    return code in (reservation.dossier.conditions_attestees or {})


def _verifiee(code: str, a_defaut: str) -> Callable[[Reservation], str | None]:
    def manque(reservation: Reservation) -> str | None:
        if _attestee(reservation, code):
            return None
        verification = VERIFICATIONS.get(code)
        return verification(reservation) if verification is not None else a_defaut

    return manque


def conditions_manquantes(reservation: Reservation) -> list[str]:
    """Ce qu'il reste à faire pour confirmer la réservation (vide = confirmable)."""
    manques = []
    for condition in REGISTRE.values():
        if condition.applicable(reservation):
            message = condition.manque(reservation)
            if message:
                manques.append(message)
    return manques


def _pieces_manquantes(reservation: Reservation) -> str | None:
    """Les pièces doivent être valides sur toute la durée d'occupation, pas seulement au premier jour."""
    from apps.usagers.services import pieces_manquantes

    if _attestee(reservation, "pieces"):
        return None
    derniere = reservation.occurrences.exclude(statut__in=["annulee", "refusee"]).order_by("-debut").first()
    fin = timezone.localtime(derniere.debut).date() if derniere is not None else reservation.date_fin
    manquantes = {
        p.pk: p for p in pieces_manquantes(reservation.dossier.usager, max(reservation.date_debut, timezone.localdate()))
    }
    manquantes.update({p.pk: p for p in pieces_manquantes(reservation.dossier.usager, max(fin, timezone.localdate()))})
    if not manquantes:
        return None
    return "fournir des pièces justificatives valides jusqu'à la dernière séance : " + ", ".join(
        p.libelle for p in manquantes.values()
    )


enregistrer(
    Condition(
        "pieces", "Dossier complet (pièces justificatives)", lambda r: r.dossier.type_reservation.exige_pieces, _pieces_manquantes
    )
)
enregistrer(
    Condition(
        "convention",
        "Convention ou contrat signé",
        lambda r: r.dossier.type_reservation.exige_convention,
        _verifiee("convention", "faire signer la convention ou le contrat"),
    )
)
enregistrer(
    Condition(
        "acompte",
        "Acompte payé",
        lambda r: r.dossier.type_reservation.exige_acompte,
        _verifiee("acompte", "régler l'acompte"),
    )
)
enregistrer(
    Condition(
        "caution",
        "Caution reçue",
        lambda r: r.dossier.type_reservation.exige_caution,
        _verifiee("caution", "déposer la caution"),
    )
)


def attester(dossier: Any, code: str, *, acteur: Any, motif: str) -> Any:
    """Constat manuel d'une condition (pièce papier, chèque de caution au guichet…), tracé au journal."""
    from django.db import transaction

    from apps.audit.services import journaliser
    from apps.habilitations.services import exiger
    from apps.noyau.exceptions import ErreurValidation

    if code not in REGISTRE:
        raise ErreurValidation("Condition inconnue.", code="condition_inconnue")
    if len(motif.strip()) < 5:
        raise ErreurValidation("Indiquez ce qui a été constaté (motif).", code="motif_requis")
    with transaction.atomic():
        for reservation in dossier.reservations.all():
            exiger(acteur, "valider_reservation", reservation)
        attestations = dict(dossier.conditions_attestees or {})
        attestations[code] = {"par": str(acteur), "le": timezone.now().isoformat(), "motif": motif.strip()}
        dossier.conditions_attestees = attestations
        dossier.save(update_fields=["conditions_attestees"])
        journaliser("attester_condition", dossier, apres={"condition": code, "motif": motif.strip()}, acteur=acteur)
    return dossier
