"""API de gestion des comptes du portail : validation par la Ville, suspension, invitation (POR-01)."""

from __future__ import annotations

from typing import Any

import django_filters
from django.db.models import QuerySet
from drf_spectacular.utils import extend_schema
from rest_framework import serializers
from rest_framework.decorators import action
from rest_framework.request import Request
from rest_framework.response import Response

from apps.habilitations.authentification import agent_courant
from apps.noyau.api import VuePerimetre
from apps.usagers.models import Contact, Usager

from . import services
from .models import CompteUsager


class CompteSerializer(serializers.ModelSerializer):
    contact_nom = serializers.CharField(source="contact.__str__", read_only=True)
    telephone = serializers.CharField(source="contact.telephone", read_only=True)
    structures = serializers.SerializerMethodField()

    class Meta:
        model = CompteUsager
        fields = [
            "id",
            "identifiant",
            "contact",
            "contact_nom",
            "telephone",
            "statut",
            "courriel_confirme_le",
            "valide_le",
            "motif_suspension",
            "totp_actif",
            "derniere_connexion",
            "cree_le",
            "structures",
        ]
        read_only_fields = fields

    def get_structures(self, compte: CompteUsager) -> list[dict[str, Any]]:
        return [
            {
                "id": r.usager_id,
                "nom": r.usager.nom,
                "type": r.usager.get_type_display(),
                "statut": r.usager.statut,
                "siret": r.usager.siret,
                "rna": r.usager.rna,
            }
            for r in compte.contact.rattachements.select_related("usager")
        ]


class FiltreComptes(django_filters.FilterSet):
    recherche = django_filters.CharFilter(method="filtrer")

    class Meta:
        model = CompteUsager
        fields = ["statut"]

    def filtrer(self, qs: QuerySet[CompteUsager], nom: str, valeur: str) -> QuerySet[CompteUsager]:
        valeur = valeur.strip()[:80]
        if not valeur:
            return qs
        return (
            qs.filter(identifiant__icontains=valeur)
            | qs.filter(contact__nom__unaccent__icontains=valeur)
            | qs.filter(contact__rattachements__usager__nom__unaccent__icontains=valeur)
        )


class ValidationSerializer(serializers.Serializer):
    usager_existant = serializers.PrimaryKeyRelatedField(
        queryset=Usager.objects.exclude(statut="anonymise"), required=False, allow_null=True
    )


class MotifSerializer(serializers.Serializer):
    motif = serializers.CharField(max_length=250)


class InvitationSerializer(serializers.Serializer):
    contact = serializers.PrimaryKeyRelatedField(queryset=Contact.objects.filter(anonymise_le__isnull=True))


class VueComptes(VuePerimetre):
    queryset = CompteUsager.objects.select_related("contact").order_by("-cree_le")
    serializer_class = CompteSerializer
    actions_requises = {
        "lecture": "lire_usager",
        "valider": "valider_compte_usager",
        "refuser": "valider_compte_usager",
        "suspendre": "valider_compte_usager",
        "reactiver": "valider_compte_usager",
        "inviter": "gerer_usager",
    }
    filterset_class = FiltreComptes
    http_method_names = ["get", "post", "head", "options"]

    def create(self, request: Request, *args: Any, **kwargs: Any) -> Response:
        return Response(
            {"code": "non_autorise", "message": "Les comptes se créent sur le portail ou par invitation."}, status=405
        )

    def _repondre(self, compte: CompteUsager) -> Response:
        return Response(CompteSerializer(CompteUsager.objects.select_related("contact").get(pk=compte.pk)).data)

    @extend_schema(request=ValidationSerializer, responses=CompteSerializer)
    @action(detail=True, methods=["post"])
    def valider(self, request: Request, pk: str | None = None) -> Response:
        entree = ValidationSerializer(data=request.data)
        entree.is_valid(raise_exception=True)
        compte = services.valider_compte(
            self.get_object(), acteur=agent_courant(request), usager_existant=entree.validated_data.get("usager_existant")
        )
        return self._repondre(compte)

    @extend_schema(request=MotifSerializer, responses=CompteSerializer)
    @action(detail=True, methods=["post"])
    def refuser(self, request: Request, pk: str | None = None) -> Response:
        entree = MotifSerializer(data=request.data)
        entree.is_valid(raise_exception=True)
        return self._repondre(
            services.refuser_compte(self.get_object(), acteur=agent_courant(request), motif=entree.validated_data["motif"])
        )

    @extend_schema(request=MotifSerializer, responses=CompteSerializer)
    @action(detail=True, methods=["post"])
    def suspendre(self, request: Request, pk: str | None = None) -> Response:
        entree = MotifSerializer(data=request.data)
        entree.is_valid(raise_exception=True)
        return self._repondre(
            services.suspendre_compte(self.get_object(), acteur=agent_courant(request), motif=entree.validated_data["motif"])
        )

    @extend_schema(request=None, responses=CompteSerializer)
    @action(detail=True, methods=["post"])
    def reactiver(self, request: Request, pk: str | None = None) -> Response:
        return self._repondre(services.reactiver_compte(self.get_object(), acteur=agent_courant(request)))

    @extend_schema(request=InvitationSerializer, responses=CompteSerializer)
    @action(detail=False, methods=["post"])
    def inviter(self, request: Request) -> Response:
        """Un agent invite un contact déjà connu au guichet à créer son compte (lien de 7 jours)."""
        entree = InvitationSerializer(data=request.data)
        entree.is_valid(raise_exception=True)
        return self._repondre(services.inviter_contact(entree.validated_data["contact"], invite_par=agent_courant(request)))
