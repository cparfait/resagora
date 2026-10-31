"""Paramètres fonctionnels modifiables par l'administration et tracés au journal (ADM-02).

Chaque paramètre a une valeur par défaut documentée ici ; la valeur effective est en base
(table `noyau_parametre`) dès qu'un agent la modifie. Les règles de gestion lisent toujours
la valeur effective via `parametre(cle)`.
"""

from __future__ import annotations

import re
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
    bornes: tuple[int, int] | None = None


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
    DefinitionParametre(
        "pieces.double_controle",
        "Double contrôle des pièces (l'agent qui dépose ne valide pas)",
        True,
        "Usagers",
        "RG-06 : une pièce déposée au guichet est validée par un autre agent.",
    ),
    DefinitionParametre("usagers.commune_residence", "Commune de résidence (tarif résident)", "Châtillon", "Usagers"),
    DefinitionParametre("rgpd.conservation_mois_inactivite", "Anonymisation après inactivité (mois)", 36, "Usagers", "USR-06"),
    DefinitionParametre(
        "rgpd.conservation_mois_dossiers_clos",
        "Conservation des dossiers clos avant anonymisation des contacts (mois)",
        60,
        "Usagers",
        "USR-06 : les pièces comptables restent conservées selon les règles de la comptabilité publique.",
    ),
    DefinitionParametre(
        "rgpd.conservation_mois_pieces_expirees", "Suppression des pièces justificatives expirées (mois)", 12, "Usagers", "USR-06"
    ),
    # Portail
    DefinitionParametre("portail.echecs_avant_verrou", "Échecs de connexion avant attente imposée", 5, "Portail", "SEC-04"),
    DefinitionParametre(
        "portail.verrou_minutes", "Attente imposée après les échecs (minutes, doublée à chaque récidive)", 1, "Portail", "SEC-04"
    ),
    DefinitionParametre("portail.verrou_max_minutes", "Attente maximale imposée (minutes)", 60, "Portail", "SEC-04"),
    DefinitionParametre("portail.jeton_heures", "Durée maximale d'une session du portail (heures)", 12, "Portail", "SEC-04"),
    DefinitionParametre(
        "portail.reinitialisation_minutes",
        "Validité du lien de réinitialisation du mot de passe (minutes)",
        30,
        "Portail",
        "SEC-04",
    ),
    DefinitionParametre(
        "portail.confirmation_heures",
        "Validité du lien de confirmation de l'adresse électronique (heures)",
        48,
        "Portail",
        "POR-01",
    ),
    DefinitionParametre(
        "portail.service_courriel",
        "Adresse du service des équipements (copie des nouveaux messages et comptes à valider)",
        "equipements@chatillon.test",
        "Portail",
        "COM-02",
    ),
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
HEURE = re.compile(r"^([01]\d|2[0-3]):[0-5]\d$")
BORNES_PAR_DEFAUT = (0, 10_000_000)
BORNES = {
    "options.duree_jours": (1, 90),
    "options.relance_jours_avant": (0, 30),
    "reservations.duree_max_minutes": (15, 7 * 24 * 60),
    "reservations.delai_min_demande_jours": (0, 120),
    "reservations.horizon_max_jours": (30, 1100),
    "annulation.delai_tardif_heures": (0, 24 * 60),
    "portail.echecs_avant_verrou": (3, 20),
    "portail.verrou_minutes": (1, 60),
    "portail.verrou_max_minutes": (1, 24 * 60),
    "portail.jeton_heures": (1, 24),
    "portail.reinitialisation_minutes": (5, 120),
    "portail.confirmation_heures": (1, 168),
    "acomptes.taux": (0, 10_000),
    "signature.expiration_jours": (1, 90),
    "signature.relance_jours_avant": (0, 30),
}


def _verifier_specifique(cle: str, valeur: Any) -> str | None:
    if cle == "priorites.ordre":
        attendu = set(PAR_CLE[cle].defaut)
        if sorted(valeur) != sorted(attendu) or len(valeur) != len(attendu):
            return "L'ordre doit reprendre une fois chacune des catégories : " + ", ".join(sorted(attendu)) + "."
    elif cle == "temps_scolaire":
        jours = valeur.get("jours")
        if not isinstance(jours, list) or not all(isinstance(j, int) and 0 <= j <= 6 for j in jours):
            return "« jours » : liste de jours 0 (lundi) à 6 (dimanche)."
        if (
            not all(isinstance(valeur.get(k), str) and HEURE.match(valeur[k]) for k in ("debut", "fin"))
            or valeur["fin"] <= valeur["debut"]
        ):
            return "« debut » et « fin » au format HH:MM, fin après début."
        if not isinstance(valeur.get("mercredi_matin"), bool):
            return "« mercredi_matin » : vrai ou faux."
    elif cle == "annulation.bareme":
        if not valeur or not all(
            isinstance(p, dict)
            and isinstance(p.get("heures_avant"), int)
            and p["heures_avant"] >= 0
            and isinstance(p.get("taux"), int)
            and 0 <= p["taux"] <= 10_000
            for p in valeur
        ):
            return "Paliers {heures_avant ≥ 0, taux de 0 à 10000} attendus."
        if not any(p["heures_avant"] == 0 for p in valeur):
            return "Le barème doit comporter un palier à 0 heure."
    elif cle == "personnel.nuit":
        if not all(isinstance(valeur.get(k), str) and HEURE.match(valeur[k]) for k in ("debut", "fin")):
            return "« debut » et « fin » au format HH:MM."
    elif cle == "valorisation.date_depot_attestations":
        if not re.fullmatch(r"(0[1-9]|[12]\d|3[01])-(0[1-9]|1[0-2])", valeur):
            return "Format JJ-MM attendu."
    elif isinstance(valeur, str) and not valeur.strip():
        return "Valeur obligatoire."
    return None


def valider_valeur(cle: str, valeur: Any) -> str | None:
    """Message d'erreur si la valeur ne convient pas au paramètre (type, bornes, structure), sinon None."""
    definition = PAR_CLE.get(cle)
    if definition is None:
        return "Paramètre inconnu."
    defaut = definition.defaut
    if isinstance(defaut, bool):
        if not isinstance(valeur, bool):
            return "Vrai ou faux attendu."
    elif isinstance(defaut, int):
        if not isinstance(valeur, int) or isinstance(valeur, bool):
            return "Nombre entier attendu."
        minimum, maximum = definition.bornes or BORNES.get(cle, BORNES_PAR_DEFAUT)
        if not minimum <= valeur <= maximum:
            return f"Valeur entre {minimum} et {maximum} attendue."
    elif not isinstance(valeur, type(defaut)):
        return f"Valeur du même type que la valeur par défaut ({type(defaut).__name__}) attendue."
    if isinstance(valeur, str) and len(valeur) > 250:
        return "Texte trop long (250 caractères au plus)."
    return _verifier_specifique(cle, valeur)


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
