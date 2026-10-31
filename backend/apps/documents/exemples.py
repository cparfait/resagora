"""Valeurs fictives propres à chaque nature, ajoutées au contexte d'essai d'une nouvelle version de modèle."""

from __future__ import annotations

from typing import Any

_LIGNES = [
    {
        "libelle": "Salle des fêtes — samedi 14 h à 23 h",
        "quantite": "9 h",
        "prix_unitaire": "45,00 €",
        "reduction": "0 %",
        "montant": "405,00 €",
    }
]

EXEMPLES_PAR_NATURE: dict[str, dict[str, Any]] = {
    "contrat_location": {"montants": {"total": "405,00 €", "acompte": "121,50 €"}, "caution": {"montant": "500,00 €"}},
    "devis": {
        "piece": {"numero": "DV2026-00000", "validite": "31 décembre 2026"},
        "lignes": _LIGNES,
        "montants": {"total": "405,00 €"},
    },
    "facture": {
        "piece": {"numero": "F2026-00000", "echeance": "30 novembre 2026"},
        "lignes": _LIGNES,
        "montants": {"total": "405,00 €"},
        "reglement": {"iban": "FR76 0000 0000 0000 0000 0000 000", "payfip": False},
    },
    "avoir": {
        "piece": {"numero": "AV2026-00000", "facture_origine": "F2026-00000", "motif": "Séance annulée par la Ville"},
        "lignes": _LIGNES,
        "montants": {"total": "-405,00 €"},
    },
    "attestation_valorisation": {
        "exercice": "2026",
        "lignes": [
            {
                "espace": "Gymnase exemple",
                "heures": "64 h",
                "tarif_reference": "30,00 €",
                "paye": "0,00 €",
                "valorisation": "1 920,00 €",
            }
        ],
        "total": "1 920,00 €",
        "methode": "heures réservées × tarif de référence non résident, déduction des sommes payées",
    },
    "etat_des_lieux": {
        "materiel": [{"libelle": "Tables", "entree": "20 en bon état", "sortie": "", "observations": ""}],
        "gardien": "Gardien exemple",
    },
}
