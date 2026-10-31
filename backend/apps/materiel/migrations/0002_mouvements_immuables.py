"""MAT-03 : le journal des mouvements de stock est immuable en base ; une erreur se corrige par un mouvement inverse."""

from django.db import migrations

SQL = """
CREATE OR REPLACE FUNCTION materiel_proteger_mouvement() RETURNS trigger AS $$
BEGIN
    RAISE EXCEPTION 'Journal des mouvements de stock (MAT-03) : ni modification ni suppression, saisir un mouvement inverse.'
        USING ERRCODE = 'restrict_violation';
END
$$ LANGUAGE plpgsql;

CREATE TRIGGER materiel_mouvement_immuable
    BEFORE UPDATE OR DELETE ON materiel_mouvement
    FOR EACH ROW EXECUTE FUNCTION materiel_proteger_mouvement();
"""

INVERSE = """
DROP TRIGGER IF EXISTS materiel_mouvement_immuable ON materiel_mouvement;
DROP FUNCTION IF EXISTS materiel_proteger_mouvement();
"""


class Migration(migrations.Migration):
    dependencies = [("materiel", "0001_initial")]
    operations = [migrations.RunSQL(SQL, INVERSE)]
