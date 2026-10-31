"""SEC-07, RG-13 : le contenu d'un fichier stocké (chemin, empreinte, taille, type) ne change jamais.

Un document signé, une facture ou un scan désignent un fichier par sa clé ; sans cette protection, une
modification de `noyau_fichier` changerait le contenu servi sans toucher au document. La suppression d'un
fichier référencé est déjà refusée par les clés étrangères.
"""

from django.db import migrations

SQL = """
CREATE OR REPLACE FUNCTION noyau_proteger_fichier() RETURNS trigger AS $$
BEGIN
    IF OLD.chemin IS DISTINCT FROM NEW.chemin OR OLD.sha256 IS DISTINCT FROM NEW.sha256
       OR OLD.taille IS DISTINCT FROM NEW.taille OR OLD.type_mime IS DISTINCT FROM NEW.type_mime THEN
        RAISE EXCEPTION 'Fichier stocké non modifiable : enregistrer un nouveau fichier.' USING ERRCODE = 'restrict_violation';
    END IF;
    RETURN NEW;
END
$$ LANGUAGE plpgsql;

CREATE TRIGGER fichier_immuable BEFORE UPDATE ON noyau_fichier FOR EACH ROW EXECUTE FUNCTION noyau_proteger_fichier();
"""

RETOUR = """
DROP TRIGGER IF EXISTS fichier_immuable ON noyau_fichier;
DROP FUNCTION IF EXISTS noyau_proteger_fichier();
"""


class Migration(migrations.Migration):
    dependencies = [("noyau", "0003_compteur")]
    operations = [migrations.RunSQL(SQL, reverse_sql=RETOUR)]
