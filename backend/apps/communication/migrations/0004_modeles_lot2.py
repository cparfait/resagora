from django.db import migrations

from apps.communication.modeles_initiaux import MODELES_LOT2

SMS_EXISTANTS = {
    "fermeture_exceptionnelle": "Ville de Châtillon : {{ lieu }} fermé du {{ debut }} au {{ fin }}. Détails par courriel.",
    "occurrence_annulee": "Ville de Châtillon : séance du {{ date }} ({{ espace }}) annulée. Détails par courriel.",
}


def creer(apps, schema_editor):
    Modele = apps.get_model("communication", "ModeleMessage")
    for code, (libelle, sujet, corps, sms) in MODELES_LOT2.items():
        Modele.objects.get_or_create(code=code, defaults={"libelle": libelle, "sujet": sujet, "corps": corps, "sms": sms})
    for code, sms in SMS_EXISTANTS.items():
        Modele.objects.filter(code=code, sms="").update(sms=sms)


def supprimer(apps, schema_editor):
    Modele = apps.get_model("communication", "ModeleMessage")
    Modele.objects.filter(code__in=list(MODELES_LOT2), notifications__isnull=True).delete()
    Modele.objects.filter(code__in=list(SMS_EXISTANTS)).update(sms="")


class Migration(migrations.Migration):
    dependencies = [("communication", "0003_messagerie_preferences_sms")]
    operations = [migrations.RunPython(creer, supprimer)]
