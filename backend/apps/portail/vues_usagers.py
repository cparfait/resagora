"""Portail : structures représentées par le contact, contacts, pièces justificatives (POR-01, POR-06, SEC-07).

Un contact ne voit que les usagers auxquels il est rattaché ; seul le contact principal modifie la
structure et ajoute des contacts. Les fichiers arrivent de la quarantaine DMZ (taille, type réel,
ClamAV) ; l'API revérifie le type et l'empreinte, et relance l'analyse si l'empreinte diffère.
"""

from __future__ import annotations

from typing import Any

from django.db import transaction
from django.http import FileResponse
from django.utils import timezone
from drf_spectacular.utils import extend_schema
from rest_framework import serializers, status
from rest_framework.parsers import MultiPartParser
from rest_framework.request import Request
from rest_framework.response import Response

from apps.audit.services import instantane, journaliser
from apps.comptes.services import inviter_contact
from apps.noyau import fichiers
from apps.noyau.exceptions import AccesRefuse, ErreurValidation
from apps.usagers import agenda
from apps.usagers import services as services_usagers
from apps.usagers.models import Contact, PieceJustificative, Rattachement, TypePiece, Usager

from .authentification import Introuvable, contact_courant, rattachement, usager_autorise, usagers_du_contact
from .securite import VueContact

ROLES_CONTACT = ["president", "tresorier", "secretaire", "referent", "directeur", "responsable", "autre"]


def representation_usager(usager: Usager, contact: Contact) -> dict[str, Any]:
    lien = Rattachement.objects.filter(usager=usager, contact=contact).first()
    return {
        "id": usager.pk,
        "nom": usager.nom,
        "type": usager.type,
        "type_libelle": usager.get_type_display(),
        "statut": usager.statut,
        "statut_libelle": usager.get_statut_display(),
        "sigle": usager.sigle,
        "siret": usager.siret,
        "rna": usager.rna,
        "adresse": usager.adresse,
        "code_postal": usager.code_postal,
        "commune": usager.commune,
        "telephone": usager.telephone,
        "courriel": usager.courriel,
        "resident": usager.resident,
        "conventionne": usager.convention_active(),
        "mon_role": lien.get_role_display() if lien else "",
        "principal": bool(lien and lien.principal),
        "peut_signer": bool(lien and lien.peut_signer),
    }


class UsagerPortailSerializer(serializers.Serializer):
    sigle = serializers.CharField(max_length=40, required=False, allow_blank=True)
    adresse = serializers.CharField(max_length=250, required=False)
    code_postal = serializers.RegexField(r"^\d{5}$", required=False)
    commune = serializers.CharField(max_length=80, required=False)
    telephone = serializers.CharField(max_length=20, required=False, allow_blank=True)
    courriel = serializers.EmailField(max_length=254, required=False, allow_blank=True)


def _exiger_principal(contact: Contact, usager: Usager) -> Rattachement:
    lien = rattachement(contact, usager)
    if not lien.principal:
        raise AccesRefuse(
            "Seul le contact principal de la structure peut faire cette modification.", code="contact_non_principal"
        )
    return lien


class VueUsagersPortail(VueContact):
    @extend_schema(responses={200: dict})
    def get(self, request: Request) -> Response:
        contact = contact_courant(request)
        return Response([representation_usager(u, contact) for u in usagers_du_contact(contact).order_by("nom")])


class VueUsagerPortail(VueContact):
    @extend_schema(responses={200: dict})
    def get(self, request: Request, pk: int) -> Response:
        contact = contact_courant(request)
        return Response(representation_usager(usager_autorise(contact, pk), contact))

    @extend_schema(request=UsagerPortailSerializer, responses={200: dict})
    def patch(self, request: Request, pk: int) -> Response:
        contact = contact_courant(request)
        usager = usager_autorise(contact, pk)
        _exiger_principal(contact, usager)
        entree = UsagerPortailSerializer(data=request.data, partial=True)
        entree.is_valid(raise_exception=True)
        with transaction.atomic():
            avant = instantane(usager)
            for champ, valeur in entree.validated_data.items():
                setattr(usager, champ, valeur)
            usager.derniere_activite = timezone.now()
            usager.save()
            journaliser("modifier_usager_portail", usager, avant=avant, apres=instantane(usager), acteur=contact)
        return Response(representation_usager(usager, contact))


class NouveauContactSerializer(serializers.Serializer):
    civilite = serializers.ChoiceField(choices=["", "Madame", "Monsieur"], required=False, default="")
    prenom = serializers.CharField(max_length=100)
    nom = serializers.CharField(max_length=100)
    courriel = serializers.EmailField(max_length=254)
    telephone = serializers.CharField(max_length=20, required=False, allow_blank=True, default="")
    role = serializers.ChoiceField(choices=ROLES_CONTACT, default="referent")
    peut_signer = serializers.BooleanField(default=False)
    inviter = serializers.BooleanField(default=True)


class VueContactsUsager(VueContact):
    """Contacts d'une structure ; le contact principal en ajoute et peut les inviter sur le portail."""

    @extend_schema(responses={200: dict})
    def get(self, request: Request, pk: int) -> Response:
        """Le contact principal voit les coordonnées des autres contacts ; les autres, leur nom et leur rôle."""
        contact = contact_courant(request)
        usager = usager_autorise(contact, pk)
        principal = rattachement(contact, usager).principal
        liste = []
        for r in usager.rattachements.select_related("contact").exclude(contact__anonymise_le__isnull=False):
            fiche: dict[str, Any] = {
                "id": r.contact_id,
                "prenom": r.contact.prenom,
                "nom": r.contact.nom,
                "role": r.get_role_display(),
                "role_code": r.role,
                "principal": r.principal,
                "peut_signer": r.peut_signer,
            }
            if principal or r.contact_id == contact.pk:
                fiche |= {
                    "courriel": r.contact.courriel,
                    "telephone": r.contact.telephone,
                    "compte": getattr(getattr(r.contact, "compte", None), "statut", None),
                }
            liste.append(fiche)
        return Response(liste)

    @extend_schema(request=NouveauContactSerializer, responses={201: dict})
    def post(self, request: Request, pk: int) -> Response:
        contact = contact_courant(request)
        usager = usager_autorise(contact, pk, valide=True)
        _exiger_principal(contact, usager)
        entree = NouveauContactSerializer(data=request.data)
        entree.is_valid(raise_exception=True)
        d = entree.validated_data
        courriel = d["courriel"].strip().lower()
        with transaction.atomic():
            if usager.rattachements.filter(contact__courriel__iexact=courriel).exists():
                raise ErreurValidation("Ce contact est déjà rattaché à la structure.", code="contact_existant")
            nouveau = Contact.objects.create(
                civilite=d["civilite"], prenom=d["prenom"], nom=d["nom"], courriel=courriel, telephone=d["telephone"]
            )
            Rattachement.objects.create(usager=usager, contact=nouveau, role=d["role"], peut_signer=d["peut_signer"])
            journaliser("ajouter_contact_portail", nouveau, apres={"usager": usager.pk, "role": d["role"]}, acteur=contact)
            if d["inviter"]:
                # Réponse identique que l'adresse ait déjà un compte ou non (SEC-04).
                inviter_contact(nouveau, invite_par=contact, structure=usager)
        return Response({"id": nouveau.pk, "message": "Contact ajouté."}, status=status.HTTP_201_CREATED)


class ModificationContactSerializer(serializers.Serializer):
    role = serializers.ChoiceField(choices=ROLES_CONTACT, required=False)
    peut_signer = serializers.BooleanField(required=False)
    telephone = serializers.CharField(max_length=20, required=False, allow_blank=True)


class VueContactUsager(VueContact):
    """POR-01 : le contact principal modifie le rôle d'un contact ou le retire de la structure (pas lui-même)."""

    def _lien(self, request: Request, pk: int, contact_id: int) -> tuple[Contact, Usager, Rattachement]:
        contact = contact_courant(request)
        usager = usager_autorise(contact, pk, valide=True)
        _exiger_principal(contact, usager)
        lien = usager.rattachements.select_related("contact").filter(contact_id=contact_id).first()
        if lien is None:
            raise Introuvable()
        if lien.contact_id == contact.pk:
            raise AccesRefuse("Vous ne pouvez pas modifier votre propre rattachement.", code="soi_meme")
        return contact, usager, lien

    @extend_schema(request=ModificationContactSerializer, responses={200: dict})
    def patch(self, request: Request, pk: int, contact_id: int) -> Response:
        contact, _usager, lien = self._lien(request, pk, contact_id)
        entree = ModificationContactSerializer(data=request.data)
        entree.is_valid(raise_exception=True)
        d = entree.validated_data
        with transaction.atomic():
            avant = {"role": lien.role, "peut_signer": lien.peut_signer, "telephone": lien.contact.telephone}
            if "role" in d:
                lien.role = d["role"]
            if "peut_signer" in d:
                lien.peut_signer = d["peut_signer"]
            lien.save(update_fields=["role", "peut_signer"])
            if "telephone" in d:
                lien.contact.telephone = d["telephone"]
                lien.contact.save(update_fields=["telephone"])
            journaliser(
                "modifier_contact_portail",
                lien.contact,
                avant=avant,
                apres={"role": lien.role, "peut_signer": lien.peut_signer, "telephone": lien.contact.telephone},
                acteur=contact,
            )
        return Response({"id": lien.contact_id, "message": "Contact modifié."})

    @extend_schema(responses={204: None})
    def delete(self, request: Request, pk: int, contact_id: int) -> Response:
        contact, usager, lien = self._lien(request, pk, contact_id)
        if lien.principal:
            raise AccesRefuse("Le contact principal ne peut pas être retiré.", code="contact_principal")
        with transaction.atomic():
            journaliser("retirer_contact_portail", lien.contact, apres={"usager": usager.pk}, acteur=contact)
            agenda.revoquer_abonnements(usager=usager, contact=lien.contact, acteur=contact, motif="contact retiré")
            lien.delete()
        return Response(status=status.HTTP_204_NO_CONTENT)


def representation_piece(piece: PieceJustificative) -> dict[str, Any]:
    return {
        "id": piece.pk,
        "type_piece": piece.type_piece_id,
        "type_libelle": piece.type_piece.libelle,
        "nom_fichier": piece.fichier.nom_origine,
        "statut": piece.statut,
        "statut_libelle": piece.get_statut_display(),
        "motif_refus": piece.motif_refus,
        "valide_jusqu_au": piece.valide_jusqu_au,
        "depose_le": piece.depose_le,
    }


class DepotPortailSerializer(serializers.Serializer):
    type_piece = serializers.PrimaryKeyRelatedField(queryset=TypePiece.objects.all())
    fichier = serializers.FileField()
    valide_jusqu_au = serializers.DateField(required=False, allow_null=True)


def deposer_depuis_portail(request: Request, usager: Usager, contact: Contact) -> PieceJustificative:
    """SEC-07 : la façade a contrôlé et analysé le fichier ; son empreinte est revérifiée ici."""
    entree = DepotPortailSerializer(data=request.data)
    entree.is_valid(raise_exception=True)
    televerse = entree.validated_data["fichier"]
    if televerse.size is None or televerse.size > fichiers.TAILLE_MAX:
        raise ErreurValidation("Le fichier est trop volumineux.", code="fichier_trop_gros")
    piece = services_usagers.deposer_piece(
        usager,
        entree.validated_data["type_piece"],
        televerse.name or "document",
        televerse.read(),
        acteur=contact,
        portail=True,
        valide_jusqu_au=entree.validated_data.get("valide_jusqu_au"),
        controle_facade=request.headers.get("X-Fichier-Controle", ""),
        empreinte_facade=request.headers.get("X-Empreinte-Sha256", ""),
    )
    Usager.objects.filter(pk=usager.pk).update(derniere_activite=timezone.now())
    return piece


class VuePiecesUsager(VueContact):
    parser_classes = [MultiPartParser]

    def get_throttles(self) -> list[Any]:
        self.throttle_scope = "televersement" if self.request.method == "POST" else "public"
        return super().get_throttles()

    @extend_schema(responses={200: dict})
    def get(self, request: Request, pk: int) -> Response:
        usager = usager_autorise(contact_courant(request), pk)
        return Response([representation_piece(p) for p in usager.pieces.select_related("type_piece", "fichier")])

    @extend_schema(request={"multipart/form-data": DepotPortailSerializer}, responses={201: dict})
    def post(self, request: Request, pk: int) -> Response:
        contact = contact_courant(request)
        usager = usager_autorise(contact, pk)
        piece = deposer_depuis_portail(request, usager, contact)
        return Response(representation_piece(piece), status=status.HTTP_201_CREATED)


class VueFichierPiece(VueContact):
    @extend_schema(responses={(200, "application/octet-stream"): bytes})
    def get(self, request: Request, pk: int, piece: int) -> FileResponse:
        contact = contact_courant(request)
        usager = usager_autorise(contact, pk)
        trouvee = usager.pieces.select_related("fichier").filter(pk=piece).first()
        if trouvee is None:
            raise Introuvable()
        journaliser("telecharger_piece_portail", trouvee, acteur=contact)
        return fichiers.reponse_telechargement(trouvee.fichier)


class VuePiecesExigees(VueContact):
    """Pièces demandées pour une structure et leur état (POR-06, USR-03)."""

    @extend_schema(responses={200: dict})
    def get(self, request: Request) -> Response:
        contact = contact_courant(request)
        usager = usager_autorise(contact, request.query_params.get("usager", ""))
        jour = timezone.localdate()
        resultat = []
        for type_piece in services_usagers.pieces_exigees(usager):
            pieces = list(usager.pieces.filter(type_piece=type_piece).order_by("-depose_le"))
            valide = next((p for p in pieces if p.valide_le(jour)), None)
            en_attente = next((p for p in pieces if p.statut == "a_verifier"), None)
            if valide is not None:
                etat = "valide"
            elif en_attente is not None:
                etat = "a_verifier"
            elif pieces and pieces[0].statut == "refuse":
                etat = "refusee"
            elif pieces:
                etat = "expiree"
            else:
                etat = "manquante"
            resultat.append(
                {
                    "type_piece": type_piece.pk,
                    "libelle": type_piece.libelle,
                    "description": type_piece.description,
                    "obligatoire": type_piece.obligatoire,
                    "etat": etat,
                    "valide_jusqu_au": valide.valide_jusqu_au if valide else None,
                    "motif_refus": pieces[0].motif_refus if pieces and pieces[0].statut == "refuse" else "",
                }
            )
        return Response(resultat)
