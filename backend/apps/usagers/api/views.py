"""API de gestion des usagers, contacts et pièces (USR-01 à USR-05)."""

from __future__ import annotations

import json
from typing import Any

import django_filters
from django.db.models import QuerySet
from django.http import FileResponse, HttpResponse
from drf_spectacular.utils import extend_schema
from rest_framework import serializers, status
from rest_framework.decorators import action
from rest_framework.parsers import JSONParser, MultiPartParser
from rest_framework.request import Request
from rest_framework.response import Response

from apps.audit.services import journaliser
from apps.habilitations.authentification import agent_courant
from apps.habilitations.services import peut, sites_autorises
from apps.noyau import fichiers
from apps.noyau.api import VuePerimetre
from apps.noyau.exceptions import ErreurValidation

from .. import rgpd, services
from ..models import TYPES_USAGER, Contact, PieceJustificative, Rattachement, TypePiece, Usager

LECTURE_ECRITURE = {"lecture": "lire_usager", "ecriture": "gerer_usager"}


class RattachementSerializer(serializers.ModelSerializer):
    contact_nom = serializers.CharField(source="contact.__str__", read_only=True)
    contact_courriel = serializers.CharField(source="contact.courriel", read_only=True)
    usager_nom = serializers.CharField(source="usager.nom", read_only=True)

    class Meta:
        model = Rattachement
        fields = ["id", "usager", "usager_nom", "contact", "contact_nom", "contact_courriel", "role", "principal", "peut_signer"]


class UsagerSerializer(serializers.ModelSerializer):
    rattachements = RattachementSerializer(many=True, read_only=True)
    type_libelle = serializers.CharField(source="get_type_display", read_only=True)

    class Meta:
        model = Usager
        fields = [
            "id",
            "type",
            "type_libelle",
            "nom",
            "sigle",
            "siret",
            "rna",
            "adresse",
            "code_postal",
            "commune",
            "telephone",
            "courriel",
            "resident",
            "local",
            "conventionne",
            "convention_reference",
            "convention_fin",
            "statut",
            "observations",
            "cree_le",
            "rattachements",
        ]
        read_only_fields = ["resident", "cree_le", "rattachements", "statut"]

    def validate_type(self, valeur: str) -> str:
        """Le type « service municipal » ouvre la priorité municipale (PLA-12) et le premier rang RG-03."""
        actuel = getattr(self.instance, "type", None)
        if "service_municipal" in {valeur, actuel} and valeur != actuel:
            requete = self.context.get("request")
            if requete is None or not peut(agent_courant(requete), "gerer_parametres"):
                raise serializers.ValidationError(
                    "Seule l'administration fonctionnelle peut classer un usager « service municipal »."
                )
        return valeur

    def validate_siret(self, valeur: str) -> str:
        valeur = valeur.replace(" ", "")
        if valeur and (len(valeur) != 14 or not valeur.isdigit()):
            raise serializers.ValidationError("Le SIRET comporte 14 chiffres.")
        return valeur

    def validate_rna(self, valeur: str) -> str:
        valeur = valeur.strip().upper()
        if valeur and not (len(valeur) == 10 and valeur[0] == "W" and valeur[1:].isdigit()):
            raise serializers.ValidationError("Le numéro RNA a la forme W123456789.")
        return valeur


class ContactSerializer(serializers.ModelSerializer):
    rattachements = RattachementSerializer(many=True, read_only=True)

    class Meta:
        model = Contact
        fields = ["id", "civilite", "prenom", "nom", "courriel", "telephone", "rattachements"]

    def validate_courriel(self, valeur: str) -> str:
        """L'adresse d'un contact qui a un compte sur le portail est son identifiant : seul le titulaire la change
        depuis son espace (une modification par un agent permettrait de détourner le compte)."""
        instance = self.instance if isinstance(self.instance, Contact) else None
        compte = getattr(instance, "compte", None)
        if instance is not None and compte is not None and valeur.strip().lower() != instance.courriel.strip().lower():
            raise serializers.ValidationError(
                "Ce contact a un compte sur le portail : il modifie lui-même son adresse depuis son espace."
            )
        return valeur


class TypePieceSerializer(serializers.ModelSerializer):
    class Meta:
        model = TypePiece
        fields = ["id", "code", "libelle", "description", "types_usager", "obligatoire", "validite_mois"]


class PieceSerializer(serializers.ModelSerializer):
    type_libelle = serializers.CharField(source="type_piece.libelle", read_only=True)
    usager_nom = serializers.CharField(source="usager.nom", read_only=True)
    nom_fichier = serializers.CharField(source="fichier.nom_origine", read_only=True)

    class Meta:
        model = PieceJustificative
        fields = [
            "id",
            "usager",
            "usager_nom",
            "type_piece",
            "type_libelle",
            "nom_fichier",
            "valide_du",
            "valide_jusqu_au",
            "statut",
            "motif_refus",
            "verifie_le",
            "depose_le",
            "depose_par_portail",
        ]
        read_only_fields = ["statut", "motif_refus", "verifie_le", "depose_le", "depose_par_portail"]


class DepotPieceSerializer(serializers.Serializer):
    usager = serializers.PrimaryKeyRelatedField(queryset=Usager.objects.exclude(statut="anonymise"))
    type_piece = serializers.PrimaryKeyRelatedField(queryset=TypePiece.objects.all())
    fichier = serializers.FileField()
    valide_jusqu_au = serializers.DateField(required=False, allow_null=True)


class VerificationPieceSerializer(serializers.Serializer):
    valide = serializers.BooleanField()
    motif = serializers.CharField(required=False, allow_blank=True, default="", max_length=250)
    valide_jusqu_au = serializers.DateField(required=False, allow_null=True)


class MotifUsagerSerializer(serializers.Serializer):
    motif = serializers.CharField(max_length=250)


class FiltreUsagers(django_filters.FilterSet):
    recherche = django_filters.CharFilter(method="filtrer")

    class Meta:
        model = Usager
        fields = ["type", "statut", "conventionne", "local", "resident"]

    def filtrer(self, qs: QuerySet[Usager], nom: str, valeur: str) -> QuerySet[Usager]:
        return services.rechercher(qs, valeur)


class VueUsagers(VuePerimetre):
    queryset = Usager.objects.exclude(statut="anonymise").prefetch_related("rattachements__contact")
    serializer_class = UsagerSerializer
    actions_requises = {
        **LECTURE_ECRITURE,
        "historique": "lire_usager",
        "types": "lire_usager",
        "valider": "valider_compte_usager",
        "suspendre": "valider_compte_usager",
        "reactiver": "valider_compte_usager",
        "export": "anonymiser_usager",
        "anonymiser": "anonymiser_usager",
    }
    filterset_class = FiltreUsagers
    http_method_names = ["get", "post", "patch", "head", "options"]

    def _changer_statut(self, request: Request, cible: str, depuis: set[str], motif: str = "") -> Response:
        usager = self.get_object()
        services.changer_statut(usager, cible, depuis=depuis, acteur=agent_courant(request), motif=motif)
        return Response(UsagerSerializer(Usager.objects.get(pk=usager.pk), context={"request": request}).data)

    @extend_schema(request=None, responses=UsagerSerializer)
    @action(detail=True, methods=["post"])
    def valider(self, request: Request, pk: str | None = None) -> Response:
        return self._changer_statut(request, "valide", {"en_attente"})

    @extend_schema(request=MotifUsagerSerializer, responses=UsagerSerializer)
    @action(detail=True, methods=["post"])
    def suspendre(self, request: Request, pk: str | None = None) -> Response:
        donnees = MotifUsagerSerializer(data=request.data)
        donnees.is_valid(raise_exception=True)
        return self._changer_statut(request, "suspendu", {"valide", "en_attente"}, donnees.validated_data["motif"])

    @extend_schema(request=None, responses=UsagerSerializer)
    @action(detail=True, methods=["post"])
    def reactiver(self, request: Request, pk: str | None = None) -> Response:
        return self._changer_statut(request, "valide", {"suspendu"})

    @extend_schema(responses={(200, "application/json"): bytes})
    @action(detail=True, methods=["get"])
    def export(self, request: Request, pk: str | None = None) -> HttpResponse:
        """USR-06 : réponse à une demande d'accès (export complet, journalisé)."""
        usager = self.get_object()
        journaliser("exporter_donnees_usager", usager, acteur=agent_courant(request))
        reponse = HttpResponse(
            json.dumps(rgpd.exporter_usager(usager), ensure_ascii=False, indent=2, default=str),
            content_type="application/json; charset=utf-8",
        )
        reponse["Content-Disposition"] = f'attachment; filename="usager-{usager.pk}-donnees.json"'
        return reponse

    @extend_schema(request=MotifUsagerSerializer, responses=UsagerSerializer)
    @action(detail=True, methods=["post"])
    def anonymiser(self, request: Request, pk: str | None = None) -> Response:
        """USR-06 : droit à l'effacement ou durée échue ; les pièces comptables restent conservées."""
        donnees = MotifUsagerSerializer(data=request.data)
        donnees.is_valid(raise_exception=True)
        usager = rgpd.anonymiser_usager(self.get_object(), acteur=agent_courant(request), motif=donnees.validated_data["motif"])
        return Response(UsagerSerializer(usager, context={"request": request}).data)

    @extend_schema(responses={200: dict})
    @action(detail=True, methods=["get"])
    def historique(self, request: Request, pk: str | None = None) -> Response:
        """USR-05 : dossiers et bilan d'occupation de l'usager."""
        donnees = services.historique(self.get_object(), sites=sites_autorises(agent_courant(request), "lire_reservation"))
        return Response(
            {
                **{k: v for k, v in donnees.items() if k != "dossiers"},
                "dossiers": [
                    {"id": d.pk, "numero": d.numero, "objet": d.objet, "statut": d.statut, "cree_le": d.cree_le}
                    for d in donnees["dossiers"][:200]
                ],
            }
        )

    @extend_schema(responses={200: dict})
    @action(detail=False, methods=["get"])
    def types(self, request: Request) -> Response:
        return Response(dict(TYPES_USAGER))


class VueContacts(VuePerimetre):
    queryset = Contact.objects.filter(anonymise_le__isnull=True).prefetch_related("rattachements__usager")
    serializer_class = ContactSerializer
    actions_requises = LECTURE_ECRITURE
    filterset_fields = ["courriel"]
    http_method_names = ["get", "post", "patch", "head", "options"]


class VueRattachements(VuePerimetre):
    queryset = Rattachement.objects.select_related("usager", "contact")
    serializer_class = RattachementSerializer
    actions_requises = LECTURE_ECRITURE
    filterset_fields = ["usager", "contact"]


class VueTypesPieces(VuePerimetre):
    queryset = TypePiece.objects.all()
    serializer_class = TypePieceSerializer
    actions_requises = {"lecture": "lire_usager", "ecriture": "gerer_parametres"}
    pagination_class = None


class VuePieces(VuePerimetre):
    queryset = PieceJustificative.objects.select_related("usager", "type_piece", "fichier")
    serializer_class = PieceSerializer
    actions_requises = {
        **LECTURE_ECRITURE,
        "create": "gerer_usager",
        "verifier": "gerer_usager",
        "fichier": "lire_usager",
        "alertes": "lire_usager",
    }
    filterset_fields = ["usager", "type_piece", "statut"]
    http_method_names = ["get", "post", "head", "options"]
    parser_classes = [MultiPartParser]

    @extend_schema(request={"multipart/form-data": DepotPieceSerializer}, responses=PieceSerializer)
    def create(self, request: Request, *args: Any, **kwargs: Any) -> Response:
        donnees = DepotPieceSerializer(data=request.data)
        donnees.is_valid(raise_exception=True)
        televerse = donnees.validated_data["fichier"]
        if televerse.size > fichiers.TAILLE_MAX:
            raise ErreurValidation("Le fichier est trop volumineux.", code="fichier_trop_gros")
        piece = services.deposer_piece(
            donnees.validated_data["usager"],
            donnees.validated_data["type_piece"],
            televerse.name,
            televerse.read(),
            acteur=agent_courant(request),
            valide_jusqu_au=donnees.validated_data.get("valide_jusqu_au"),
        )
        return Response(PieceSerializer(piece).data, status=status.HTTP_201_CREATED)

    @extend_schema(request=VerificationPieceSerializer, responses=PieceSerializer)
    @action(detail=True, methods=["post"], parser_classes=[JSONParser])
    def verifier(self, request: Request, pk: str | None = None) -> Response:
        donnees = VerificationPieceSerializer(data=request.data)
        donnees.is_valid(raise_exception=True)
        piece = services.verifier_piece(self.get_object(), acteur=agent_courant(request), **donnees.validated_data)
        return Response(PieceSerializer(piece).data)

    @extend_schema(responses={(200, "application/octet-stream"): bytes})
    @action(detail=True, methods=["get"])
    def fichier(self, request: Request, pk: str | None = None) -> FileResponse:
        piece = self.get_object()
        journaliser("telecharger_piece", piece, apres={"fichier": piece.fichier_id}, acteur=agent_courant(request))
        return fichiers.reponse_telechargement(piece.fichier)

    @extend_schema(responses=PieceSerializer(many=True))
    @action(detail=False, methods=["get"])
    def alertes(self, request: Request) -> Response:
        """USR-03 : pièces expirées ou qui expirent dans le délai d'alerte."""
        return Response(PieceSerializer(services.alertes_expiration()[:500], many=True).data)
