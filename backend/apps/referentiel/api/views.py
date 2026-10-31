"""Référentiel (REF-01, REF-02) filtré par périmètre (RG-14)."""

from __future__ import annotations

from typing import Any

from django.db import transaction

from apps.noyau.api import VuePerimetre

from ..models import Batiment, Espace, FamilleEspace, Site
from .serializers import BatimentSerializer, EspaceSerializer, FamilleEspaceSerializer, SiteSerializer

DROITS = {"lecture": "lire_referentiel", "ecriture": "gerer_referentiel"}


class VueSites(VuePerimetre):
    queryset = Site.objects.all()
    serializer_class = SiteSerializer
    actions_requises = DROITS
    chemin_site = "pk"
    filterset_fields = ["actif"]


class VueBatiments(VuePerimetre):
    queryset = Batiment.objects.select_related("site")
    serializer_class = BatimentSerializer
    actions_requises = DROITS
    chemin_site = "site"
    filterset_fields = ["site", "actif"]


class VueFamilles(VuePerimetre):
    queryset = FamilleEspace.objects.all()
    serializer_class = FamilleEspaceSerializer
    actions_requises = DROITS


class VueEspaces(VuePerimetre):
    queryset = Espace.objects.select_related("batiment__site", "famille", "parent")
    serializer_class = EspaceSerializer
    actions_requises = DROITS
    chemin_site = "batiment__site"
    filterset_fields = ["batiment", "batiment__site", "famille", "parent", "actif", "gardiennage_requis", "partageable"]

    CHAMPS_HIERARCHIE = ("parent_id", "partageable", "capacite_simultanee")

    def _recalculer(self, espaces: list[Espace]) -> None:
        """REF-05 : un changement de hiérarchie ou de partage replace les verrous (RG-01) ; un conflit annule tout."""
        from apps.reservations.services import recalculer_verrous

        recalculer_verrous([e for e in espaces if e is not None])

    def perform_create(self, serializer: Any) -> None:
        with transaction.atomic():
            super().perform_create(serializer)
            if serializer.instance.parent_id:
                self._recalculer([serializer.instance])

    def perform_update(self, serializer: Any) -> None:
        avant = {c: getattr(serializer.instance, c) for c in self.CHAMPS_HIERARCHIE}
        ancien_parent = serializer.instance.parent
        with transaction.atomic():
            super().perform_update(serializer)
            if any(getattr(serializer.instance, c) != v for c, v in avant.items()):
                self._recalculer([serializer.instance, ancien_parent])
