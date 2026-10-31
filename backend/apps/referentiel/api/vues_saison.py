"""API : saisons et calendrier (ADM-01), horaires (REF-03), fermetures (REF-06), photos et documents d'espace (REF-01, REF-08)."""

from __future__ import annotations

from typing import Any

from django.db import transaction
from django.http import FileResponse
from drf_spectacular.utils import extend_schema
from rest_framework import serializers, status
from rest_framework.decorators import action
from rest_framework.parsers import JSONParser, MultiPartParser
from rest_framework.request import Request
from rest_framework.response import Response

from apps.audit.services import instantane, journaliser
from apps.habilitations.authentification import agent_courant
from apps.noyau import fichiers
from apps.noyau.api import VuePerimetre
from apps.noyau.exceptions import ErreurMetier

from ..calendrier import importer_saison
from ..models import DocumentEspace, Espace, Fermeture, HoraireOuverture, PeriodeCalendrier, PhotoEspace, Saison

DROITS = {"lecture": "lire_referentiel", "ecriture": "gerer_referentiel"}


class SaisonSerializer(serializers.ModelSerializer):
    class Meta:
        model = Saison
        fields = ["id", "nom", "debut", "fin", "active"]


class PeriodeSerializer(serializers.ModelSerializer):
    class Meta:
        model = PeriodeCalendrier
        fields = ["id", "saison", "nature", "libelle", "debut", "fin", "zone", "source"]
        read_only_fields = ["source"]


class HoraireSerializer(serializers.ModelSerializer):
    class Meta:
        model = HoraireOuverture
        fields = ["id", "espace", "saison", "jour_semaine", "debut", "fin", "pendant_vacances"]


class FermetureSerializer(serializers.ModelSerializer):
    seances_touchees = serializers.IntegerField(read_only=True, default=0)

    class Meta:
        model = Fermeture
        fields = ["id", "site", "espace", "debut", "fin", "motif", "cree_le", "seances_touchees"]
        read_only_fields = ["cree_le"]

    def validate(self, donnees: dict[str, Any]) -> dict[str, Any]:
        if bool(donnees.get("site")) == bool(donnees.get("espace")):
            raise serializers.ValidationError("Choisissez soit un site entier, soit un espace.")
        if donnees["fin"] <= donnees["debut"]:
            raise serializers.ValidationError({"fin": "La fin doit suivre le début."})
        return donnees


class PhotoSerializer(serializers.ModelSerializer):
    class Meta:
        model = PhotoEspace
        fields = ["id", "espace", "description", "ordre"]


class DocumentSerializer(serializers.ModelSerializer):
    nom_fichier = serializers.CharField(source="fichier.nom_origine", read_only=True)

    class Meta:
        model = DocumentEspace
        fields = ["id", "espace", "nature", "titre", "public", "nom_fichier"]


class DepotSerializer(serializers.Serializer):
    espace = serializers.PrimaryKeyRelatedField(queryset=Espace.objects.all())
    fichier = serializers.FileField()
    description = serializers.CharField(max_length=250, required=False, default="")
    titre = serializers.CharField(max_length=200, required=False, default="")
    nature = serializers.ChoiceField(choices=[n for n, _ in DocumentEspace.NATURES], required=False, default="reglement")
    public = serializers.BooleanField(required=False, default=True)
    ordre = serializers.IntegerField(required=False, default=0)


class VueSaisons(VuePerimetre):
    queryset = Saison.objects.all()
    serializer_class = SaisonSerializer
    actions_requises = {"lecture": "lire_referentiel", "ecriture": "gerer_parametres", "importer_calendrier": "gerer_parametres"}

    @extend_schema(request=None, responses={200: dict})
    @action(detail=True, methods=["post"], url_path="importer-calendrier")
    def importer_calendrier(self, request: Request, pk: str | None = None) -> Response:
        """ADM-01 : vacances de la zone et jours fériés de la saison depuis les données nationales."""
        saison = self.get_object()
        nombre = importer_saison(saison, acteur=agent_courant(request))
        return Response({"periodes": nombre})


class VuePeriodes(VuePerimetre):
    queryset = PeriodeCalendrier.objects.select_related("saison")
    serializer_class = PeriodeSerializer
    actions_requises = {"lecture": "lire_referentiel", "ecriture": "gerer_parametres"}
    filterset_fields = ["saison", "nature"]
    pagination_class = None


class VueHoraires(VuePerimetre):
    queryset = HoraireOuverture.objects.select_related("espace__batiment")
    serializer_class = HoraireSerializer
    actions_requises = DROITS
    chemin_site = "espace__batiment__site"
    filterset_fields = ["espace", "saison", "jour_semaine"]
    pagination_class = None


class VueFermetures(VuePerimetre):
    queryset = Fermeture.objects.select_related("site", "espace__batiment")
    serializer_class = FermetureSerializer
    actions_requises = DROITS
    filterset_fields = ["site", "espace"]
    http_method_names = ["get", "post", "delete", "head", "options"]

    def get_queryset(self) -> Any:
        from apps.habilitations.services import sites_autorises

        qs = super(VuePerimetre, self).get_queryset()
        sites = sites_autorises(agent_courant(self.request), "lire_referentiel")
        return qs if sites is None else qs.filter(site__in=sites) | qs.filter(espace__batiment__site__in=sites)

    def perform_create(self, serializer: Any) -> None:
        from apps.reservations.services import enregistrer_fermeture

        with transaction.atomic():
            fermeture = serializer.save(cree_par=agent_courant(self.request))
            self._verifier_objet(fermeture)
            touchees = enregistrer_fermeture(fermeture, acteur=agent_courant(self.request))
            fermeture.seances_touchees = len(touchees)


class _VueFichierEspace(VuePerimetre):
    chemin_site = "espace__batiment__site"
    actions_requises = {**DROITS, "fichier": "lire_referentiel"}
    parser_classes = [MultiPartParser, JSONParser]
    http_method_names = ["get", "post", "patch", "delete", "head", "options"]
    filterset_fields = ["espace"]

    def _enregistrer(self, request: Request) -> tuple[Any, Any]:
        donnees = DepotSerializer(data=request.data)
        donnees.is_valid(raise_exception=True)
        espace = donnees.validated_data["espace"]
        self._verifier_objet(espace)
        televerse = donnees.validated_data["fichier"]
        types = ("image/jpeg", "image/png") if self.serializer_class is PhotoSerializer else ("application/pdf",)
        fichier = fichiers.enregistrer(
            televerse.name, televerse.read(), types_autorises=types, depose_par=str(agent_courant(request))
        )
        return donnees.validated_data, fichier

    @action(detail=True, methods=["get"])
    def fichier(self, request: Request, pk: str | None = None) -> FileResponse:
        objet = self.get_object()
        return fichiers.reponse_telechargement(objet.fichier, en_ligne=self.serializer_class is PhotoSerializer)


class VuePhotos(_VueFichierEspace):
    queryset = PhotoEspace.objects.select_related("espace__batiment", "fichier")
    serializer_class = PhotoSerializer

    @extend_schema(request={"multipart/form-data": DepotSerializer}, responses=PhotoSerializer)
    def create(self, request: Request, *args: Any, **kwargs: Any) -> Response:
        donnees, fichier = self._enregistrer(request)
        if not donnees["description"].strip():
            raise ErreurMetier("Décrivez la photo (texte alternatif obligatoire).", code="description_requise")
        photo = PhotoEspace.objects.create(
            espace=donnees["espace"], fichier=fichier, description=donnees["description"], ordre=donnees["ordre"]
        )
        journaliser("ajouter_photo_espace", photo, apres=instantane(photo))
        return Response(PhotoSerializer(photo).data, status=status.HTTP_201_CREATED)


class VueDocumentsEspace(_VueFichierEspace):
    queryset = DocumentEspace.objects.select_related("espace__batiment", "fichier")
    serializer_class = DocumentSerializer

    @extend_schema(request={"multipart/form-data": DepotSerializer}, responses=DocumentSerializer)
    def create(self, request: Request, *args: Any, **kwargs: Any) -> Response:
        donnees, fichier = self._enregistrer(request)
        document = DocumentEspace.objects.create(
            espace=donnees["espace"],
            fichier=fichier,
            titre=donnees["titre"] or fichier.nom_origine,
            nature=donnees["nature"],
            public=donnees["public"],
        )
        journaliser("ajouter_document_espace", document, apres=instantane(document))
        return Response(DocumentSerializer(document).data, status=status.HTTP_201_CREATED)
