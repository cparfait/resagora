"""Consultation, export et vérification du journal d'audit (ADM-05, SEC-08).

Le journal couvre toute la Ville : sa lecture exige l'action `lire_audit` sur un périmètre « tous
sites ». Chaque export et chaque vérification sont eux-mêmes journalisés.
"""

from __future__ import annotations

import csv
from typing import Any

import django_filters
from django.http import StreamingHttpResponse
from drf_spectacular.utils import extend_schema
from rest_framework import serializers, viewsets
from rest_framework.decorators import action
from rest_framework.permissions import BasePermission
from rest_framework.request import Request
from rest_framework.response import Response

from apps.habilitations.models import Utilisateur
from apps.habilitations.services import sites_autorises

from .models import JournalAudit
from .services import journaliser, verifier_chaine


class JournalAuditSerializer(serializers.ModelSerializer):
    class Meta:
        model = JournalAudit
        fields = [
            "id",
            "horodatage",
            "acteur",
            "acteur_libelle",
            "canal",
            "action",
            "objet_type",
            "objet_id",
            "objet_libelle",
            "avant",
            "apres",
            "adresse_ip",
            "empreinte",
        ]


class FiltreJournal(django_filters.FilterSet):
    du = django_filters.DateFilter(field_name="horodatage", lookup_expr="date__gte")
    au = django_filters.DateFilter(field_name="horodatage", lookup_expr="date__lte")
    action = django_filters.CharFilter(lookup_expr="icontains")
    acteur_libelle = django_filters.CharFilter(lookup_expr="icontains")

    class Meta:
        model = JournalAudit
        fields = ["acteur", "objet_type", "objet_id", "canal"]


class VerificationSerializer(serializers.Serializer):
    entrees_verifiees = serializers.IntegerField()
    integre = serializers.BooleanField()
    anomalies = serializers.ListField(child=serializers.CharField())


class PerimetreVilleEntiere(BasePermission):
    message = "Le journal d'audit n'est consultable qu'avec un périmètre couvrant toute la Ville."

    def has_permission(self, request: Request, view: Any) -> bool:
        utilisateur = request.user
        return isinstance(utilisateur, Utilisateur) and sites_autorises(utilisateur, "lire_audit") is None


def cellule_sure(valeur: object) -> str:
    """Neutralise l'injection de formules dans les tableurs (=, +, -, @, tabulation, retour chariot)."""
    texte = "" if valeur is None else str(valeur)
    return "'" + texte if texte[:1] in ("=", "+", "-", "@", "\t", "\r") else texte


class _Tampon:
    def write(self, valeur: str) -> str:
        return valeur


class VueJournalAudit(viewsets.ReadOnlyModelViewSet):
    queryset = JournalAudit.objects.all()
    serializer_class = JournalAuditSerializer
    filterset_class = FiltreJournal
    actions_requises = {"lecture": "lire_audit"}

    def get_permissions(self) -> list[Any]:
        return [*super().get_permissions(), PerimetreVilleEntiere()]

    @extend_schema(responses=VerificationSerializer)
    @action(detail=False, methods=["get"])
    def verification(self, request: Request) -> Response:
        resultat = verifier_chaine()
        journaliser("verifier_journal_audit", objet_type="audit.journalaudit", apres={"integre": resultat.integre})
        return Response(
            {"entrees_verifiees": resultat.entrees_verifiees, "integre": resultat.integre, "anomalies": resultat.anomalies}
        )

    @extend_schema(responses={(200, "text/csv"): str})
    @action(detail=False, methods=["get"])
    def export(self, request: Request) -> StreamingHttpResponse:
        lignes = self.filter_queryset(self.get_queryset()).order_by("id")
        journaliser("exporter_journal_audit", objet_type="audit.journalaudit", apres={"filtres": dict(request.query_params)})
        ecrivain = csv.writer(_Tampon(), delimiter=";")
        entete = [
            "id",
            "horodatage",
            "acteur",
            "action",
            "objet_type",
            "objet_id",
            "objet",
            "avant",
            "apres",
            "adresse_ip",
            "empreinte",
        ]

        def flux() -> Any:
            yield "﻿" + ecrivain.writerow(entete)
            for e in lignes.iterator(chunk_size=2000):
                yield ecrivain.writerow(
                    [
                        cellule_sure(v)
                        for v in (
                            e.pk,
                            e.horodatage.isoformat(),
                            e.acteur_libelle,
                            e.action,
                            e.objet_type,
                            e.objet_id,
                            e.objet_libelle,
                            e.avant or "",
                            e.apres or "",
                            e.adresse_ip or "",
                            e.empreinte,
                        )
                    ]
                )

        reponse = StreamingHttpResponse(flux(), content_type="text/csv; charset=utf-8")
        reponse["Content-Disposition"] = 'attachment; filename="journal-audit.csv"'
        return reponse
