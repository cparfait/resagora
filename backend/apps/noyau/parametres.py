"""Paramètres fonctionnels modifiables par l'administration et tracés au journal (ADM-02).

Chaque paramètre a une valeur par défaut documentée ici ; la valeur effective est en base
(table `noyau_parametre`) dès qu'un agent la modifie. Les règles de gestion lisent toujours
la valeur effective via `parametre(cle)`.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from django.core.cache import cache

CLE_CACHE = "parametres:v1"


@dataclass(frozen=True)
class DefinitionParametre:
    cle: str
    libelle: str
    defaut: Any
    groupe: str
    aide: str = ""


DEFINITIONS: list[DefinitionParametre] = [
    # Réservations
    DefinitionParametre("options.duree_jours", "Durée de validité d'une option (jours)", 7, "Réservations", "PLA-08"),
    DefinitionParametre(
        "options.relance_jours_avant", "Relance avant expiration d'une option (jours)", 2, "Réservations", "RG-07"
    ),
    DefinitionParametre("reservations.duree_max_minutes", "Durée maximale d'un créneau (minutes)", 24 * 60, "Réservations"),
    DefinitionParametre(
        "reservations.delai_min_demande_jours", "Délai minimal entre la demande et l'occupation (jours)", 7, "Réservations"
    ),
    DefinitionParametre(
        "reservations.horizon_max_jours", "Horizon maximal de réservation ponctuelle (jours)", 400, "Réservations"
    ),
    DefinitionParametre(
        "annulation.delai_tardif_heures",
        "En deçà, une annulation est tardive (heures avant le début)",
        72,
        "Réservations",
        "PLA-10, RG-08",
    ),
    DefinitionParametre(
        "annulation.bareme",
        "Barème des frais d'annulation (heures avant le début → taux en dix-millièmes)",
        [
            {"heures_avant": 168, "taux": 0},
            {"heures_avant": 72, "taux": 2500},
            {"heures_avant": 24, "taux": 5000},
            {"heures_avant": 0, "taux": 10000},
        ],
        "Finances",
        "TAR-08 : le premier palier dont le délai est atteint s'applique.",
    ),
    DefinitionParametre(
        "priorites.ordre",
        "Ordre de priorité des demandeurs (RG-03)",
        ["service_municipal", "scolaire_temps_scolaire", "association_conventionnee_locale", "association", "autre"],
        "Réservations",
        "Ville, puis scolaire en temps scolaire, puis associations conventionnées locales, "
        "autres associations, entreprises et particuliers.",
    ),
    DefinitionParametre(
        "temps_scolaire",
        "Temps scolaire (jours de la semaine 0 = lundi, heures)",
        {"jours": [0, 1, 3, 4], "debut": "08:20", "fin": "16:30", "mercredi_matin": True},
        "Réservations",
        "Utilisé pour la priorité scolaire (RG-03).",
    ),
    # Calendrier
    DefinitionParametre("calendrier.zone", "Zone de vacances scolaires", "Zone C", "Calendrier", "ADM-01"),
    DefinitionParametre("calendrier.academie", "Académie (calendrier scolaire)", "Versailles", "Calendrier"),
    # Usagers
    DefinitionParametre(
        "pieces.alerte_jours_avant_expiration", "Alerte avant expiration d'une pièce (jours)", 30, "Usagers", "USR-03"
    ),
    DefinitionParametre("usagers.commune_residence", "Commune de résidence (tarif résident)", "Châtillon", "Usagers"),
    DefinitionParametre("rgpd.conservation_mois_inactivite", "Anonymisation après inactivité (mois)", 36, "Usagers", "USR-06"),
    # Documents et signature
    DefinitionParametre("signature.expiration_jours", "Délai de signature électronique (jours)", 21, "Documents", "SIG-01"),
    DefinitionParametre(
        "signature.relance_jours_avant", "Relance avant expiration de la signature (jours)", 3, "Documents", "SIG-04"
    ),
    # Finances
    DefinitionParametre("factures.echeance_jours", "Échéance de paiement des factures (jours)", 30, "Finances", "TAR-10"),
    DefinitionParametre("acomptes.taux", "Taux d'acompte exigé pour les locations (dix-millièmes)", 3000, "Finances", "TAR-09"),
    DefinitionParametre(
        "caution.seuil_double_validation_centimes",
        "Retenue de caution nécessitant un second agent (centimes)",
        30000,
        "Finances",
        "CAU-05",
    ),
    DefinitionParametre(
        "caution.delai_restitution_jours", "Délai de restitution de la caution (jours)", 30, "Finances", "CAU-07"
    ),
    # Personnel
    DefinitionParametre("personnel.max_hebdo_minutes", "Durée hebdomadaire maximale (minutes)", 48 * 60, "Personnel", "PER-05"),
    DefinitionParametre(
        "personnel.moyenne_12_semaines_minutes", "Moyenne sur 12 semaines (minutes)", 44 * 60, "Personnel", "PER-05"
    ),
    DefinitionParametre(
        "personnel.max_quotidien_minutes", "Durée quotidienne maximale (minutes)", 10 * 60, "Personnel", "PER-05"
    ),
    DefinitionParametre(
        "personnel.amplitude_max_minutes", "Amplitude maximale de la journée (minutes)", 12 * 60, "Personnel", "PER-05"
    ),
    DefinitionParametre("personnel.repos_quotidien_minutes", "Repos quotidien minimal (minutes)", 11 * 60, "Personnel", "PER-05"),
    DefinitionParametre("personnel.repos_hebdo_minutes", "Repos hebdomadaire minimal (minutes)", 35 * 60, "Personnel", "PER-05"),
    DefinitionParametre(
        "personnel.pause_apres_minutes", "Pause obligatoire au-delà de (minutes de travail)", 6 * 60, "Personnel", "PER-05"
    ),
    DefinitionParametre("personnel.pause_minutes", "Durée de la pause (minutes)", 20, "Personnel", "PER-05"),
    DefinitionParametre("personnel.nuit", "Heures de nuit", {"debut": "21:00", "fin": "06:00"}, "Personnel", "PER-07"),
    # Mobile
    DefinitionParametre(
        "mobile.purge_jours", "Effacement des données locales sans synchronisation (jours)", 7, "Mobile", "MOB-08"
    ),
    DefinitionParametre("mobile.alerte_heures", "Alerte de fraîcheur des données (heures)", 24, "Mobile", "MOB-08"),
    DefinitionParametre("mobile.horizon_jours", "Horizon du paquet descendant (jours)", 14, "Mobile", "MOB-07"),
    # Valorisation
    DefinitionParametre(
        "valorisation.seuil_convention_centimes",
        "Seuil de convention obligatoire (centimes)",
        2_300_000,
        "Valorisation",
        "VAL-06",
    ),
    DefinitionParametre(
        "valorisation.seuil_compte_rendu_centimes",
        "Seuil du compte rendu financier (centimes)",
        15_300_000,
        "Valorisation",
        "VAL-06",
    ),
    DefinitionParametre(
        "valorisation.absences_non_signalees_valorisees", "Valoriser les absences non signalées", True, "Valorisation", "VAL-03"
    ),
    DefinitionParametre(
        "valorisation.date_depot_attestations", "Date limite de dépôt des attestations (JJ-MM)", "31-03", "Valorisation", "VAL-04"
    ),
]

PAR_CLE = {d.cle: d for d in DEFINITIONS}


def tous() -> dict[str, Any]:
    from .models import Parametre

    valeurs = cache.get(CLE_CACHE)
    if valeurs is None:
        valeurs = {d.cle: d.defaut for d in DEFINITIONS}
        valeurs.update(dict(Parametre.objects.values_list("cle", "valeur")))
        cache.set(CLE_CACHE, valeurs, 300)
    return valeurs


def parametre(cle: str) -> Any:
    if cle not in PAR_CLE:
        raise KeyError(f"Paramètre inconnu : {cle}")
    return tous()[cle]


def invalider() -> None:
    cache.delete(CLE_CACHE)
