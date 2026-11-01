from django.db import migrations

from apps.communication.modeles_initiaux import CORRECTIONS_ACCES


def creer(apps, schema_editor):
    Modele = apps.get_model("communication", "ModeleMessage")
    for code, (ancien, nouveau) in CORRECTIONS_ACCES.items():
        Modele.objects.filter(code=code, corps=ancien).update(corps=nouveau)


def supprimer(apps, schema_editor):
    Modele = apps.get_model("communication", "ModeleMessage")
    for code, (ancien, nouveau) in CORRECTIONS_ACCES.items():
        Modele.objects.filter(code=code, corps=nouveau).update(corps=ancien)


class Migration(migrations.Migration):
    dependencies = [("communication", "0014_modeles_lot7")]
    operations = [migrations.RunPython(creer, supprimer)]
