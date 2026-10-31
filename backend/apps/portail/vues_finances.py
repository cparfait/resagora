"""Portail : simulation de tarif (TAR-11), devis à accepter (TAR-04), factures et avoirs avec les coordonnées de
règlement (TAR-12), cautions (CAU-02). Un contact ne voit que les pièces des structures qu'il représente."""

from __future__ import annotations

from typing import Any

from django.db.models import QuerySet
from django.http import FileResponse
from drf_spectacular.utils import extend_schema
from rest_framework import serializers
from rest_framework.request import Request
from rest_framework.response import Response

from apps.audit.services import journaliser
from apps.finances import facturation, tarification
from apps.finances.models import CATEGORIES, Caution, PieceComptable
from apps.noyau import fichiers
from apps.noyau.exceptions import AccesRefuse, ErreurMetier
from apps.noyau.montants import euros
from apps.noyau.parametres import parametre

from .authentification import Introuvable, contact_courant, usagers_du_contact
from .catalogue import espaces_publics
from .securite import VueContact, VuePublique
from .vues_dossiers import dossier_autorise

STATUTS_PUBLICS = {
    "emis": "À accepter",
    "accepte": "Accepté",
    "refuse": "Refusé",
    "expire": "Expiré",
    "a_titrer": "À régler",
    "titre_emis": "À régler",
    "solde_partiel": "Partiellement réglée",
    "solde": "Réglée",
    "en_recouvrement": "En recouvrement auprès du comptable public",
    "annulee": "Annulée par avoir",
}
STATUTS_CAUTION_PUBLICS = {
    "attendue": "À déposer",
    "recue": "Déposée",
    "restituable": "En cours de restitution",
    "retenue_a_valider": "Retenue en cours d'examen",
    "restituee": "Restituée",
    "retenue_partielle": "Retenue partielle",
    "retenue_totale": "Retenue totale",
    "encaissee": "Retenue encaissée",
}
CATEGORIES_PUBLIQUES = [c for c, _ in CATEGORIES if c not in {"service_municipal"}]


def _pieces(contact: Any) -> QuerySet[PieceComptable]:
    return (
        PieceComptable.objects.filter(usager__in=usagers_du_contact(contact), numero__isnull=False)
        .select_related("dossier", "origine", "document")
        .prefetch_related("lignes")
        .order_by("-emise_le", "-numero")
    )


def representation_piece(piece: PieceComptable) -> dict[str, Any]:
    reglement = piece.nature in {"facture", "acompte"} and piece.statut in {"a_titrer", "titre_emis", "solde_partiel"}
    return {
        "id": piece.pk,
        "numero": piece.numero,
        "nature": piece.nature,
        "nature_libelle": piece.get_nature_display(),
        "dossier": piece.dossier_id,
        "dossier_numero": piece.dossier.numero,
        "objet": piece.objet,
        "statut": piece.statut,
        "statut_libelle": STATUTS_PUBLICS.get(piece.statut, piece.get_statut_display()),
        "emise_le": piece.emise_le,
        "echeance": piece.echeance,
        "validite": piece.validite,
        "total_du": piece.total_du,
        "total_texte": euros(piece.total_du),
        "acompte_deduit": piece.acompte_deduit,
        "reste_du": piece.reste_du if piece.nature != "devis" else None,
        "reste_texte": euros(piece.reste_du) if piece.nature != "devis" else "",
        "facture_origine": piece.origine.numero if piece.nature == "avoir" and piece.origine else "",
        "lignes": [
            {
                "libelle": ligne.libelle,
                "montant_reference": ligne.montant_reference,
                "reduction": ligne.taux_reduction,
                "montant_du": ligne.montant_du,
            }
            for ligne in piece.lignes.all()
        ],
        "a_accepter": piece.nature == "devis" and piece.statut == "emis",
        "pdf": piece.document_id is not None,
        "reglement": {
            "titulaire": parametre("comptable.titulaire"),
            "iban": parametre("comptable.iban"),
            "bic": parametre("comptable.bic"),
            "reference": piece.reference_virement,
        }
        if reglement
        else None,
    }


class SimulationSerializer(serializers.Serializer):
    espace = serializers.IntegerField(min_value=1)
    date = serializers.DateField()
    heure_debut = serializers.TimeField()
    heure_fin = serializers.TimeField()
    categorie = serializers.ChoiceField(choices=CATEGORIES_PUBLIQUES)
    resident = serializers.BooleanField(default=True)


class VueSimulationTarif(VuePublique):
    """TAR-11 : estimation publique, sans réduction personnelle (une gratuité éventuelle figure sur le devis)."""

    throttle_scope = "public"

    @extend_schema(request=SimulationSerializer, responses={200: dict})
    def post(self, request: Request) -> Response:
        entree = SimulationSerializer(data=request.data)
        entree.is_valid(raise_exception=True)
        d = entree.validated_data
        espace = espaces_publics().filter(pk=d["espace"]).first()
        if espace is None:
            raise Introuvable()
        if d["heure_fin"] <= d["heure_debut"]:
            raise ErreurMetier("L'heure de fin doit suivre l'heure de début.", code="horaires_invalides")
        debut, fin = tarification._debut_fin(d["date"], d["heure_debut"], d["heure_fin"])
        try:
            resultat = tarification.simuler(
                espace=espace, debut=debut, fin=fin, categorie_usager=d["categorie"], resident=d["resident"]
            )
        except ErreurMetier as erreur:
            raise ErreurMetier(
                "Le tarif de cet équipement n'est pas encore publié pour cette date : contactez le service des équipements.",
                code="tarif_indisponible",
            ) from erreur
        return Response({"espace": espace.nom, **resultat})


class VuePiecesPortail(VueContact):
    @extend_schema(responses={200: dict})
    def get(self, request: Request) -> Response:
        contact = contact_courant(request)
        pieces = _pieces(contact)
        dossier = request.query_params.get("dossier")
        if dossier:
            pieces = pieces.filter(dossier_id=dossier_autorise(contact, dossier).pk)
        return Response([representation_piece(p) for p in pieces[:500]])


class VueFichierPiece(VueContact):
    @extend_schema(responses={(200, "application/pdf"): bytes})
    def get(self, request: Request, pk: int) -> FileResponse:
        contact = contact_courant(request)
        piece = _pieces(contact).filter(pk=pk).first()
        if piece is None or piece.document is None:
            raise Introuvable()
        journaliser("telecharger_piece_portail", piece, acteur=contact)
        return fichiers.reponse_telechargement(piece.document.fichier_courant)  # type: ignore[arg-type]


class VueAccepterDevis(VueContact):
    """TAR-04 : le devis est accepté en ligne par un contact habilité à engager la structure."""

    @extend_schema(request=None, responses={200: dict})
    def post(self, request: Request, pk: int, devis: int) -> Response:
        contact = contact_courant(request)
        dossier = dossier_autorise(contact, pk)
        piece = PieceComptable.objects.filter(pk=devis, dossier=dossier, nature="devis").first()
        if piece is None:
            raise Introuvable()
        if not dossier.usager.rattachements.filter(contact=contact, peut_signer=True).exists():
            raise AccesRefuse("Seul un contact habilité à signer peut accepter le devis.", code="non_signataire")
        accepte = facturation.accepter_devis(piece, acteur=contact, portail=True)
        return Response(representation_piece(accepte))


class VueCautionsPortail(VueContact):
    @extend_schema(responses={200: dict})
    def get(self, request: Request) -> Response:
        contact = contact_courant(request)
        cautions = (
            Caution.objects.filter(usager__in=usagers_du_contact(contact))
            .select_related("dossier", "reservation__espace")
            .order_by("-cree_le")
        )
        return Response(
            [
                {
                    "id": c.pk,
                    "dossier": c.dossier_id,
                    "dossier_numero": c.dossier.numero,
                    "espace": c.reservation.espace.nom,
                    "montant": c.montant,
                    "montant_texte": euros(c.montant),
                    "statut": c.statut,
                    "statut_libelle": STATUTS_CAUTION_PUBLICS.get(c.statut, c.get_statut_display()),
                    "montant_retenu": c.montant_retenu,
                    "motif_retenue": c.motif_retenue if c.statut in {"retenue_partielle", "retenue_totale", "encaissee"} else "",
                    "recue_le": c.recue_le,
                    "restituee_le": c.restituee_le,
                    "a_deposer_avant": c.reservation.date_debut if c.statut == "attendue" else None,
                }
                for c in cautions[:200]
            ]
        )
