"""Données de référence (rôles, familles, types, pièces, modèles de messages) rejouables à volonté.

Les migrations de données les créent à l'installation ; cette fonction les recrée de façon idempotente
(base de test après vidage, réparation d'une base de recette) en réutilisant exactement ces migrations.
"""

from __future__ import annotations

import importlib

from django.apps import apps

MIGRATIONS_DE_REFERENCE = [
    ("apps.habilitations.migrations.0005_roles_separation_des_taches", "appliquer"),
    ("apps.referentiel.migrations.0002_familles_initiales", "creer"),
    ("apps.usagers.migrations.0002_types_pieces", "creer"),
    ("apps.reservations.migrations.0002_types_reservation", "creer"),
    ("apps.reservations.migrations.0004_types_ouverts_au_portail", "appliquer"),
    ("apps.communication.migrations.0002_modeles_initiaux", "creer"),
    ("apps.communication.migrations.0004_modeles_lot2", "creer"),
    ("apps.communication.migrations.0005_modeles_lot3", "creer"),
    ("apps.communication.migrations.0006_modeles_corrections_lot2", "creer"),
    ("apps.communication.migrations.0008_modeles_lot4", "creer"),
    ("apps.documents.migrations.0002_modeles_initiaux", "creer"),
    ("apps.personnel.migrations.0002_types_habilitation", "creer"),
]


def amorcer_donnees_de_reference() -> None:
    for module, fonction in MIGRATIONS_DE_REFERENCE:
        getattr(importlib.import_module(module), fonction)(apps, None)
