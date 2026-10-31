from __future__ import annotations

from celery import shared_task

from . import services


@shared_task(name="apps.materiel.tasks.alerter_controles")
def alerter_controles() -> int:
    """MAT-04 : contrôles périodiques dépassés et consommables sous le seuil signalés au service (hebdomadaire)."""
    return services.alerter_controles()
