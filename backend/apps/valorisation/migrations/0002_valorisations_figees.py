"""VAL-08 : une valorisation figée (exercice clos) ne change plus en base ; seuls s'écrivent, une fois, l'attestation
et sa date de dépôt, et l'indicateur « actuelle » ne fait que tomber (procédure de recalcul). Ses lignes sont
immuables ; aucune version figée ne se supprime."""

from django.db import migrations

SQL = """
CREATE OR REPLACE FUNCTION valorisation_proteger() RETURNS trigger AS $$
BEGIN
    IF TG_OP = 'DELETE' THEN
        IF OLD.figee THEN
            RAISE EXCEPTION 'Valorisation figée (VAL-08) : suppression interdite.' USING ERRCODE = 'restrict_violation';
        END IF;
        RETURN OLD;
    END IF;
    IF NOT OLD.figee THEN
        RETURN NEW;
    END IF;
    IF NEW.exercice_id IS DISTINCT FROM OLD.exercice_id OR NEW.usager_id IS DISTINCT FROM OLD.usager_id
        OR NEW.version IS DISTINCT FROM OLD.version OR NEW.figee IS DISTINCT FROM OLD.figee
        OR NEW.minutes IS DISTINCT FROM OLD.minutes OR NEW.montant_espaces IS DISTINCT FROM OLD.montant_espaces
        OR NEW.montant_materiel IS DISTINCT FROM OLD.montant_materiel OR NEW.montant_personnel IS DISTINCT FROM OLD.montant_personnel
        OR NEW.total IS DISTINCT FROM OLD.total OR NEW.calcule_le IS DISTINCT FROM OLD.calcule_le
        OR NEW.motif_recalcul IS DISTINCT FROM OLD.motif_recalcul
        OR (NEW.actuelle AND NOT OLD.actuelle)
        OR (OLD.document_id IS NOT NULL AND NEW.document_id IS DISTINCT FROM OLD.document_id)
        OR (OLD.deposee_le IS NOT NULL AND NEW.deposee_le IS DISTINCT FROM OLD.deposee_le) THEN
        RAISE EXCEPTION 'Valorisation figée (VAL-08) : recalcul par la procédure tracée.' USING ERRCODE = 'restrict_violation';
    END IF;
    RETURN NEW;
END
$$ LANGUAGE plpgsql;

CREATE TRIGGER valorisation_figee
    BEFORE UPDATE OR DELETE ON valorisation_valorisation
    FOR EACH ROW EXECUTE FUNCTION valorisation_proteger();

CREATE OR REPLACE FUNCTION valorisation_proteger_ligne() RETURNS trigger AS $$
DECLARE
    figee boolean;
BEGIN
    SELECT v.figee INTO figee FROM valorisation_valorisation v WHERE v.id = COALESCE(NEW.valorisation_id, OLD.valorisation_id);
    IF figee THEN
        RAISE EXCEPTION 'Valorisation figée (VAL-08) : lignes immuables.' USING ERRCODE = 'restrict_violation';
    END IF;
    RETURN COALESCE(NEW, OLD);
END
$$ LANGUAGE plpgsql;

CREATE TRIGGER valorisation_ligne_figee
    BEFORE INSERT OR UPDATE OR DELETE ON valorisation_lignevalorisation
    FOR EACH ROW EXECUTE FUNCTION valorisation_proteger_ligne();
"""

INVERSE = """
DROP TRIGGER IF EXISTS valorisation_ligne_figee ON valorisation_lignevalorisation;
DROP FUNCTION IF EXISTS valorisation_proteger_ligne();
DROP TRIGGER IF EXISTS valorisation_figee ON valorisation_valorisation;
DROP FUNCTION IF EXISTS valorisation_proteger();
"""


class Migration(migrations.Migration):
    dependencies = [("valorisation", "0001_initial")]
    operations = [migrations.RunSQL(SQL, INVERSE)]
