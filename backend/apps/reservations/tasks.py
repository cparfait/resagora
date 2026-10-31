from __future__ import annotations

from celery import shared_task

from . import services


@shared_task(name="apps.reservations.tasks.traiter_options")
def traiter_options() -> dict[str, int]:
    """RG-07 : relance puis libération des options expirées (idempotente, toutes les heures)."""
    return services.traiter_options()


@shared_task(name="apps.reservations.tasks.marquer_realisees")
def marquer_realisees() -> int:
    """Séances passées validées ou confirmées → réalisées (quotidienne)."""
    return services.marquer_realisees()


@shared_task(name="apps.reservations.tasks.rappeler_seances")
def rappeler_seances() -> int:
    return services.rappeler_seances()
