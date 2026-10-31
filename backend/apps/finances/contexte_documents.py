"""Contexte de fusion des devis, factures, acomptes et avoirs (DOC-02, DOC-03, TAR-12)."""

from __future__ import annotations

from typing import Any

from apps.documents.contexte import base, contexte_usager, date_longue, fournisseur
from apps.noyau.montants import euros
from apps.noyau.parametres import parametre

from .models import PieceComptable

UNITES = {"heure": "h", "demi_journee": "demi-journée(s)", "journee": "journée(s)", "forfait": ""}


def _quantite(ligne: Any) -> str:
    if ligne.unite == "heure":
        heures, minutes = divmod(ligne.quantite, 60)
        return f"{heures} h {minutes:02d}" if minutes else f"{heures} h"
    return f"{ligne.quantite} {UNITES.get(ligne.unite, '')}".strip()


@fournisseur(
    "devis",
    "facture",
    "avoir",
    variables=[
        "piece.numero",
        "piece.validite",
        "piece.echeance",
        "piece.facture_origine",
        "piece.motif",
        "lignes[].libelle",
        "lignes[].quantite",
        "lignes[].prix_unitaire",
        "lignes[].reduction",
        "lignes[].montant",
        "montants.total",
        "montants.reference",
        "montants.acompte_deduit",
        "montants.reste_du",
        "reglement.iban",
        "reglement.bic",
        "reglement.titulaire",
        "reglement.payfip",
        "usager.*",
        "dossier.numero",
    ],
)
def contexte_piece(piece: PieceComptable) -> dict[str, Any]:
    return {
        **base(),
        "dossier": {"numero": piece.dossier.numero, "objet": piece.dossier.objet},
        "usager": contexte_usager(piece.usager),
        "piece": {
            "numero": piece.numero or "",
            "nature": piece.get_nature_display(),
            "validite": date_longue(piece.validite),
            "echeance": date_longue(piece.echeance),
            "emise_le": date_longue(piece.emise_le),
            "facture_origine": piece.origine.numero if piece.nature == "avoir" and piece.origine else "",
            "motif": piece.motif,
            "reference_virement": piece.reference_virement,
        },
        "lignes": [
            {
                "libelle": ligne.libelle,
                "quantite": _quantite(ligne),
                "prix_unitaire": euros(ligne.prix_unitaire),
                "reduction": f"{ligne.taux_reduction / 100:.0f} %" if ligne.taux_reduction else "—",
                "montant": euros(ligne.montant_du),
                "montant_reference": euros(ligne.montant_reference),
                "fondement": ligne.fondement,
            }
            for ligne in piece.lignes.all()
        ],
        "montants": {
            "total": euros(piece.total_du),
            "reference": euros(piece.total_reference),
            "acompte_deduit": euros(piece.acompte_deduit),
            "reste_du": euros(piece.total_du - piece.acompte_deduit),
            "acompte": euros(piece.total_du),
        },
        "reglement": {
            "iban": parametre("comptable.iban"),
            "bic": parametre("comptable.bic"),
            "titulaire": parametre("comptable.titulaire"),
            "payfip": False,
        },
        "caution": {"montant": ""},
    }


@fournisseur(
    "contrat_location",
    variables=[
        "dossier.*",
        "usager.*",
        "reservations[]",
        "conditions[]",
        "montants.total",
        "montants.acompte",
        "caution.montant",
    ],
)
def contexte_location(dossier: Any) -> dict[str, Any]:
    """Contrat de location : contexte du dossier complété des montants du devis accepté et de la caution."""
    from apps.documents.contexte import contexte_dossier

    from .cautions import caution_exigee
    from .facturation import devis_accepte
    from .models import Caution

    contexte = contexte_dossier(dossier)
    devis = devis_accepte(dossier)
    acompte = PieceComptable.objects.filter(dossier=dossier, nature="acompte").exclude(statut="annulee").first()
    reservation = dossier.reservations.order_by("date_debut").first()
    caution = Caution.objects.filter(dossier=dossier).first()
    montant_caution = (
        caution.montant
        if caution
        else (caution_exigee(reservation.espace, dossier.usager, reservation.date_debut) if reservation else 0)
    )
    contexte["montants"] = {
        "total": euros(devis.total_du) if devis else "selon devis",
        "acompte": euros(acompte.total_du) if acompte else "selon devis",
    }
    contexte["caution"] = {"montant": euros(montant_caution) if montant_caution else "aucune"}
    return contexte
