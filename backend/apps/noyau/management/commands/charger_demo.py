"""Charge le jeu de démonstration anonyme (recette, formation, scénarios transverses du §9.3)."""

from __future__ import annotations

import os
from typing import Any

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction

from apps.noyau.demo import socle


class Command(BaseCommand):
    help = "Charge le jeu de démonstration (3 sites, 40 espaces, usagers fictifs, saison 2026-2027 et réservations)."

    def add_arguments(self, parser: Any) -> None:
        parser.add_argument("--graine", type=int, default=92320, help="Graine du générateur (jeu reproductible).")
        parser.add_argument(
            "--completer",
            action="store_true",
            help="Jeu déjà chargé : ajoute seulement les parties des lots suivants qui manquent (finances, personnel…).",
        )

    def handle(self, *args: Any, **options: Any) -> None:
        if getattr(settings, "ENVIRONNEMENT", os.environ.get("ENVIRONNEMENT", "")) == "prod":
            raise CommandError("Le jeu de démonstration ne se charge jamais en production (ENVIRONNEMENT=prod).")
        if socle.deja_charge():
            if not options["completer"]:
                raise CommandError("Le jeu de démonstration est déjà chargé (--completer ajoute les parties manquantes).")
            with transaction.atomic():
                resultat = socle.existant()
                for module in socle.EXTENSIONS:
                    resultat["bilan"].update(module(resultat))
            for cle, nombre in sorted(resultat["bilan"].items()):
                self.stdout.write(f"{cle} : {nombre}")
            self.stdout.write(self.style.SUCCESS("Jeu de démonstration complété."))
            return
        with transaction.atomic():
            resultat = socle.charger(options["graine"])
            for module in socle.EXTENSIONS:
                resultat["bilan"].update(module(resultat))
        for cle, nombre in sorted(resultat["bilan"].items()):
            self.stdout.write(f"{cle} : {nombre}")
        self.stdout.write(self.style.SUCCESS("Jeu de démonstration chargé."))
