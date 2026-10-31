"""Consultation, export et vérification du journal d'audit (ADM-05, SEC-08)."""

from __future__ import annotations

import csv
from typing import Any

import django_filters
from django.http import StreamingHttpResponse
from drf_spectacular.utils import extend_schema
from rest_framework import serializers, viewsets
from rest_framework.decorators import action
from rest_framework.request import Request
from rest_framework.response import Response

from .models import JournalAudit
from .services import verifier_chaine


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


class _Tampon:
    def write(self, valeur: str) -> str:
        return valeur


class VueJournalAudit(viewsets.ReadOnlyModelViewSet):
    queryset = JournalAudit.objects.all()
    serializer_class = JournalAuditSerializer
    filterset_class = FiltreJournal
    actions_requises = {"lecture": "lire_audit"}

    @extend_schema(responses=VerificationSerializer)
    @action(detail=False, methods=["get"])
    def verification(self, request: Request) -> Response:
        resultat = verifier_chaine()
        return Response(
            {"entrees_verifiees": resultat.entrees_verifiees, "integre": resultat.integre, "anomalies": resultat.anomalies}
        )

    @extend_schema(responses={(200, "text/csv"): str})
    @action(detail=False, methods=["get"])
    def export(self, request: Request) -> StreamingHttpResponse:
        lignes = self.filter_queryset(self.get_queryset()).order_by("id")
        ecrivain = csv.writer(_Tampon(), delimiter=";")
        entete = ["id", "horodatage", "acteur", "action", "objet_type", "objet_id", "objet", "adresse_ip", "empreinte"]

        def flux() -> Any:
            yield "﻿" + ecrivain.writerow(entete)
            for e in lignes.iterator(chunk_size=2000):
                yield ecrivain.writerow(
                    [
                        e.pk,
                        e.horodatage.isoformat(),
                        e.acteur_libelle,
                        e.action,
                        e.objet_type,
                        e.objet_id,
                        e.objet_libelle,
                        e.adresse_ip or "",
                        e.empreinte,
                    ]
                )

        reponse = StreamingHttpResponse(flux(), content_type="text/csv; charset=utf-8")
        reponse["Content-Disposition"] = 'attachment; filename="journal-audit.csv"'
        return reponse
