"""Jeu de démonstration, lot 6 : envoi hebdomadaire programmé du planning du premier gymnase (IMP-04), le vendredi
à 16 h, vers deux boîtes de service fictives du domaine de la Ville (seul domaine autorisé, D-062) ; en recette,
tout courriel aboutit dans Mailpit."""

from __future__ import annotations

from datetime import time
from typing import Any

from apps.referentiel.models import Espace

from . import impressions
from .models import EnvoiProgramme

SYSTEME = "système"


def charger(resultat: dict[str, Any]) -> dict[str, int]:
    if EnvoiProgramme.objects.exists():
        return {}
    espace = (
        Espace.objects.filter(batiment__site__code__startswith="demo-", famille__code="gymnase", parent__isnull=True)
        .order_by("pk")
        .first()
    )
    if espace is None:
        return {}
    envoi = EnvoiProgramme.objects.create(
        libelle=f"Planning hebdomadaire — {espace.nom}",
        espace=espace,
        destinataires=["gardiens.demo@chatillon92.fr", "service.sports.demo@chatillon92.fr"],
        jour_semaine=4,
        heure=time(16, 0),
    )
    impressions.programmer(envoi, acteur=SYSTEME)
    return {"envois_planning": 1}
