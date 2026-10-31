"""Portail : documents du dossier (POR-05, DOC-07), signature électronique (POR-10, SIG-01) ou dépôt du scan
signé (SIG-05), et réception des webhooks DocuSeal relayés par la façade (SIG-02)."""

from __future__ import annotations

from typing import Any

from django.http import FileResponse
from drf_spectacular.utils import extend_schema
from rest_framework import serializers, status
from rest_framework.parsers import JSONParser, MultiPartParser
from rest_framework.request import Request
from rest_framework.response import Response

from apps.audit.services import journaliser
from apps.documents import services as documents
from apps.documents.models import Document
from apps.noyau import fichiers
from apps.noyau.exceptions import ErreurValidation

from .authentification import Introuvable, contact_courant
from .securite import VueContact, VuePublique
from .vues_dossiers import dossier_autorise


def representation_document(document: Document, contact: Any) -> dict[str, Any]:
    circuit = document.circuits.filter(statut="envoye").first()
    attendu = circuit.signataires.exclude(statut="signe").order_by("ordre").first() if circuit is not None else None
    return {
        "id": document.pk,
        "numero": document.numero,
        "titre": document.titre,
        "nature": document.get_nature_display(),
        "statut": document.statut,
        "statut_libelle": document.get_statut_display(),
        "cree_le": document.cree_le,
        "signe_le": document.signe_le,
        "taille": document.fichier_courant.taille,  # type: ignore[attr-defined]
        "a_signer_en_ligne": bool(circuit and circuit.mode == "docuseal" and attendu and attendu.contact_id == contact.pk),
        "scan_attendu": document.statut in {"genere", "en_signature"} and document.modele.signature_requise,
        "echeance_signature": circuit.expire_le if circuit is not None else None,
    }


def _document(request: Request, pk: int, document: int) -> tuple[Any, Document]:
    contact = contact_courant(request)
    dossier = dossier_autorise(contact, pk)
    trouve = (
        Document.objects.select_related("modele")
        .filter(pk=document, dossier=dossier, visible_portail=True)
        .exclude(statut="annule")
        .first()
    )
    if trouve is None:
        raise Introuvable()
    return contact, trouve


class VueDocumentsDossier(VueContact):
    @extend_schema(responses={200: dict})
    def get(self, request: Request, pk: int) -> Response:
        contact = contact_courant(request)
        dossier = dossier_autorise(contact, pk)
        visibles = (
            Document.objects.select_related("modele").filter(dossier=dossier, visible_portail=True).exclude(statut="annule")
        )
        return Response([representation_document(d, contact) for d in visibles.order_by("-cree_le")])


class VueFichierDocument(VueContact):
    """DOC-07 : téléchargement contrôlé ; un autre usager obtient 404 (R2-27)."""

    @extend_schema(responses={(200, "application/pdf"): bytes})
    def get(self, request: Request, pk: int, document: int) -> FileResponse:
        contact, trouve = _document(request, pk, document)
        journaliser("telecharger_document_portail", trouve, acteur=contact)
        return fichiers.reponse_telechargement(trouve.fichier_signe or trouve.fichier)


class VueSignatureDocument(VueContact):
    """POR-10 : lien de signature du contact connecté, s'il est le signataire attendu."""

    @extend_schema(responses={200: dict})
    def get(self, request: Request, pk: int, document: int) -> Response:
        contact, trouve = _document(request, pk, document)
        lien = documents.lien_de_signature(trouve, contact)
        journaliser("ouvrir_signature_portail", trouve, acteur=contact)
        return Response({"lien": lien})


class ScanPortailSerializer(serializers.Serializer):
    fichier = serializers.FileField()


class VueScanSigne(VueContact):
    """SIG-05 : l'usager dépose le document imprimé, signé et numérisé (PDF)."""

    parser_classes = [MultiPartParser]
    throttle_scope = "televersement"

    @extend_schema(request={"multipart/form-data": ScanPortailSerializer}, responses={200: dict})
    def post(self, request: Request, pk: int, document: int) -> Response:
        contact, trouve = _document(request, pk, document)
        entree = ScanPortailSerializer(data=request.data)
        entree.is_valid(raise_exception=True)
        televerse = entree.validated_data["fichier"]
        if televerse.size is None or televerse.size > fichiers.TAILLE_MAX:
            raise ErreurValidation("Le fichier est trop volumineux.", code="fichier_trop_gros")
        if trouve.usager is None or not trouve.usager.rattachements.filter(contact=contact, peut_signer=True).exists():
            raise ErreurValidation(
                "Seul un contact habilité à signer pour la structure peut déposer le document signé.", code="non_signataire"
            )
        signe = documents.deposer_scan_signe(
            trouve,
            televerse.name or "scan.pdf",
            televerse.read(),
            acteur=contact,
            portail=True,
            controle_facade=request.headers.get("X-Fichier-Controle", ""),
            empreinte_facade=request.headers.get("X-Empreinte-Sha256", ""),
        )
        return Response(representation_document(signe, contact))


class VueWebhookDocuSeal(VuePublique):
    """SIG-02 : la façade a vérifié le secret ; l'API ne retient que l'identifiant et relit l'état chez DocuSeal."""

    throttle_scope = "public"
    parser_classes = [JSONParser]

    @extend_schema(request={"application/json": dict}, responses={202: dict})
    def post(self, request: Request) -> Response:
        circuit = documents.traiter_webhook(request.data if isinstance(request.data, dict) else {})
        return Response({"pris_en_compte": circuit is not None}, status=status.HTTP_202_ACCEPTED)
