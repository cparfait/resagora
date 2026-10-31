"""Exporte les schémas OpenAPI versionnés des canaux gestion et portail (clients TypeScript générés)."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from django.core.management import call_command
from django.core.management.base import BaseCommand
from django.test import override_settings


class Command(BaseCommand):
    help = "Écrit openapi-gestion.yaml et openapi-portail.yaml dans le dossier donné."

    def add_arguments(self, parser: Any) -> None:
        parser.add_argument("dossier")

    def handle(self, *args: Any, **options: Any) -> None:
        dossier = Path(options["dossier"])
        dossier.mkdir(parents=True, exist_ok=True)
        for canal, urlconf in (("gestion", "config.urls_gestion"), ("portail", "config.urls_portail")):
            with override_settings(ROOT_URLCONF=urlconf, CANAL=canal):
                call_command("spectacular", "--file", str(dossier / f"openapi-{canal}.yaml"), "--urlconf", urlconf, "--validate")
            self.stdout.write(f"Schéma {canal} écrit.")
