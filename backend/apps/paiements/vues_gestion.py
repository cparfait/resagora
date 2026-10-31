"""Back-office : suivi des paiements en ligne (TAR-07) — tentatives, relecture chez PayFiP, clôture après contrôle,
remboursement des trop-perçus, rapprochement."""

from __future__ import annotations

from datetime import date
from typing import Any

from drf_spectacular.utils import extend_schema
from rest_framework import serializers
from rest_framework.decorators import action
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.routers import SimpleRouter

from apps.habilitations.authentification import agent_courant
from apps.habilitations.services import exiger, sites_autorises
from apps.noyau.api import VuePerimetre
from apps.noyau.exceptions import AccesRefuse, ErreurValidation

from . import services
from .models import TentativePaiement


class TentativeSerializer(serializers.ModelSerializer):
    facture = serializers.CharField(source="piece.numero", read_only=True)
    dossier = serializers.IntegerField(source="piece.dossier_id", read_only=True)
    usager_nom = serializers.CharField(source="piece.usager.nom", read_only=True)
    statut_libelle = serializers.CharField(source="get_statut_display", read_only=True)
    controle_libelle = serializers.CharField(source="get_controle_display", read_only=True)
    rembourse_le = serializers.SerializerMethodField()

    class Meta:
        model = TentativePaiement
        fields = [
            "id",
            "uuid",
            "piece",
            "facture",
            "dossier",
            "usager_nom",
            "mode",
            "refdet",
            "exer",
            "montant",
            "statut",
            "statut_libelle",
            "numauto",
            "paye_le",
            "encaissement",
            "trop_percu",
            "controle",
            "controle_libelle",
            "rembourse_le",
            "erreur",
            "motif_cloture",
            "cree_le",
            "verifiee_le",
            "notifications",
        ]
        read_only_fields = fields

    def get_rembourse_le(self, tentative: TentativePaiement) -> date | None:
        remboursement = getattr(tentative, "remboursement", None)
        return remboursement.date if remboursement else None


class RemboursementSerializer(serializers.Serializer):
    date = serializers.DateField()
    reference = serializers.CharField(max_length=100)
    par = serializers.ChoiceField(choices=["ville", "comptable"])


class VueTentatives(VuePerimetre):
    """Lecture seule : une tentative ne naît que du portail et ne change que par le résultat lu chez PayFiP, ou par la
    clôture motivée d'un agent après contrôle."""

    queryset = TentativePaiement.objects.select_related("piece__usager").prefetch_related("remboursement")
    serializer_class = TentativeSerializer
    chemin_site = "piece__dossier__reservations__espace__batiment__site"
    actions_requises = {
        "lecture": "lire_finances",
        "verifier": "encaisser",
        "clore": "encaisser",
        "rembourser": "encaisser",
        "rapprocher": "encaisser",
    }
    filterset_fields = {"statut": ["exact", "in"], "controle": ["exact", "in"], "piece": ["exact"], "cree_le": ["gte", "lt"]}
    http_method_names = ["get", "post", "head", "options"]

    def get_queryset(self) -> Any:
        return super().get_queryset().distinct()

    def create(self, request: Request, *args: Any, **kwargs: Any) -> Response:
        return Response({"code": "non_autorise", "message": "Un paiement en ligne se crée depuis le portail."}, status=405)

    def _ville_entiere(self, request: Request) -> None:
        if sites_autorises(agent_courant(request), "encaisser") is not None:
            raise AccesRefuse("Réservé à la régie « tous sites ».", code="hors_perimetre")

    @extend_schema(request=None, responses=TentativeSerializer)
    @action(detail=True, methods=["post"])
    def verifier(self, request: Request, pk: str | None = None) -> Response:
        """Demande au worker de relire le résultat auprès de PayFiP (notification perdue, usager au guichet)."""
        tentative = self.get_object()
        TentativePaiement.objects.filter(pk=tentative.pk).update(verifiee_le=None)
        tentative.refresh_from_db()
        services.demander_relecture(tentative, source=f"agent {agent_courant(request).pk}")
        return Response(TentativeSerializer(tentative).data)

    @extend_schema(
        request={"application/json": {"type": "object", "properties": {"motif": {"type": "string"}}}},
        responses=TentativeSerializer,
    )
    @action(detail=True, methods=["post"])
    def clore(self, request: Request, pk: str | None = None) -> Response:
        """Clôture d'une tentative à contrôler, après vérification auprès de la DGFiP (motif tracé)."""
        self._ville_entiere(request)
        motif = str(request.data.get("motif", "")) if hasattr(request.data, "get") else ""
        tentative = services.clore_apres_controle(self.get_object(), acteur=agent_courant(request), motif=motif)
        return Response(TentativeSerializer(tentative).data)

    @extend_schema(request=RemboursementSerializer, responses=TentativeSerializer)
    @action(detail=True, methods=["post"])
    def rembourser(self, request: Request, pk: str | None = None) -> Response:
        """Trace le remboursement d'un trop-perçu (par la régie ou par le comptable public)."""
        self._ville_entiere(request)
        donnees = RemboursementSerializer(data=request.data)
        if not donnees.is_valid():
            raise ErreurValidation(
                "Indiquez la date, la référence et qui a remboursé.", code="validation", details={"champs": donnees.errors}
            )
        tentative = services.enregistrer_remboursement(self.get_object(), acteur=agent_courant(request), **donnees.validated_data)
        return Response(TentativeSerializer(TentativePaiement.objects.get(pk=tentative.pk)).data)

    @extend_schema(request=None, responses={200: dict})
    @action(detail=False, methods=["post"])
    def rapprocher(self, request: Request) -> Response:
        """Rapprochement à la demande (il tourne aussi chaque heure) ; réservé à la régie « tous sites »."""
        exiger(agent_courant(request), "encaisser")
        self._ville_entiere(request)
        from . import tasks

        tasks.rapprocher.delay()
        return Response({"programme": True})


routeur = SimpleRouter(trailing_slash=False)
routeur.register("finances/paiements-en-ligne", VueTentatives, basename="paiements-en-ligne")
urlpatterns = routeur.urls
