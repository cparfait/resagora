"""Catalogue public des espaces réservables (POR-03) : uniquement les informations publiques."""

from __future__ import annotations

from django.db.models import QuerySet
from rest_framework import generics, serializers

from apps.referentiel.models import Espace, FamilleEspace, Site

from .securite import VuePublique


class SitePublicSerializer(serializers.ModelSerializer):
    class Meta:
        model = Site
        fields = ["id", "nom", "adresse", "code_postal", "commune"]


class FamillePubliqueSerializer(serializers.ModelSerializer):
    class Meta:
        model = FamilleEspace
        fields = ["id", "code", "libelle"]


class EspacePublicSerializer(serializers.ModelSerializer):
    site = serializers.IntegerField(source="batiment.site_id", read_only=True)
    site_nom = serializers.CharField(source="batiment.site.nom", read_only=True)
    adresse = serializers.CharField(source="batiment.site.adresse", read_only=True)
    famille_libelle = serializers.CharField(source="famille.libelle", read_only=True)
    parent = serializers.SerializerMethodField()  # type: ignore[assignment]
    parent_nom = serializers.SerializerMethodField()

    class Meta:
        model = Espace
        fields = [
            "id",
            "nom",
            "site",
            "site_nom",
            "adresse",
            "famille",
            "famille_libelle",
            "parent",
            "parent_nom",
            "description",
            "capacite",
            "surface_m2",
            "accessible_pmr",
            "equipements",
            "activites",
            "partageable",
        ]

    def get_parent(self, espace: Espace) -> int | None:
        parent = _parent_public(espace)
        return parent.pk if parent else None

    def get_parent_nom(self, espace: Espace) -> str | None:
        parent = _parent_public(espace)
        return parent.nom if parent else None


def _parent_public(espace: Espace) -> Espace | None:
    parent = espace.parent
    return parent if parent is not None and parent.actif and parent.reservable_portail else None


def espaces_publics() -> QuerySet[Espace]:
    return Espace.objects.filter(
        actif=True, reservable_portail=True, batiment__actif=True, batiment__site__actif=True
    ).select_related("batiment__site", "famille", "parent")


class VueSitesPublics(VuePublique, generics.ListAPIView):
    serializer_class = SitePublicSerializer
    pagination_class = None

    def get_queryset(self) -> QuerySet[Site]:
        return Site.objects.filter(actif=True, batiments__espaces__in=espaces_publics()).distinct().order_by("nom")


class VueFamillesPubliques(VuePublique, generics.ListAPIView):
    serializer_class = FamillePubliqueSerializer
    pagination_class = None

    def get_queryset(self) -> QuerySet[FamilleEspace]:
        return FamilleEspace.objects.filter(espaces__in=espaces_publics()).distinct().order_by("ordre", "libelle")


class VueEspacesPublics(VuePublique, generics.ListAPIView):
    serializer_class = EspacePublicSerializer
    filterset_fields = ["famille", "batiment__site", "accessible_pmr"]

    def get_queryset(self) -> QuerySet[Espace]:
        qs = espaces_publics()
        capacite = self.request.query_params.get("capacite_min", "")
        if capacite.isdigit():
            qs = qs.filter(capacite__gte=int(capacite))
        recherche = self.request.query_params.get("recherche", "").strip()[:80]
        if recherche:
            qs = qs.filter(nom__unaccent__icontains=recherche) | qs.filter(activites__unaccent__icontains=recherche)
        return qs.order_by("batiment__site__nom", "nom")


class VueEspacePublic(VuePublique, generics.RetrieveAPIView):
    serializer_class = EspacePublicSerializer

    def get_queryset(self) -> QuerySet[Espace]:
        return espaces_publics()
