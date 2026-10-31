"""Lots de titres de recettes pour Ciril (TAR-06) et report des numéros de titres (statut « titre émis »)."""

from __future__ import annotations

from datetime import date
from typing import Any

from django.db import transaction
from django.db.models import Q, QuerySet
from django.utils import timezone

from apps.audit.services import journaliser
from apps.noyau import fichiers
from apps.noyau.exceptions import ErreurMetier, ErreurValidation
from apps.noyau.numerotation import numero

from .ciril.export import produire
from .facturation import _controler
from .models import LotTitres, PieceComptable


def a_titrer() -> QuerySet[PieceComptable]:
    """Factures, acomptes et avoirs émis qui n'ont encore figuré dans aucun lot."""
    return (
        PieceComptable.objects.filter(numero__isnull=False, titre_numero="", lots_titres__isnull=True)
        .filter(Q(nature__in=["facture", "acompte"], statut="a_titrer") | Q(nature="avoir"))
        .select_related("usager", "dossier", "origine")
        .order_by("numero")
    )


@transaction.atomic
def exporter(pieces: list[PieceComptable], *, acteur: Any, format_export: str | None = None) -> LotTitres:
    _controler(acteur, "exporter_titres", None)
    if not pieces:
        raise ErreurValidation("Aucune pièce à exporter.", code="lot_vide")
    deja = [p.numero for p in pieces if p.lots_titres.exists()]
    if deja:
        raise ErreurMetier(
            f"Déjà exportées dans un lot : {', '.join(str(n) for n in deja)}. Rejouez ce lot plutôt que d'en créer un nouveau.",
            code="deja_exportee",
        )
    contenu, extension, type_mime = produire(pieces, format_export)
    reference = numero("LT", timezone.localdate().year)
    fichier = fichiers.enregistrer_genere(f"titres-{reference}.{extension}", contenu, type_mime, depose_par=str(acteur))
    lot = LotTitres.objects.create(
        numero=reference,
        format=extension,
        fichier=fichier,
        total_centimes=sum(p.total_du - p.acompte_deduit for p in pieces),
        cree_par=acteur if hasattr(acteur, "habilitations") else None,
    )
    lot.pieces.set(pieces)
    journaliser(
        "exporter_titres",
        lot,
        apres={"pieces": [p.numero for p in pieces], "format": extension, "sha256": fichier.sha256},
        acteur=acteur,
    )
    return lot


@transaction.atomic
def reporter_titre(piece: PieceComptable, *, acteur: Any, titre: str, jour: date | None = None) -> PieceComptable:
    """Le service financier reporte le numéro du titre saisi ou importé dans Ciril."""
    piece = PieceComptable.objects.select_for_update().get(pk=piece.pk)
    _controler(acteur, "exporter_titres", None)
    if piece.nature not in {"facture", "acompte", "avoir"} or not piece.numero:
        raise ErreurMetier("Seule une pièce émise reçoit un numéro de titre.", code="statut_facture")
    if not titre.strip():
        raise ErreurValidation("Indiquez le numéro de titre.", code="titre_requis")
    if PieceComptable.objects.filter(titre_numero=titre.strip()).exclude(pk=piece.pk).exists():
        raise ErreurMetier("Ce numéro de titre est déjà attribué à une autre pièce.", code="titre_existant")
    piece.titre_numero, piece.titre_le = titre.strip()[:40], jour or timezone.localdate()
    if piece.statut == "a_titrer":
        piece.statut = "titre_emis"
    piece.save(update_fields=["titre_numero", "titre_le", "statut"])
    journaliser("reporter_titre", piece, apres={"titre": piece.titre_numero}, acteur=acteur)
    return piece
