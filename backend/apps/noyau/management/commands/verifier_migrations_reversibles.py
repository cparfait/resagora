"""CLAUDE.md règle 7 : toute migration est réversible. Applique tout, revient à zéro, réapplique,
sur une base de test dédiée (jamais sur la base de production)."""

from __future__ import annotations

from typing import Any

from django.apps import apps
from django.conf import settings
from django.core.management import call_command
from django.core.management.base import BaseCommand, CommandError
from django.db import connections
from django.test.utils import get_runner


class Command(BaseCommand):
    help = "Vérifie que toutes les migrations s'appliquent et se défont sans erreur (base de test temporaire)."

    def handle(self, *args: Any, **options: Any) -> None:
        if not settings.DATABASES["default"]["NAME"] or "prod" in str(settings.DATABASES["default"].get("NAME", "")):
            raise CommandError("Refus d'exécuter sur une base de production.")
        executeur = get_runner(settings)(interactive=False, verbosity=0)
        anciennes = executeur.setup_databases()
        try:
            applications = sorted(
                {c.label for c in apps.get_app_configs() if c.name.startswith("apps.")}, key=lambda a: a != "noyau"
            )
            for application in reversed(applications):
                call_command("migrate", application, "zero", verbosity=0, interactive=False)
                self.stdout.write(f"{application} : migrations défaites.")
            call_command("migrate", verbosity=0, interactive=False)
            self.stdout.write(self.style.SUCCESS("Toutes les migrations sont réversibles (aller, retour, aller)."))
        finally:
            for connexion in connections.all():
                connexion.close()
            executeur.teardown_databases(anciennes)
