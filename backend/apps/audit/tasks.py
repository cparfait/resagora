from __future__ import annotations

import logging

from celery import shared_task

from .services import ancrer, verifier_chaine

journal = logging.getLogger(__name__)


@shared_task(name="apps.audit.tasks.verifier_integrite")
def verifier_integrite() -> dict[str, object]:
    """Vérification périodique de la chaîne du journal d'audit (SEC-08) ; alerte en cas de rupture."""
    resultat = verifier_chaine()
    if not resultat.integre:
        journal.error("Journal d'audit : %d anomalie(s) d'intégrité", len(resultat.anomalies))
    return {"entrees": resultat.entrees_verifiees, "anomalies": resultat.anomalies}


@shared_task(name="apps.audit.tasks.ancrer_journal")
def ancrer_journal() -> int | None:
    """Ancrage horaire de la chaîne (détection de troncature, SEC-08)."""
    ancrage = ancrer()
    return ancrage.dernier_id if ancrage else None
