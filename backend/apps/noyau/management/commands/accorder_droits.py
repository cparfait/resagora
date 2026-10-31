"""Droits du rôle PostgreSQL applicatif (ADR 0005), à exécuter avec le rôle propriétaire après chaque migration.

Le rôle applicatif lit et écrit les tables métier, mais ne peut ni modifier, ni supprimer, ni vider les
tables immuables (journal d'audit, points de contrôle, ancrages et, aux lots suivants, documents
signés, factures émises et journaux de caution) ; il n'a aucun droit DDL.
"""

from __future__ import annotations

from typing import Any

from django.core.management.base import BaseCommand, CommandError
from django.db import connection

TABLES_AJOUT_SEUL = [
    "audit_journalaudit",
    "audit_pointcontrolejournal",
    "audit_ancragejournal",
]


def tables_immuables() -> list[str]:
    """Tables en ajout seul : celles du socle et celles déclarées par les modèles (`immuable = True`)."""
    from django.apps import apps

    noms = set(TABLES_AJOUT_SEUL)
    for modele in apps.get_models():
        if getattr(modele, "immuable", False):
            noms.add(modele._meta.db_table)
    return sorted(noms)


class Command(BaseCommand):
    help = "Accorde au rôle applicatif les droits minimaux (DML), sans UPDATE/DELETE/TRUNCATE sur les tables immuables."

    def add_arguments(self, parser: Any) -> None:
        parser.add_argument("role")

    def handle(self, *args: Any, **options: Any) -> None:
        role = options["role"]
        if not role.replace("_", "").isalnum():
            raise CommandError("Nom de rôle invalide.")
        with connection.cursor() as curseur:
            curseur.execute("SELECT 1 FROM pg_roles WHERE rolname = %s AND NOT rolsuper", [role])
            if curseur.fetchone() is None:
                raise CommandError(f"Rôle {role} introuvable ou superutilisateur.")
            curseur.execute(f'GRANT SELECT, INSERT, UPDATE, DELETE ON ALL TABLES IN SCHEMA public TO "{role}"')
            curseur.execute(f'GRANT USAGE, SELECT ON ALL SEQUENCES IN SCHEMA public TO "{role}"')
            curseur.execute(f'REVOKE TRUNCATE, REFERENCES, TRIGGER ON ALL TABLES IN SCHEMA public FROM "{role}"')
            for table in tables_immuables():
                curseur.execute("SELECT to_regclass(%s)", [table])
                if curseur.fetchone()[0] is not None:
                    curseur.execute(f'REVOKE UPDATE, DELETE, TRUNCATE ON "{table}" FROM "{role}"')
            curseur.execute(f'REVOKE CREATE ON SCHEMA public FROM "{role}"')
        self.stdout.write(
            self.style.SUCCESS(f"Droits accordés à {role} ; tables immuables en ajout seul : {', '.join(tables_immuables())}.")
        )
