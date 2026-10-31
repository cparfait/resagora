"""Archivage puis purge des entrées du journal d'audit plus anciennes que la durée de conservation (SEC-08).

À exécuter avec le rôle propriétaire de la base (job de maintenance), jamais par l'application :
`docker compose run --rm migrations python manage.py purger_journal_audit --avant 2026-01-01`.
"""

from __future__ import annotations

from datetime import datetime, time, timedelta
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError
from django.utils import timezone

from apps.audit.services import purger


class Command(BaseCommand):
    help = "Archive (JSON Lines + empreinte) puis purge le journal avant la date donnée, conservation minimale 6 mois."

    def add_arguments(self, parser: Any) -> None:
        parser.add_argument("--avant", help="Date AAAA-MM-JJ (par défaut : aujourd'hui moins la durée de conservation).")
        parser.add_argument("--archives", default=str(Path(settings.MEDIA_ROOT) / "archives-audit"))

    def handle(self, *args: Any, **options: Any) -> None:
        if options["avant"]:
            jour = datetime.strptime(options["avant"], "%Y-%m-%d").date()
            avant = datetime.combine(jour, time.min, tzinfo=ZoneInfo(settings.TIME_ZONE))
        else:
            avant = timezone.now() - timedelta(days=settings.AUDIT_CONSERVATION_JOURS)
        try:
            point = purger(avant, "commande purger_journal_audit", Path(options["archives"]))
        except ValueError as erreur:
            raise CommandError(str(erreur)) from erreur
        if point is None:
            self.stdout.write("Aucune entrée à purger.")
        else:
            self.stdout.write(self.style.SUCCESS(f"{point.nombre} entrées archivées dans {point.archive} puis purgées."))
