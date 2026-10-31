"""Catalogue des actions (verbes) contrôlées par rôle × périmètre (RG-14) et rôles initiaux (ADM-03).

Une action = un verbe métier. Les rôles regroupent des actions ; les périmètres limitent les sites.
Séparation des tâches (ADR 0005) : l'ordonnateur (émission, avoirs, titres) est distinct de la régie
(encaissement, réception et restitution des cautions) ; l'administrateur gère les droits sans
exercer d'acte financier ; le contrôle interne lit le journal d'audit.
"""

from __future__ import annotations

ACTIONS: dict[str, str] = {
    # Référentiel
    "lire_referentiel": "Consulter sites, bâtiments et espaces",
    "gerer_referentiel": "Créer et modifier sites, bâtiments, espaces, horaires et fermetures",
    # Usagers
    "lire_usager": "Consulter les usagers et leurs contacts",
    "gerer_usager": "Créer et modifier les usagers, contacts et pièces",
    "valider_compte_usager": "Valider les comptes créés sur le portail",
    "anonymiser_usager": "Anonymiser ou exporter les données d'un usager (RGPD)",
    # Réservations
    "lire_reservation": "Consulter le planning, les dossiers et les réservations",
    "creer_reservation": "Saisir des demandes et des options",
    "instruire_reservation": "Instruire les demandes",
    "valider_reservation": "Valider ou refuser les demandes",
    "confirmer_reservation": "Confirmer les réservations",
    "annuler_reservation": "Annuler des réservations",
    "cloturer_reservation": "Saisir le réalisé et clôturer",
    "gerer_campagne": "Ouvrir et instruire les campagnes de créneaux annuels",
    "arbitrer_campagne": "Arbitrer et attribuer les créneaux en commission",
    "deplacer_priorite": "Déplacer une réservation confirmée pour priorité municipale (avec motif)",
    # Documents, signature, communication
    "lire_document": "Consulter et télécharger les documents",
    "generer_document": "Générer des documents et avenants",
    "gerer_modele": "Gérer les modèles de documents et de messages",
    "envoyer_signature": "Envoyer en signature et gérer le circuit manuel",
    "lire_message": "Consulter les messages des dossiers",
    "envoyer_message": "Envoyer des messages et notifications",
    "notifier_groupe": "Envoyer des notifications groupées",
    # Finances
    "lire_finances": "Consulter tarifs, devis, factures et cautions",
    "gerer_tarifs": "Gérer les grilles tarifaires et barèmes",
    "emettre_facture": "Émettre devis et factures (ordonnateur)",
    "emettre_avoir": "Émettre des avoirs (ordonnateur)",
    "exporter_titres": "Exporter les titres de recettes vers Ciril (ordonnateur)",
    "encaisser": "Pointer les encaissements (régie)",
    "gerer_caution": "Enregistrer la réception et la restitution des cautions (régie)",
    "proposer_retenue": "Constater un dommage et proposer une retenue de caution",
    "valider_retenue": "Valider les retenues de caution au-delà du seuil",
    # Personnel et mobile
    "lire_personnel": "Consulter le planning du personnel",
    "planifier_personnel": "Planifier vacations, trames et remplacements",
    "gerer_agents": "Gérer les fiches agents, qualifications (SSIAP, PSC1) et absences",
    "forcer_regle": "Forcer une règle de temps de travail avec motif",
    "utiliser_mobile": "Utiliser l'application mobile des gardiens",
    "gerer_appareils": "Enrôler et révoquer les appareils mobiles",
    # Matériel
    "lire_materiel": "Consulter le matériel",
    "gerer_materiel": "Gérer le matériel, les mouvements et la maintenance",
    "signaler_panne_materiel": "Signaler une panne de matériel",
    # Pilotage
    "lire_valorisation": "Consulter la valorisation",
    "calculer_valorisation": "Calculer la valorisation et éditer les attestations",
    "cloturer_valorisation": "Clôturer un exercice de valorisation",
    "lire_statistiques": "Consulter les statistiques",
    "lire_tableau_direction": "Consulter le tableau de bord de la direction",
    # Administration
    "administrer": "Gérer les agents, rôles, périmètres et groupes AD",
    "gerer_parametres": "Modifier les paramètres fonctionnels et le calendrier",
    "lire_audit": "Consulter et exporter le journal d'audit",
}

#: Actions qui imposent la double authentification au rôle qui les porte (SEC-03).
ACTIONS_SENSIBLES = frozenset(
    {
        "administrer",
        "lire_audit",
        "encaisser",
        "gerer_caution",
        "emettre_avoir",
        "exporter_titres",
        "valider_retenue",
        "cloturer_valorisation",
        "gerer_parametres",
        "anonymiser_usager",
        "gerer_appareils",
    }
)

#: Couples d'actions qu'un même agent ne peut pas cumuler (séparation ordonnateur / comptable, ADR 0005).
# Actes financiers : jamais portés par un rôle d'administration (ADR 0005).
ACTIONS_FINANCIERES = frozenset(
    {"gerer_tarifs", "emettre_facture", "emettre_avoir", "exporter_titres", "encaisser", "gerer_caution", "valider_retenue"}
)

INCOMPATIBILITES: list[tuple[str, str]] = [
    ("encaisser", "emettre_facture"),
    ("encaisser", "emettre_avoir"),
    ("gerer_caution", "valider_retenue"),
    ("administrer", "encaisser"),
]

_LECTURE_METIER = [
    "lire_referentiel",
    "lire_usager",
    "lire_reservation",
    "lire_document",
    "lire_message",
    "lire_finances",
    "lire_personnel",
    "lire_materiel",
    "lire_valorisation",
    "lire_statistiques",
]

ROLES_INITIAUX: dict[str, dict[str, object]] = {
    "administrateur": {
        "libelle": "Administrateur fonctionnel",
        "actions": [
            *_LECTURE_METIER,
            "administrer",
            "gerer_parametres",
            "gerer_modele",
            "anonymiser_usager",
            "lire_audit",
            "gerer_referentiel",
        ],
        "double_authentification": True,
    },
    "gestionnaire": {
        "libelle": "Gestionnaire des équipements",
        "actions": [
            *_LECTURE_METIER,
            "gerer_referentiel",
            "gerer_usager",
            "valider_compte_usager",
            "creer_reservation",
            "instruire_reservation",
            "valider_reservation",
            "confirmer_reservation",
            "annuler_reservation",
            "cloturer_reservation",
            "gerer_campagne",
            "deplacer_priorite",
            "generer_document",
            "envoyer_signature",
            "envoyer_message",
            "notifier_groupe",
            "emettre_facture",
            "proposer_retenue",
            "gerer_materiel",
            "signaler_panne_materiel",
            "calculer_valorisation",
        ],
        "double_authentification": False,
    },
    "accueil": {
        "libelle": "Agent d'accueil",
        "actions": [
            "lire_referentiel",
            "lire_usager",
            "lire_reservation",
            "creer_reservation",
            "lire_document",
            "lire_message",
            "envoyer_message",
            "gerer_usager",
            "lire_materiel",
        ],
        "double_authentification": False,
    },
    "elu_commission": {
        "libelle": "Membre de la commission d'attribution",
        "actions": ["lire_referentiel", "lire_reservation", "arbitrer_campagne"],
        "double_authentification": False,
    },
    "regisseur": {
        "libelle": "Régisseur",
        "actions": [
            "lire_referentiel",
            "lire_usager",
            "lire_reservation",
            "lire_finances",
            "lire_document",
            "encaisser",
            "gerer_caution",
        ],
        "double_authentification": True,
    },
    "financier": {
        "libelle": "Service financier (ordonnateur)",
        "actions": [
            "lire_referentiel",
            "lire_usager",
            "lire_reservation",
            "lire_finances",
            "lire_document",
            "gerer_tarifs",
            "emettre_facture",
            "emettre_avoir",
            "exporter_titres",
            "valider_retenue",
            "lire_valorisation",
            "calculer_valorisation",
            "cloturer_valorisation",
            "lire_statistiques",
        ],
        "double_authentification": True,
    },
    "planificateur": {
        "libelle": "Planificateur du personnel",
        "actions": [
            "lire_referentiel",
            "lire_reservation",
            "lire_personnel",
            "planifier_personnel",
            "gerer_agents",
            "forcer_regle",
            "gerer_appareils",
            "lire_materiel",
            "signaler_panne_materiel",
        ],
        "double_authentification": True,
    },
    "gardien": {
        "libelle": "Gardien",
        "actions": ["utiliser_mobile", "lire_referentiel", "lire_materiel", "signaler_panne_materiel"],
        "double_authentification": False,
    },
    "technicien_materiel": {
        "libelle": "Technicien matériel",
        "actions": ["lire_referentiel", "lire_reservation", "lire_materiel", "signaler_panne_materiel", "gerer_materiel"],
        "double_authentification": False,
    },
    "direction": {
        "libelle": "Direction",
        "actions": [*_LECTURE_METIER, "lire_tableau_direction"],
        "double_authentification": False,
    },
    "controle_interne": {
        "libelle": "Contrôle interne",
        "actions": [*_LECTURE_METIER, "lire_audit"],
        "double_authentification": True,
    },
}
