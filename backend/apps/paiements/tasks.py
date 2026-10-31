"""Tâches du paiement en ligne (TAR-07) : exécutées par le worker, seul conteneur qui joint PayFiP (ADR 0008)."""

from __future__ import annotations

from celery import shared_task

from apps.finances.payfip import PayFiPIndisponible

from . import services
from .models import TentativePaiement


@shared_task(autoretry_for=(PayFiPIndisponible,), retry_backoff=10, retry_backoff_max=300, max_retries=6)
def creer_operation(identifiant: int) -> str:
    tentative = services.creer_operation(identifiant)
    return tentative.statut if tentative else ""


@shared_task(autoretry_for=(PayFiPIndisponible,), retry_backoff=30, retry_backoff_max=1800, max_retries=8)
def verifier(identifiant: int, source: str = "") -> str:
    tentative = TentativePaiement.objects.filter(pk=identifiant).first()
    if tentative is None:
        return ""
    return services.verifier(tentative, source=source or "tache").statut


@shared_task
def rapprocher() -> dict[str, int]:
    if not services.actif():
        return {}
    return services.rapprocher()
