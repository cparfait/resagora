"""RG-13 : une pièce comptable émise (numérotée) garde son contenu ; seuls sa situation de paiement, son titre
et son document évoluent. Lignes des pièces émises, encaissements et journal des cautions : ajout seul."""

from django.db import migrations

SQL = """
CREATE OR REPLACE FUNCTION finances_proteger_piece() RETURNS trigger AS $$
BEGIN
    IF TG_OP = 'DELETE' THEN
        IF OLD.numero IS NOT NULL THEN
            RAISE EXCEPTION 'Pièce comptable émise (RG-13) : suppression interdite.' USING ERRCODE = 'restrict_violation';
        END IF;
        RETURN OLD;
    END IF;
    IF OLD.numero IS NOT NULL AND (
        NEW.numero IS DISTINCT FROM OLD.numero OR NEW.nature IS DISTINCT FROM OLD.nature
        OR NEW.exercice IS DISTINCT FROM OLD.exercice OR NEW.dossier_id IS DISTINCT FROM OLD.dossier_id
        OR NEW.usager_id IS DISTINCT FROM OLD.usager_id OR NEW.origine_id IS DISTINCT FROM OLD.origine_id
        OR NEW.objet IS DISTINCT FROM OLD.objet OR NEW.emise_le IS DISTINCT FROM OLD.emise_le
        OR NEW.echeance IS DISTINCT FROM OLD.echeance OR NEW.validite IS DISTINCT FROM OLD.validite
        OR NEW.total_reference IS DISTINCT FROM OLD.total_reference OR NEW.total_du IS DISTINCT FROM OLD.total_du
        OR NEW.acompte_deduit IS DISTINCT FROM OLD.acompte_deduit OR NEW.motif IS DISTINCT FROM OLD.motif
        OR NEW.reference_virement IS DISTINCT FROM OLD.reference_virement) THEN
        RAISE EXCEPTION 'Pièce comptable émise (RG-13) : contenu non modifiable, émettre un avoir.' USING ERRCODE = 'restrict_violation';
    END IF;
    RETURN NEW;
END
$$ LANGUAGE plpgsql;

CREATE OR REPLACE FUNCTION finances_proteger_ligne() RETURNS trigger AS $$
DECLARE
    piece_emise boolean;
BEGIN
    SELECT numero IS NOT NULL INTO piece_emise FROM finances_piececomptable
        WHERE id = COALESCE(NEW.piece_id, OLD.piece_id);
    IF piece_emise THEN
        RAISE EXCEPTION 'Ligne d''une pièce émise (RG-13) : % interdit.', TG_OP USING ERRCODE = 'restrict_violation';
    END IF;
    RETURN COALESCE(NEW, OLD);
END
$$ LANGUAGE plpgsql;

CREATE TRIGGER piece_comptable_immuable BEFORE UPDATE OR DELETE ON finances_piececomptable
    FOR EACH ROW EXECUTE FUNCTION finances_proteger_piece();
CREATE TRIGGER ligne_comptable_immuable BEFORE INSERT OR UPDATE OR DELETE ON finances_lignecomptable
    FOR EACH ROW EXECUTE FUNCTION finances_proteger_ligne();
CREATE TRIGGER encaissement_immuable BEFORE UPDATE OR DELETE ON finances_encaissement
    FOR EACH ROW EXECUTE FUNCTION interdire_modification();
CREATE TRIGGER mouvement_caution_immuable BEFORE UPDATE OR DELETE ON finances_mouvementcaution
    FOR EACH ROW EXECUTE FUNCTION interdire_modification();
CREATE TRIGGER piece_sans_vidage BEFORE TRUNCATE ON finances_piececomptable FOR EACH STATEMENT EXECUTE FUNCTION interdire_vidage();
CREATE TRIGGER ligne_sans_vidage BEFORE TRUNCATE ON finances_lignecomptable FOR EACH STATEMENT EXECUTE FUNCTION interdire_vidage();
CREATE TRIGGER encaissement_sans_vidage BEFORE TRUNCATE ON finances_encaissement FOR EACH STATEMENT EXECUTE FUNCTION interdire_vidage();
CREATE TRIGGER mouvement_caution_sans_vidage BEFORE TRUNCATE ON finances_mouvementcaution FOR EACH STATEMENT EXECUTE FUNCTION interdire_vidage();
"""

RETOUR = """
DROP TRIGGER IF EXISTS piece_comptable_immuable ON finances_piececomptable;
DROP TRIGGER IF EXISTS ligne_comptable_immuable ON finances_lignecomptable;
DROP TRIGGER IF EXISTS encaissement_immuable ON finances_encaissement;
DROP TRIGGER IF EXISTS mouvement_caution_immuable ON finances_mouvementcaution;
DROP TRIGGER IF EXISTS piece_sans_vidage ON finances_piececomptable;
DROP TRIGGER IF EXISTS ligne_sans_vidage ON finances_lignecomptable;
DROP TRIGGER IF EXISTS encaissement_sans_vidage ON finances_encaissement;
DROP TRIGGER IF EXISTS mouvement_caution_sans_vidage ON finances_mouvementcaution;
DROP FUNCTION IF EXISTS finances_proteger_piece();
DROP FUNCTION IF EXISTS finances_proteger_ligne();
"""


class Migration(migrations.Migration):
    dependencies = [("finances", "0001_initial"), ("audit", "0005_immuabilite_renforcee")]
    operations = [migrations.RunSQL(SQL, reverse_sql=RETOUR)]
