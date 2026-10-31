from django.db import migrations

from apps.communication.modeles_initiaux import MODELES


def creer(apps, schema_editor):
    Modele = apps.get_model("communication", "ModeleMessage")
    for code, (libelle, sujet, corps) in MODELES.items():
        Modele.objects.get_or_create(code=code, defaults={"libelle": libelle, "sujet": sujet, "corps": corps})


def supprimer(apps, schema_editor):
    apps.get_model("communication", "ModeleMessage").objects.filter(code__in=list(MODELES), notifications__isnull=True).delete()


class Migration(migrations.Migration):
    dependencies = [("communication", "0001_initial")]
    operations = [migrations.RunPython(creer, supprimer)]
