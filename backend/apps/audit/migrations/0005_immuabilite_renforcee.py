"""Immuabilité renforcée du journal (SEC-08) :

- TRUNCATE interdit sur le journal, ses points de contrôle et ses ancrages ;
- DELETE autorisé seulement pendant une purge tracée (variable de session posée par `purger()`,
  exécutée par le rôle propriétaire ; le rôle applicatif n'a ni DELETE ni TRUNCATE, voir ADR 0005) ;
- points de contrôle et ancrages immuables.
La base de test pose `equipements.truncate_autorise` (conftest) pour vider les tables entre tests.
"""

from django.db import migrations

FONCTIONS = """
CREATE OR REPLACE FUNCTION interdire_modification_journal() RETURNS trigger AS $$
BEGIN
    IF TG_OP = 'DELETE' AND current_setting('equipements.purge_audit', true) = 'oui' THEN
        RETURN OLD;
    END IF;
    RAISE EXCEPTION 'Journal d''audit immuable (%): % interdit.', TG_TABLE_NAME, TG_OP USING ERRCODE = 'restrict_violation';
END
$$ LANGUAGE plpgsql;

CREATE OR REPLACE FUNCTION interdire_vidage() RETURNS trigger AS $$
BEGIN
    IF current_setting('equipements.truncate_autorise', true) = 'oui' THEN
        RETURN NULL;
    END IF;
    RAISE EXCEPTION 'Vidage interdit de la table %.', TG_TABLE_NAME USING ERRCODE = 'restrict_violation';
END
$$ LANGUAGE plpgsql;

DROP TRIGGER IF EXISTS journal_audit_immuable ON audit_journalaudit;
CREATE TRIGGER journal_audit_immuable BEFORE UPDATE OR DELETE ON audit_journalaudit
    FOR EACH ROW EXECUTE FUNCTION interdire_modification_journal();
CREATE TRIGGER journal_audit_sans_vidage BEFORE TRUNCATE ON audit_journalaudit
    FOR EACH STATEMENT EXECUTE FUNCTION interdire_vidage();
CREATE TRIGGER point_controle_immuable BEFORE UPDATE OR DELETE ON audit_pointcontrolejournal
    FOR EACH ROW EXECUTE FUNCTION interdire_modification();
CREATE TRIGGER point_controle_sans_vidage BEFORE TRUNCATE ON audit_pointcontrolejournal
    FOR EACH STATEMENT EXECUTE FUNCTION interdire_vidage();
CREATE TRIGGER ancrage_immuable BEFORE UPDATE OR DELETE ON audit_ancragejournal
    FOR EACH ROW EXECUTE FUNCTION interdire_modification();
CREATE TRIGGER ancrage_sans_vidage BEFORE TRUNCATE ON audit_ancragejournal
    FOR EACH STATEMENT EXECUTE FUNCTION interdire_vidage();
"""

RETOUR = """
DROP TRIGGER IF EXISTS journal_audit_sans_vidage ON audit_journalaudit;
DROP TRIGGER IF EXISTS point_controle_immuable ON audit_pointcontrolejournal;
DROP TRIGGER IF EXISTS point_controle_sans_vidage ON audit_pointcontrolejournal;
DROP TRIGGER IF EXISTS ancrage_immuable ON audit_ancragejournal;
DROP TRIGGER IF EXISTS ancrage_sans_vidage ON audit_ancragejournal;
DROP TRIGGER IF EXISTS journal_audit_immuable ON audit_journalaudit;
CREATE TRIGGER journal_audit_immuable BEFORE UPDATE OR DELETE ON audit_journalaudit
    FOR EACH ROW EXECUTE FUNCTION interdire_modification();
DROP FUNCTION IF EXISTS interdire_modification_journal();
DROP FUNCTION IF EXISTS interdire_vidage();
"""


class Migration(migrations.Migration):
    dependencies = [("audit", "0004_points_controle_et_ancrages")]
    operations = [migrations.RunSQL(FONCTIONS, reverse_sql=RETOUR)]
