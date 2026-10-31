"""Catalogue public des espaces réservables (POR-03) : uniquement les informations publiques."""

from __future__ import annotations

from django.db.models import QuerySet
from django.http import FileResponse, Http404
from rest_framework import generics, serializers
from rest_framework.request import Request

from apps.noyau import fichiers
from apps.referentiel.models import DocumentEspace, Espace, FamilleEspace, PhotoEspace, Site

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
    photos = serializers.SerializerMethodField()
    documents = serializers.SerializerMethodField()

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
            "photos",
            "documents",
        ]

    def get_parent(self, espace: Espace) -> int | None:
        parent = _parent_public(espace)
        return parent.pk if parent else None

    def get_parent_nom(self, espace: Espace) -> str | None:
        parent = _parent_public(espace)
        return parent.nom if parent else None

    def get_photos(self, espace: Espace) -> list[dict[str, object]]:
        return [
            {"id": p.pk, "description": p.description, "url": f"/api/portail/catalogue/espaces/{espace.pk}/photos/{p.pk}"}
            for p in espace.photos.order_by("ordre", "pk")
        ]

    def get_documents(self, espace: Espace) -> list[dict[str, object]]:
        return [
            {
                "id": d.pk,
                "titre": d.titre,
                "nature": d.get_nature_display(),
                "taille": d.fichier.taille,
                "format": d.fichier.type_mime.rsplit("/", 1)[-1].upper(),
                "url": f"/api/portail/catalogue/espaces/{espace.pk}/documents/{d.pk}",
            }
            for d in espace.documents.filter(public=True).select_related("fichier")
        ]


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


class VuePhotoPublique(VuePublique):
    """Photo d'un espace publié (affichée dans la page : `inline`)."""

    def get(self, request: Request, pk: int, photo: int) -> FileResponse:
        trouvee = (
            PhotoEspace.objects.filter(pk=photo, espace__in=espaces_publics().filter(pk=pk)).select_related("fichier").first()
        )
        if trouvee is None:
            raise Http404
        reponse = fichiers.reponse_telechargement(trouvee.fichier, en_ligne=True)
        reponse["Cache-Control"] = "public, max-age=3600"
        return reponse


class VueDocumentPublic(VuePublique):
    """Règlement, plan ou consignes d'un espace publié (REF-08)."""

    def get(self, request: Request, pk: int, document: int) -> FileResponse:
        trouve = (
            DocumentEspace.objects.filter(pk=document, public=True, espace__in=espaces_publics().filter(pk=pk))
            .select_related("fichier")
            .first()
        )
        if trouve is None:
            raise Http404
        return fichiers.reponse_telechargement(trouve.fichier)
