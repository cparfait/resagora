"""VAL-01, VAL-08 (revues du lot 6) : paramètres de calcul figés par exercice ; un exercice clos ne change plus en
base — ni son année, ni ses méthodes, ni ses subventions en numéraire — et ne rouvre pas ; l'année d'un exercice ne
change jamais. `calcule_par` rejoint les colonnes protégées d'une valorisation figée ; aucune table ne se vide."""

from django.db import migrations, models

SQL = """
CREATE OR REPLACE FUNCTION valorisation_proteger_exercice() RETURNS trigger AS $$
BEGIN
    IF TG_OP = 'DELETE' THEN
        IF OLD.statut = 'cloture' THEN
            RAISE EXCEPTION 'Exercice clos (VAL-08) : suppression interdite.' USING ERRCODE = 'restrict_violation';
        END IF;
        RETURN OLD;
    END IF;
    IF NEW.annee IS DISTINCT FROM OLD.annee THEN
        RAISE EXCEPTION 'L''année d''un exercice ne change pas.' USING ERRCODE = 'restrict_violation';
    END IF;
    IF OLD.statut = 'cloture' AND (
        NEW.statut IS DISTINCT FROM OLD.statut OR NEW.cloture_le IS DISTINCT FROM OLD.cloture_le
        OR NEW.cloture_par_id IS DISTINCT FROM OLD.cloture_par_id
        OR NEW.cout_horaire_personnel_centimes IS DISTINCT FROM OLD.cout_horaire_personnel_centimes
        OR NEW.absences_non_signalees_valorisees IS DISTINCT FROM OLD.absences_non_signalees_valorisees) THEN
        RAISE EXCEPTION 'Exercice clos (VAL-08) : statut et paramètres de calcul figés.' USING ERRCODE = 'restrict_violation';
    END IF;
    RETURN NEW;
END
$$ LANGUAGE plpgsql;

CREATE TRIGGER valorisation_exercice_clos
    BEFORE UPDATE OR DELETE ON valorisation_exercice
    FOR EACH ROW EXECUTE FUNCTION valorisation_proteger_exercice();

CREATE OR REPLACE FUNCTION valorisation_proteger_rattache() RETURNS trigger AS $$
DECLARE
    clos boolean;
BEGIN
    IF TG_OP = 'UPDATE' AND NEW.exercice_id IS DISTINCT FROM OLD.exercice_id THEN
        RAISE EXCEPTION 'Une méthode ou une subvention ne change pas d''exercice.' USING ERRCODE = 'restrict_violation';
    END IF;
    SELECT e.statut = 'cloture' INTO clos FROM valorisation_exercice e WHERE e.id = COALESCE(NEW.exercice_id, OLD.exercice_id);
    IF clos THEN
        RAISE EXCEPTION 'Exercice clos (VAL-08) : méthodes et subventions figées.' USING ERRCODE = 'restrict_violation';
    END IF;
    RETURN COALESCE(NEW, OLD);
END
$$ LANGUAGE plpgsql;

CREATE TRIGGER valorisation_methode_exercice_clos
    BEFORE INSERT OR UPDATE OR DELETE ON valorisation_methodevalorisation
    FOR EACH ROW EXECUTE FUNCTION valorisation_proteger_rattache();
CREATE TRIGGER valorisation_subvention_exercice_clos
    BEFORE INSERT OR UPDATE OR DELETE ON valorisation_subventionnumeraire
    FOR EACH ROW EXECUTE FUNCTION valorisation_proteger_rattache();

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
        OR NEW.calcule_par IS DISTINCT FROM OLD.calcule_par OR NEW.motif_recalcul IS DISTINCT FROM OLD.motif_recalcul
        OR (NEW.actuelle AND NOT OLD.actuelle)
        OR (OLD.document_id IS NOT NULL AND NEW.document_id IS DISTINCT FROM OLD.document_id)
        OR (OLD.deposee_le IS NOT NULL AND NEW.deposee_le IS DISTINCT FROM OLD.deposee_le) THEN
        RAISE EXCEPTION 'Valorisation figée (VAL-08) : recalcul par la procédure tracée.' USING ERRCODE = 'restrict_violation';
    END IF;
    RETURN NEW;
END
$$ LANGUAGE plpgsql;

CREATE TRIGGER valorisation_sans_vidage BEFORE TRUNCATE ON valorisation_valorisation
    FOR EACH STATEMENT EXECUTE FUNCTION interdire_vidage();
CREATE TRIGGER valorisation_ligne_sans_vidage BEFORE TRUNCATE ON valorisation_lignevalorisation
    FOR EACH STATEMENT EXECUTE FUNCTION interdire_vidage();
CREATE TRIGGER valorisation_exercice_sans_vidage BEFORE TRUNCATE ON valorisation_exercice
    FOR EACH STATEMENT EXECUTE FUNCTION interdire_vidage();
CREATE TRIGGER valorisation_methode_sans_vidage BEFORE TRUNCATE ON valorisation_methodevalorisation
    FOR EACH STATEMENT EXECUTE FUNCTION interdire_vidage();
CREATE TRIGGER valorisation_subvention_sans_vidage BEFORE TRUNCATE ON valorisation_subventionnumeraire
    FOR EACH STATEMENT EXECUTE FUNCTION interdire_vidage();
"""

INVERSE = """
DROP TRIGGER IF EXISTS valorisation_subvention_sans_vidage ON valorisation_subventionnumeraire;
DROP TRIGGER IF EXISTS valorisation_methode_sans_vidage ON valorisation_methodevalorisation;
DROP TRIGGER IF EXISTS valorisation_exercice_sans_vidage ON valorisation_exercice;
DROP TRIGGER IF EXISTS valorisation_ligne_sans_vidage ON valorisation_lignevalorisation;
DROP TRIGGER IF EXISTS valorisation_sans_vidage ON valorisation_valorisation;
DROP TRIGGER IF EXISTS valorisation_subvention_exercice_clos ON valorisation_subventionnumeraire;
DROP TRIGGER IF EXISTS valorisation_methode_exercice_clos ON valorisation_methodevalorisation;
DROP FUNCTION IF EXISTS valorisation_proteger_rattache();
DROP TRIGGER IF EXISTS valorisation_exercice_clos ON valorisation_exercice;
DROP FUNCTION IF EXISTS valorisation_proteger_exercice();
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
"""


class Migration(migrations.Migration):
    dependencies = [("valorisation", "0002_valorisations_figees"), ("audit", "0005_immuabilite_renforcee")]
    operations = [
        migrations.AddField(
            model_name="exercice",
            name="cout_horaire_personnel_centimes",
            field=models.PositiveIntegerField(
                blank=True, null=True, help_text="Coût chargé d'une heure de personnel dédié (centimes)."
            ),
        ),
        migrations.AddField(
            model_name="exercice", name="absences_non_signalees_valorisees", field=models.BooleanField(blank=True, null=True)
        ),
        migrations.RunSQL(SQL, INVERSE),
    ]
