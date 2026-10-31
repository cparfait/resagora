"""Contrôles avant mise en service (job de migration) : base, migrations, réglages de sécurité, secrets."""

from __future__ import annotations

from typing import Any

from django.conf import settings
from django.core.management import call_command
from django.core.management.base import BaseCommand, CommandError
from django.db import connection
from django.db.migrations.executor import MigrationExecutor


class Command(BaseCommand):
    help = "Vérifie que l'instance est prête : base joignable, migrations appliquées, réglages sûrs."

    def handle(self, *args: Any, **options: Any) -> None:
        erreurs: list[str] = []
        with connection.cursor() as curseur:
            curseur.execute("SELECT extname FROM pg_extension")
            extensions = {ligne[0] for ligne in curseur.fetchall()}
        if "btree_gist" not in extensions:
            erreurs.append("Extension PostgreSQL btree_gist absente (contrainte anti-chevauchement RG-01).")
        executeur = MigrationExecutor(connection)
        if executeur.migration_plan(executeur.loader.graph.leaf_nodes()):
            erreurs.append("Des migrations ne sont pas appliquées.")
        if settings.DEBUG:
            erreurs.append("DEBUG est actif.")
        if len(settings.SECRET_KEY) < 50:
            erreurs.append("Secret django_secret_key trop court.")
        if not settings.SESSION_COOKIE_SECURE or not settings.CSRF_COOKIE_SECURE:
            erreurs.append("Cookies non sécurisés.")
        call_command("check", "--deploy", "--fail-level", "ERROR")
        if erreurs:
            raise CommandError(" ; ".join(erreurs))
        self.stdout.write(self.style.SUCCESS("Instance prête."))
