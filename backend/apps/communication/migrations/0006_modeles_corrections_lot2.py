from django.db import migrations

from apps.communication.modeles_initiaux import MODELES_SIGNATURE_ET_COMPTES, SMS_COMPLEMENTS


def creer(apps, schema_editor):
    Modele = apps.get_model("communication", "ModeleMessage")
    for code, (libelle, sujet, corps, sms) in MODELES_SIGNATURE_ET_COMPTES.items():
        Modele.objects.get_or_create(code=code, defaults={"libelle": libelle, "sujet": sujet, "corps": corps, "sms": sms})
    for code, sms in SMS_COMPLEMENTS.items():
        Modele.objects.filter(code=code, sms="").update(sms=sms)


def supprimer(apps, schema_editor):
    Modele = apps.get_model("communication", "ModeleMessage")
    Modele.objects.filter(code__in=list(MODELES_SIGNATURE_ET_COMPTES), notifications__isnull=True).delete()
    for code, sms in SMS_COMPLEMENTS.items():
        Modele.objects.filter(code=code, sms=sms).update(sms="")


class Migration(migrations.Migration):
    dependencies = [("communication", "0005_modeles_lot3")]
    operations = [migrations.RunPython(creer, supprimer)]
