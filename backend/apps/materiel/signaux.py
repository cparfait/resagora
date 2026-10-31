"""Le matériel suit les réservations (D-059) : séance déplacée ou supprimée, réservation refusée, annulée, expirée
ou validée. Les annulations de séances passent par le crochet `annulation` des réservations."""

from __future__ import annotations

from typing import Any

from django.db.models.signals import post_save, pre_delete
from django.dispatch import receiver

from apps.reservations.models import Occurrence, Reservation

from . import services
from .models import ReservationMateriel


@receiver(post_save, sender=Occurrence)
def occurrence_enregistree(sender: type[Occurrence], instance: Occurrence, created: bool, **_: Any) -> None:
    if created or not ReservationMateriel.objects.filter(occurrence=instance, statut__in=services.STATUTS_EN_COURS).exists():
        return
    services.apres_deplacement(instance)


@receiver(pre_delete, sender=Occurrence)
def occurrence_supprimee(sender: type[Occurrence], instance: Occurrence, **_: Any) -> None:
    services.avant_suppression(instance)


@receiver(post_save, sender=Reservation)
def reservation_enregistree(sender: type[Reservation], instance: Reservation, created: bool, **_: Any) -> None:
    if created or not ReservationMateriel.objects.filter(reservation=instance, statut__in=services.STATUTS_EN_COURS).exists():
        return
    services.apres_changement_statut(instance)
