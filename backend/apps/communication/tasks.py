from __future__ import annotations

from celery import shared_task
from django.db import transaction

from .models import Notification
from .services import envoyer


@shared_task(
    name="apps.communication.tasks.envoyer_notification",
    autoretry_for=(OSError, ConnectionError),
    retry_backoff=60,
    retry_backoff_max=3600,
    max_retries=6,
)
def envoyer_notification(identifiant: int) -> bool:
    """Envoi idempotent : la clé d'idempotence est l'identifiant de la notification."""
    with transaction.atomic():
        notification = Notification.objects.filter(pk=identifiant).first()
        if notification is None:
            return False
        return envoyer(notification)


@shared_task(name="apps.communication.tasks.relancer_echecs")
def relancer_echecs() -> int:
    """Reprise périodique des envois en échec (serveur SMTP momentanément indisponible)."""
    nombre = 0
    for identifiant in Notification.objects.filter(statut__in=["a_envoyer", "echec"], tentatives__lt=6).values_list("pk", flat=True)[:500]:
        envoyer_notification.delay(identifiant)
        nombre += 1
    return nombre
