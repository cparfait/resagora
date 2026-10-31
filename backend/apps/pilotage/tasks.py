from __future__ import annotations

from celery import shared_task

from . import impressions


@shared_task(name="apps.pilotage.tasks.envoyer_plannings")
def envoyer_plannings() -> int:
    """IMP-04 : plannings programmés dus envoyés avec leur PDF (toutes les heures, idempotent)."""
    return impressions.envoyer_plannings_dus()
