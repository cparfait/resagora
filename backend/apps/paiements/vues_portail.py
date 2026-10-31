"""Portail : paiement d'une facture en ligne (POR-07), état d'une tentative et notification de PayFiP (TAR-07).

L'API du portail n'appelle jamais PayFiP (moindre privilège, ADR 0008) : elle enregistre la tentative et confie au
worker la création de l'opération et la lecture des résultats. L'adresse de retour ne prouve rien."""

from __future__ import annotations

from typing import Any
from uuid import UUID

from drf_spectacular.utils import extend_schema
from rest_framework import status
from rest_framework.parsers import FormParser, MultiPartParser
from rest_framework.request import Request
from rest_framework.response import Response

from apps.finances.models import PieceComptable
from apps.noyau.montants import euros
from apps.portail.authentification import Introuvable, contact_courant, usagers_du_contact
from apps.portail.securite import VueContact, VuePublique

from . import services
from .models import TentativePaiement

LIBELLES = {
    "creee": "Préparation du paiement auprès de la DGFiP…",
    "redirigee": "Paiement en cours de vérification auprès de la DGFiP.",
    "remplacee": "Ce paiement a été remplacé par un autre ; s'il a abouti, il est bien pris en compte.",
    "payee": "Paiement accepté : merci. La facture est réglée.",
    "refusee": "Paiement refusé par votre banque : aucune somme n'a été prélevée.",
    "abandonnee": "Paiement abandonné : aucune somme n'a été prélevée.",
    "expiree": "Le paiement n'a pas abouti. Si une somme a été prélevée, elle sera prise en compte : consultez vos factures.",
    "a_controler": "Votre paiement est en cours de vérification par le service financier de la Ville.",
    "erreur": "Le paiement en ligne n'a pas pu être préparé : vous pouvez réessayer plus tard ou régler par virement.",
}
TERMINES = {"payee", "refusee", "abandonnee", "erreur", "a_controler", "expiree", "remplacee"}


def representation(tentative: TentativePaiement) -> dict[str, Any]:
    redirection = tentative.statut == "redirigee" and tentative.id_op
    return {
        "uuid": str(tentative.uuid),
        "facture": tentative.piece.numero,
        "facture_id": tentative.piece_id,
        "montant": tentative.montant,
        "montant_texte": euros(tentative.montant),
        "statut": tentative.statut,
        "message": LIBELLES[tentative.statut],
        "termine": tentative.statut in TERMINES,
        "numero_autorisation": tentative.numauto if tentative.statut == "payee" else "",
        "url": services.ClientPayFiP.url_paiement(tentative.id_op or "") if redirection else "",
    }


class VuePayerEnLigne(VueContact):
    """POR-07 : la tentative est enregistrée ; le portail suit son état et redirige vers PayFiP quand l'opération est
    créée par le worker."""

    @extend_schema(request=None, responses={202: dict})
    def post(self, request: Request, pk: int) -> Response:
        contact = contact_courant(request)
        piece = PieceComptable.objects.filter(pk=pk, usager__in=usagers_du_contact(contact), numero__isnull=False).first()
        if piece is None:
            raise Introuvable()
        tentative = services.initier(piece, contact=contact)
        return Response(representation(tentative), status=status.HTTP_202_ACCEPTED)


class VueEtatPaiement(VueContact):
    """Retour du navigateur : l'état vient de la base ; une relecture chez PayFiP est demandée au worker (30 s au plus
    souvent). Jamais déduit de l'adresse de retour."""

    @extend_schema(responses={200: dict})
    def get(self, request: Request, uuid: UUID) -> Response:
        contact = contact_courant(request)
        tentative = (
            TentativePaiement.objects.select_related("piece")
            .filter(uuid=uuid, piece__usager__in=usagers_du_contact(contact))
            .first()
        )
        if tentative is None:
            raise Introuvable()
        services.demander_relecture(tentative, source="retour")
        return Response(representation(tentative))


class VueNotificationPayFiP(VuePublique):
    """TAR-07 : la façade a filtré l'adresse de PayFiP et transmis `ref` et `sig` ; l'API contrôle la signature, puis
    confie la relecture du résultat au worker. Réponse neutre dans tous les cas."""

    throttle_scope = "public"
    parser_classes = [FormParser, MultiPartParser]

    @extend_schema(
        request={"application/x-www-form-urlencoded": {"type": "object", "properties": {"idop": {"type": "string"}}}},
        responses={200: dict},
    )
    def post(self, request: Request) -> Response:
        donnees = request.data if hasattr(request.data, "get") else {}
        services.notification(
            str(request.query_params.get("ref", ""))[:40],
            str(request.query_params.get("sig", ""))[:64],
            str(donnees.get("idop", ""))[:64],
        )
        return Response({"recu": True})
