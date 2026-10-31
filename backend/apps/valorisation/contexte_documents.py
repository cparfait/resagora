"""Contexte de fusion de l'attestation annuelle de valorisation (VAL-04, modèle « attestation_valorisation »)."""

from __future__ import annotations

from apps.documents.contexte import Contexte, base, contexte_usager, fournisseur
from apps.noyau.montants import euros

from .models import Valorisation
from .services import libelle_methode


@fournisseur(
    "attestation_valorisation",
    variables=[
        "exercice",
        "usager.*",
        "lignes[].espace",
        "lignes[].heures",
        "lignes[].tarif_reference",
        "lignes[].paye",
        "lignes[].valorisation",
        "total",
        "methode",
    ],
)
def contexte_attestation(valorisation: Valorisation) -> Contexte:
    """Une ligne par équipement (et une pour le matériel, une pour le personnel), totaux en euros."""
    regroupe: dict[str, dict[str, int]] = {}
    methodes: set[str] = set()
    for ligne in valorisation.lignes.select_related("espace"):
        if ligne.nature == "espace" and ligne.espace is not None:
            cle = ligne.espace.nom
        elif ligne.nature == "materiel":
            cle = "Prêt de matériel"
        else:
            cle = "Personnel dédié (gardiennage)"
        cumul = regroupe.setdefault(cle, {"minutes": 0, "reference": 0, "paye": 0, "valorise": 0})
        if ligne.nature != "materiel":
            cumul["minutes"] += ligne.quantite
        cumul["reference"] += ligne.montant_reference
        cumul["paye"] += ligne.montant_paye
        cumul["valorise"] += ligne.montant_valorise
        if ligne.nature == "espace":
            methodes.add(libelle_methode(ligne.methode))
    return {
        **base(),
        "exercice": valorisation.exercice.annee,
        "usager": contexte_usager(valorisation.usager),
        "lignes": [
            {
                "espace": nom,
                "heures": f"{c['minutes'] / 60:.1f}".replace(".", ",") if c["minutes"] else "—",
                "tarif_reference": euros(c["reference"]),
                "paye": euros(c["paye"]),
                "valorisation": euros(c["valorise"]),
            }
            for nom, c in sorted(regroupe.items())
        ],
        "total": euros(valorisation.total),
        "methode": ", ".join(sorted(methodes)) or libelle_methode("tarif_reference"),
    }
