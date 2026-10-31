"""SEC-08 / ADR 0005 : le rôle applicatif PostgreSQL ne peut ni modifier ni vider le journal d'audit."""

from __future__ import annotations

import pytest
from django.core.management import call_command
from django.db import DatabaseError, connection, transaction

from apps.audit.services import journaliser
from tests.fabriques import SiteFabrique

pytestmark = pytest.mark.django_db


def test_sec08_role_applicatif_en_ajout_seul_sur_le_journal():
    with connection.cursor() as curseur:
        curseur.execute("SELECT 1 FROM pg_roles WHERE rolname = 'equipements_app_test'")
        if curseur.fetchone() is None:
            curseur.execute("CREATE ROLE equipements_app_test NOLOGIN NOSUPERUSER")
    call_command("accorder_droits", "equipements_app_test")
    entree = journaliser("essai", SiteFabrique())
    with connection.cursor() as curseur:
        curseur.execute("SELECT has_table_privilege('equipements_app_test', 'audit_journalaudit', 'INSERT')")
        assert curseur.fetchone()[0] is True
        for privilege in ("UPDATE", "DELETE", "TRUNCATE"):
            curseur.execute("SELECT has_table_privilege('equipements_app_test', 'audit_journalaudit', %s)", [privilege])
            assert curseur.fetchone()[0] is False, privilege
        curseur.execute("SELECT has_table_privilege('equipements_app_test', 'referentiel_site', 'UPDATE')")
        assert curseur.fetchone()[0] is True
    with pytest.raises(DatabaseError), transaction.atomic(), connection.cursor() as curseur:
        curseur.execute("SET LOCAL ROLE equipements_app_test")
        curseur.execute("DELETE FROM audit_journalaudit WHERE id = %s", [entree.pk])
