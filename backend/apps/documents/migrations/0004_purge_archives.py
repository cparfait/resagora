"""ADR 0006 : au terme de la durée d'utilité administrative, la procédure de purge (et elle seule) peut effacer
le contexte de fusion et les signataires d'un document d'usager anonymisé. Elle s'annonce par le réglage de
session `equipements.purge_archives`, posé dans sa transaction ; la suppression reste interdite.

Un document annulé ne redevient pas valable."""

from django.db import migrations

FONCTION = """
CREATE OR REPLACE FUNCTION documents_proteger() RETURNS trigger AS $$
BEGIN
    IF TG_OP = 'DELETE' THEN
        RAISE EXCEPTION 'Document conservé (RG-13) : suppression interdite.' USING ERRCODE = 'restrict_violation';
    END IF;
    IF current_setting('equipements.purge_archives', true) = 'oui' THEN
        IF OLD.numero IS DISTINCT FROM NEW.numero OR OLD.fichier_id IS DISTINCT FROM NEW.fichier_id
           OR OLD.sha256 IS DISTINCT FROM NEW.sha256 OR OLD.statut IS DISTINCT FROM NEW.statut
           OR OLD.nature IS DISTINCT FROM NEW.nature OR OLD.dossier_id IS DISTINCT FROM NEW.dossier_id THEN
            RAISE EXCEPTION 'Purge des archives : seuls le contexte et les signataires sont effacés.' USING ERRCODE = 'restrict_violation';
        END IF;
        RETURN NEW;
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
    IF OLD.statut = 'annule' AND NEW.statut IS DISTINCT FROM OLD.statut THEN
        RAISE EXCEPTION 'Document annulé : il ne redevient pas valable (RG-13).' USING ERRCODE = 'restrict_violation';
    END IF;
    RETURN NEW;
END
$$ LANGUAGE plpgsql;
"""

RETOUR = """
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
"""


class Migration(migrations.Migration):
    dependencies = [("documents", "0003_immuabilite_rg13")]
    operations = [migrations.RunSQL(FONCTION, reverse_sql=RETOUR)]
