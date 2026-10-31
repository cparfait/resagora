"""RG-09 : toute création, modification ou annulation de séance gardiennée recalcule les besoins du site et du jour
concernés, après validation de la transaction (une fois par site et par jour, quel que soit le nombre de séances)."""

from __future__ import annotations

import threading
from datetime import date, datetime
from typing import Any

from django.db import transaction
from django.db.models.signals import post_save, pre_save
from django.dispatch import receiver
from django.utils import timezone

from apps.reservations.models import Occurrence, Reservation
from apps.reservations.recurrence import PARIS

_local = threading.local()


def _cles() -> set[tuple[int, date]]:
    if not hasattr(_local, "cles"):
        _local.cles = set()
    return _local.cles  # type: ignore[no-any-return]


def _vider() -> None:
    from .services import recalculer_besoins

    cles = sorted(_cles())
    _cles().clear()
    for site_id, jour in cles:
        recalculer_besoins(site_id, jour)


def planifier(cles: set[tuple[int, date]]) -> None:
    if not cles:
        return
    _cles().update(cles)
    transaction.on_commit(_vider)


def _cle(site_id: int, debut: datetime) -> tuple[int, date]:
    return site_id, timezone.localtime(debut, PARIS).date()


@receiver(pre_save, sender=Occurrence)
def memoriser_ancienne_plage(sender: Any, instance: Occurrence, **kwargs: Any) -> None:
    if instance.pk:
        ancienne = (
            Occurrence.objects.filter(pk=instance.pk)
            .values_list("espace__batiment__site_id", "debut", "espace__gardiennage_requis")
            .first()
        )
        instance._ancienne_plage = ancienne  # type: ignore[attr-defined]


@receiver(post_save, sender=Occurrence)
def occurrence_modifiee(sender: Any, instance: Occurrence, **kwargs: Any) -> None:
    cles = set()
    ancienne = getattr(instance, "_ancienne_plage", None)
    if ancienne and ancienne[2]:
        cles.add(_cle(ancienne[0], ancienne[1]))
    espace = instance.espace
    if espace.gardiennage_requis:
        cles.add(_cle(espace.batiment.site_id, instance.debut))
    planifier(cles)


@receiver(post_save, sender=Reservation)
def reservation_modifiee(sender: Any, instance: Reservation, **kwargs: Any) -> None:
    """Les changements de statut d'une série passent par la réservation (mise à jour groupée des séances)."""
    seances = Occurrence.objects.filter(reservation=instance, espace__gardiennage_requis=True).values_list(
        "espace__batiment__site_id", "debut"
    )
    planifier({_cle(site, debut) for site, debut in seances})
