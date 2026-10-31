"""Tâches des documents et de la signature : exécutées par le worker, seul conteneur qui joint DocuSeal."""

from __future__ import annotations

from celery import shared_task

from apps.noyau.exceptions import ErreurMetier

from . import services
from .docuseal import DocuSealIndisponible
from .models import CircuitSignature, LotGeneration


@shared_task(name="apps.documents.tasks.executer_lot", queue="documents")
def executer_lot(identifiant: int) -> int:
    lot = LotGeneration.objects.filter(pk=identifiant).first()
    if lot is None or lot.statut == "termine":
        return 0
    return services.executer_lot(lot).faits


@shared_task(
    name="apps.documents.tasks.deposer_signature",
    queue="documents",
    autoretry_for=(DocuSealIndisponible,),
    retry_backoff=60,
    retry_backoff_max=1800,
    max_retries=5,
)
def deposer_signature(identifiant: int) -> str:
    circuit = CircuitSignature.objects.filter(pk=identifiant).first()
    if circuit is None:
        return ""
    try:
        return services.deposer_aupres_de_docuseal(circuit).statut
    except DocuSealIndisponible as erreur:
        if deposer_signature.request.retries >= deposer_signature.max_retries:
            services.signaler_echec_depot(identifiant, erreur.message)
        raise
    except ErreurMetier as erreur:
        services.signaler_echec_depot(identifiant, erreur.message)
        return "erreur"


@shared_task(
    name="apps.documents.tasks.synchroniser_signature",
    queue="documents",
    autoretry_for=(DocuSealIndisponible,),
    retry_backoff=30,
    max_retries=6,
)
def synchroniser_signature(identifiant: int) -> str:
    circuit = CircuitSignature.objects.filter(pk=identifiant).first()
    return services.synchroniser(circuit).statut if circuit is not None else ""


@shared_task(name="apps.documents.tasks.synchroniser_signatures", queue="documents")
def synchroniser_signatures() -> int:
    return services.synchroniser_en_cours()


@shared_task(name="apps.documents.tasks.relancer_signatures", queue="documents")
def relancer_signatures() -> int:
    return services.relancer_signatures()
