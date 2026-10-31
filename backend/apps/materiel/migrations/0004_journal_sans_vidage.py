"""MAT-03 (revue sécurité du lot 5, m6) : le journal des mouvements ne se vide pas non plus (TRUNCATE)."""

from django.db import migrations

SQL = """
CREATE TRIGGER materiel_mouvement_sans_vidage
    BEFORE TRUNCATE ON materiel_mouvement
    FOR EACH STATEMENT EXECUTE FUNCTION interdire_vidage();
"""

INVERSE = "DROP TRIGGER IF EXISTS materiel_mouvement_sans_vidage ON materiel_mouvement;"


class Migration(migrations.Migration):
    dependencies = [("materiel", "0003_pret_par_seance"), ("audit", "0005_immuabilite_renforcee")]
    operations = [migrations.RunSQL(SQL, INVERSE)]
