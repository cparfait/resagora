from django.db import migrations

from apps.communication.modeles_initiaux import MODELES_LOT6


def creer(apps, schema_editor):
    Modele = apps.get_model("communication", "ModeleMessage")
    for code, (libelle, sujet, corps, sms) in MODELES_LOT6.items():
        Modele.objects.get_or_create(code=code, defaults={"libelle": libelle, "sujet": sujet, "corps": corps, "sms": sms})


def supprimer(apps, schema_editor):
    apps.get_model("communication", "ModeleMessage").objects.filter(code__in=list(MODELES_LOT6), notifications__isnull=True).delete()


class Migration(migrations.Migration):
    dependencies = [("communication", "0012_piece_jointe")]
    operations = [migrations.RunPython(creer, supprimer)]
