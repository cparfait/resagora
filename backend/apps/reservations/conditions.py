"""Conditions de confirmation d'une réservation (RG-06), calculées et jamais stockées en booléen libre.

Chaque condition est enregistrée par le module qui la porte : pièces justificatives (ici), convention
signée (documents, lot 2), acompte payé et caution reçue (finances, lot 3). Le type de réservation
indique lesquelles s'appliquent.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import TYPE_CHECKING

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


def enregistrer(condition: Condition) -> None:
    REGISTRE[condition.code] = condition


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
    from apps.usagers.services import pieces_manquantes

    jour = max(reservation.date_debut, timezone.localdate())
    manquantes = pieces_manquantes(reservation.dossier.usager, jour)
    if not manquantes:
        return None
    return "fournir des pièces justificatives valides : " + ", ".join(p.libelle for p in manquantes)


enregistrer(Condition("pieces", "Dossier complet (pièces justificatives)", lambda r: r.dossier.type_reservation.exige_pieces, _pieces_manquantes))
