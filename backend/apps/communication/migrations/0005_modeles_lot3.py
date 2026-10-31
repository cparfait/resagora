from django.db import migrations

from apps.communication.modeles_initiaux import MODELES_LOT3


def creer(apps, schema_editor):
    Modele = apps.get_model("communication", "ModeleMessage")
    for code, (libelle, sujet, corps, sms) in MODELES_LOT3.items():
        Modele.objects.get_or_create(code=code, defaults={"libelle": libelle, "sujet": sujet, "corps": corps, "sms": sms})


def supprimer(apps, schema_editor):
    apps.get_model("communication", "ModeleMessage").objects.filter(code__in=list(MODELES_LOT3), notifications__isnull=True).delete()


class Migration(migrations.Migration):
    dependencies = [("communication", "0004_modeles_lot2")]
    operations = [migrations.RunPython(creer, supprimer)]
