from __future__ import annotations

from celery import shared_task

from . import facturation


@shared_task(name="apps.finances.tasks.expirer_devis")
def expirer_devis() -> int:
    """TAR-08 : les devis non acceptés au terme de leur validité passent « expirés » (quotidienne)."""
    return facturation.expirer_devis()
