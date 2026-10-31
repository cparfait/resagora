"""Aides de test des réservations : dossiers et réservations prêts à l'emploi."""

from __future__ import annotations

from datetime import date, datetime, time
from typing import Any

from apps.referentiel.models import Espace
from apps.reservations import services
from apps.reservations.models import Reservation, TypeReservation
from apps.usagers.models import Usager
from tests.fabriques import usager_avec_contact

SYSTEME = services.SYSTEME


def reserver(
    espace: Espace,
    jour: date,
    debut: str,
    fin: str,
    *,
    usager: Usager | None = None,
    acteur: Any = SYSTEME,
    type_code: str = "ponctuelle",
    recurrence: str = "",
    date_fin: date | None = None,
    statut: str = "demande",
    **champs: Any,
) -> Reservation:
    usager = usager or usager_avec_contact()
    dossier = services.creer_dossier(
        acteur=acteur, usager=usager, type_reservation=TypeReservation.objects.get(code=type_code), objet="Entraînement"
    )
    reservation = services.ajouter_reservation(
        dossier,
        acteur=acteur,
        espace=espace,
        date_debut=jour,
        date_fin=date_fin or jour,
        heure_debut=time.fromisoformat(debut),
        heure_fin=time.fromisoformat(fin),
        recurrence=recurrence,
        **champs,
    )
    if statut == "validee":
        reservation = valider_systeme(reservation)
    return reservation


def valider_systeme(reservation: Reservation) -> Reservation:
    """Validation sans contrôle de droits (préparation des jeux d'essai)."""
    services._changer_statut(reservation, "validee", SYSTEME)
    for occurrence in reservation.occurrences.filter(statut="validee"):
        services.poser_verrous(occurrence)
    return reservation


def paris(annee: int, mois: int, jour: int, heure: int, minute: int = 0) -> datetime:
    from apps.reservations.recurrence import PARIS

    return datetime(annee, mois, jour, heure, minute, tzinfo=PARIS)
