"""Référentiel (REF-01, REF-02) filtré par périmètre (RG-14)."""

from __future__ import annotations

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
