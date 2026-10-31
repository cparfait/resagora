"""Lots de titres de recettes pour Ciril (TAR-06) et report des numéros de titres (statut « titre émis »).

L'export et l'import concernent toute la comptabilité de la Ville : ils exigent un périmètre « tous sites » (RG-14).
Un lot rejeté par Ciril s'annule (motif tracé, fichier conservé) : ses pièces redeviennent à exporter.
"""

from __future__ import annotations

from datetime import date
from typing import Any

from django.db import transaction
from django.db.models import Q, QuerySet
from django.utils import timezone

from apps.audit.services import journaliser
from apps.habilitations.models import Utilisateur
from apps.habilitations.services import sites_autorises
from apps.noyau import fichiers
from apps.noyau.exceptions import AccesRefuse, ErreurMetier, ErreurValidation
from apps.noyau.numerotation import numero

from .ciril.export import produire
from .facturation import _controler
from .models import LotTitres, PieceComptable


def exiger_ville_entiere(acteur: Any, action: str) -> None:
    """RG-14 : l'export des titres et l'import des encaissements portent sur toutes les factures de la Ville."""
    _controler(acteur, action, None)
    if isinstance(acteur, Utilisateur) and sites_autorises(acteur, action) is not None:
        raise AccesRefuse("Cette opération exige un périmètre couvrant toute la Ville.", code="perimetre_ville_entiere")


def _dans_un_lot() -> Q:
    return Q(lots_titres__isnull=False, lots_titres__annule_le__isnull=True)


def a_titrer() -> QuerySet[PieceComptable]:
    """Factures et acomptes émis à titrer, et avoirs dont la facture d'origine est titrée ou part dans le même lot.

    Une facture entièrement annulée par avoir avant tout export ne part pas, ni son avoir."""
    exportees = PieceComptable.objects.filter(_dans_un_lot()).values("pk")
    factures = (
        PieceComptable.objects.filter(
            nature__in=["facture", "acompte"],
            statut__in=["a_titrer", "solde_partiel", "solde"],
            numero__isnull=False,
            titre_numero="",
        )
        .exclude(pk__in=exportees)
        .exclude(statut="solde", total_du__lte=0)
    )
    avoirs = (
        PieceComptable.objects.filter(nature="avoir", numero__isnull=False)
        .exclude(pk__in=exportees)
        .filter(Q(origine__in=exportees) | Q(origine__in=factures.values("pk")))
    )
    return (
        PieceComptable.objects.filter(Q(pk__in=factures.values("pk")) | Q(pk__in=avoirs.values("pk")))
        .select_related("usager", "dossier", "origine")
        .order_by("numero")
    )


@transaction.atomic
def exporter(pieces: list[PieceComptable], *, acteur: Any, format_export: str | None = None) -> LotTitres:
    exiger_ville_entiere(acteur, "exporter_titres")
    if not pieces:
        raise ErreurValidation("Aucune pièce à exporter.", code="lot_vide")
    verrouillees = list(PieceComptable.objects.select_for_update().filter(pk__in=[p.pk for p in pieces]).order_by("numero"))
    deja = [p.numero for p in verrouillees if p.lots_titres.filter(annule_le__isnull=True).exists()]
    if deja:
        raise ErreurMetier(
            f"Déjà exportées dans un lot : {', '.join(str(n) for n in deja)}. Rejouez ce lot plutôt que d'en créer un nouveau.",
            code="deja_exportee",
        )
    contenu, extension, type_mime = produire(verrouillees, format_export)
    reference = numero("LT", timezone.localdate().year)
    fichier = fichiers.enregistrer_genere(f"titres-{reference}.{extension}", contenu, type_mime, depose_par=str(acteur))
    lot = LotTitres.objects.create(
        numero=reference,
        format=extension,
        fichier=fichier,
        numeros=[p.numero for p in verrouillees],
        total_centimes=sum(p.montant_titre for p in verrouillees),
        cree_par=acteur if isinstance(acteur, Utilisateur) else None,
    )
    lot.pieces.set(verrouillees)
    journaliser(
        "exporter_titres", lot, apres={"pieces": lot.numeros, "format": extension, "sha256": fichier.sha256}, acteur=acteur
    )
    return lot


@transaction.atomic
def annuler_lot(lot: LotTitres, *, acteur: Any, motif: str) -> LotTitres:
    """Lot rejeté par Ciril (format, erreur de saisie) : il reste consultable, ses pièces sont à réexporter."""
    exiger_ville_entiere(acteur, "exporter_titres")
    lot = LotTitres.objects.select_for_update().get(pk=lot.pk)
    if lot.annule_le is not None:
        raise ErreurMetier("Ce lot est déjà annulé.", code="lot_annule")
    if len(motif.strip()) < 5:
        raise ErreurValidation("Indiquez le motif du rejet.", code="motif_requis")
    titrees = [p.numero for p in lot.pieces.exclude(titre_numero="")]
    if titrees:
        raise ErreurMetier(
            f"Des titres sont déjà émis pour ce lot ({', '.join(str(n) for n in titrees)}) : il ne s'annule plus.",
            code="lot_titre",
        )
    lot.annule_le, lot.motif_annulation = timezone.now(), motif.strip()[:300]
    lot.save(update_fields=["annule_le", "motif_annulation"])
    lot.pieces.clear()
    journaliser("annuler_lot_titres", lot, apres={"motif": lot.motif_annulation, "pieces": lot.numeros}, acteur=acteur)
    return lot


@transaction.atomic
def reporter_titre(piece: PieceComptable, *, acteur: Any, titre: str, jour: date | None = None) -> PieceComptable:
    """Le service financier reporte le numéro du titre saisi ou importé dans Ciril (une seule fois)."""
    piece = PieceComptable.objects.select_for_update().get(pk=piece.pk)
    _controler(acteur, "exporter_titres", piece.dossier)
    if piece.nature not in {"facture", "acompte", "avoir"} or not piece.numero:
        raise ErreurMetier("Seule une pièce émise reçoit un numéro de titre.", code="statut_facture")
    if piece.titre_numero:
        raise ErreurMetier(f"Le titre {piece.titre_numero} est déjà reporté sur cette pièce.", code="titre_deja_reporte")
    titre = titre.strip()[:40]
    if not titre:
        raise ErreurValidation("Indiquez le numéro de titre.", code="titre_requis")
    if PieceComptable.objects.filter(titre_numero=titre).exclude(pk=piece.pk).exists():
        raise ErreurMetier("Ce numéro de titre est déjà attribué à une autre pièce.", code="titre_existant")
    piece.titre_numero, piece.titre_le = titre, jour or timezone.localdate()
    if piece.statut == "a_titrer":
        piece.statut = "titre_emis"
    piece.save(update_fields=["titre_numero", "titre_le", "statut"])
    journaliser("reporter_titre", piece, apres={"titre": piece.titre_numero}, acteur=acteur)
    return piece
