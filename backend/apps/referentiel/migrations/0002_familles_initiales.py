from django.db import migrations

FAMILLES = [
    ("gymnase", "Gymnase", 1),
    ("salle-sport", "Salle de sport spécialisée", 2),
    ("dojo", "Dojo et salle d'arts martiaux", 3),
    ("terrain-exterieur", "Terrain extérieur", 4),
    ("piste-athletisme", "Piste d'athlétisme", 5),
    ("salle-reunion", "Salle de réunion", 6),
    ("salle-associative", "Salle associative", 7),
    ("salle-fetes", "Salle des fêtes", 8),
    ("salle-spectacle", "Salle de spectacle", 9),
]


def creer(apps, schema_editor):
    Famille = apps.get_model("referentiel", "FamilleEspace")
    for code, libelle, ordre in FAMILLES:
        Famille.objects.update_or_create(code=code, defaults={"libelle": libelle, "ordre": ordre})


def supprimer(apps, schema_editor):
    apps.get_model("referentiel", "FamilleEspace").objects.filter(code__in=[f[0] for f in FAMILLES], espaces__isnull=True).delete()


class Migration(migrations.Migration):
    dependencies = [("referentiel", "0001_initial")]
    operations = [migrations.RunPython(creer, supprimer)]
