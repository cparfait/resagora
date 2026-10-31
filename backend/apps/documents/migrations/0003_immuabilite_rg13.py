"""RG-13 : un document généré garde son contenu ; signé, il ne change plus ; il n'est jamais supprimé.

Les versions de modèles sont en ajout seul. Le contrôle est fait par la base, quel que soit le code qui écrit.
"""

from django.db import migrations

SQL = """
CREATE OR REPLACE FUNCTION documents_proteger() RETURNS trigger AS $$
BEGIN
    IF TG_OP = 'DELETE' THEN
        RAISE EXCEPTION 'Document conservé (RG-13) : suppression interdite.' USING ERRCODE = 'restrict_violation';
    END IF;
    IF OLD.numero IS DISTINCT FROM NEW.numero OR OLD.fichier_id IS DISTINCT FROM NEW.fichier_id
       OR OLD.sha256 IS DISTINCT FROM NEW.sha256 OR OLD.contexte IS DISTINCT FROM NEW.contexte
       OR OLD.version_id IS DISTINCT FROM NEW.version_id OR OLD.modele_id IS DISTINCT FROM NEW.modele_id
       OR OLD.nature IS DISTINCT FROM NEW.nature OR OLD.dossier_id IS DISTINCT FROM NEW.dossier_id
       OR OLD.usager_id IS DISTINCT FROM NEW.usager_id OR OLD.parent_id IS DISTINCT FROM NEW.parent_id
       OR OLD.titre IS DISTINCT FROM NEW.titre THEN
        RAISE EXCEPTION 'Contenu d''un document généré non modifiable (RG-13) : produire un avenant ou un nouveau document.'
            USING ERRCODE = 'restrict_violation';
    END IF;
    IF OLD.statut IN ('signe', 'signe_manuellement') AND (
        NEW.statut IS DISTINCT FROM OLD.statut OR NEW.fichier_signe_id IS DISTINCT FROM OLD.fichier_signe_id
        OR NEW.preuve_id IS DISTINCT FROM OLD.preuve_id OR NEW.signe_le IS DISTINCT FROM OLD.signe_le
        OR NEW.signe_par IS DISTINCT FROM OLD.signe_par) THEN
        RAISE EXCEPTION 'Document signé immuable (RG-13) : produire un avenant.' USING ERRCODE = 'restrict_violation';
    END IF;
    RETURN NEW;
END
$$ LANGUAGE plpgsql;

CREATE TRIGGER document_immuable BEFORE UPDATE OR DELETE ON documents_document
    FOR EACH ROW EXECUTE FUNCTION documents_proteger();
CREATE TRIGGER document_sans_vidage BEFORE TRUNCATE ON documents_document
    FOR EACH STATEMENT EXECUTE FUNCTION interdire_vidage();
CREATE TRIGGER version_modele_immuable BEFORE UPDATE OR DELETE ON documents_versionmodele
    FOR EACH ROW EXECUTE FUNCTION interdire_modification();
CREATE TRIGGER version_modele_sans_vidage BEFORE TRUNCATE ON documents_versionmodele
    FOR EACH STATEMENT EXECUTE FUNCTION interdire_vidage();
"""

RETOUR = """
DROP TRIGGER IF EXISTS document_immuable ON documents_document;
DROP TRIGGER IF EXISTS document_sans_vidage ON documents_document;
DROP TRIGGER IF EXISTS version_modele_immuable ON documents_versionmodele;
DROP TRIGGER IF EXISTS version_modele_sans_vidage ON documents_versionmodele;
DROP FUNCTION IF EXISTS documents_proteger();
"""


class Migration(migrations.Migration):
    dependencies = [("documents", "0002_modeles_initiaux"), ("audit", "0005_immuabilite_renforcee")]
    operations = [migrations.RunSQL(SQL, reverse_sql=RETOUR)]
