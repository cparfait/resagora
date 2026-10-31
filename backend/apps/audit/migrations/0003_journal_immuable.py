"""Déclencheur PostgreSQL interdisant UPDATE et DELETE sur le journal d'audit (SEC-08, RG-13).

La fonction `interdire_modification()` est réutilisée par les autres tables immuables
(documents signés, factures émises, journaux de caution).
"""

from django.db import migrations

FONCTION = """
CREATE OR REPLACE FUNCTION interdire_modification() RETURNS trigger AS $$
BEGIN
    RAISE EXCEPTION 'Table immuable (%): % interdit. Corriger par avenant, avoir ou nouvelle entrée.', TG_TABLE_NAME, TG_OP
        USING ERRCODE = 'restrict_violation';
END
$$ LANGUAGE plpgsql;
"""

DECLENCHEUR = """
CREATE TRIGGER journal_audit_immuable
BEFORE UPDATE OR DELETE ON audit_journalaudit
FOR EACH ROW EXECUTE FUNCTION interdire_modification();
"""


class Migration(migrations.Migration):
    dependencies = [("audit", "0002_initial")]

    operations = [
        migrations.RunSQL(FONCTION, reverse_sql="DROP FUNCTION IF EXISTS interdire_modification() CASCADE;"),
        migrations.RunSQL(DECLENCHEUR, reverse_sql="DROP TRIGGER IF EXISTS journal_audit_immuable ON audit_journalaudit;"),
    ]
