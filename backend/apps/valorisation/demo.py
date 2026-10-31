"""Jeu de démonstration, lot 6 : exercice en cours, méthodes par famille (tarif voté, valeur locative pour les salles
associatives), subventions en numéraire de trois associations (dont une au-delà du seuil de convention une fois la
valorisation ajoutée), valorisation calculée de tous les bénéficiaires (l'attestation viendra après la clôture de l'exercice)."""

from __future__ import annotations

from typing import Any

from django.utils import timezone

from apps.referentiel.models import FamilleEspace
from apps.usagers.models import Usager

from . import services
from .models import Exercice, MethodeValorisation, SubventionNumeraire

SYSTEME = services.SYSTEME
DELIBERATION = "DCM-DEMO-2025-12-15-08"


def charger(resultat: dict[str, Any]) -> dict[str, int]:
    annee = timezone.localdate().year
    if Exercice.objects.filter(annee=annee).exists():
        return {}
    exercice = Exercice.objects.create(annee=annee)
    for famille in FamilleEspace.objects.all():
        if famille.code == "salle-associative":
            MethodeValorisation.objects.create(
                exercice=exercice,
                famille=famille,
                methode="valeur_locative",
                loyer_m2_annuel_centimes=18_000,
                heures_annuelles_reference=2_400,
                deliberation_reference=DELIBERATION,
            )
        else:
            MethodeValorisation.objects.create(exercice=exercice, famille=famille, methode="tarif_reference")
    associations = list(Usager.objects.filter(type="association").order_by("pk")[:3])
    for rang, (usager, montant) in enumerate(zip(associations, (2_250_000, 800_000, 150_000), strict=False)):
        SubventionNumeraire.objects.create(
            exercice=exercice,
            usager=usager,
            montant_centimes=montant,
            objet="Subvention de fonctionnement",
            deliberation_reference=f"DCM-DEMO-2026-03-{rang + 10}",
        )
    bilan = services.valoriser_exercice(exercice, acteur=SYSTEME)
    # Les attestations s'éditent après la clôture de l'exercice (montants définitifs, VAL-04) puis la signature de
    # l'élu : l'exercice de démonstration, en cours, n'en a pas encore.
    return {"valorisations": bilan["calcules"], "anomalies_valorisation": len(bilan["anomalies"])}
