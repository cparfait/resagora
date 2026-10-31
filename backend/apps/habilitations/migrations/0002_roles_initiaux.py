from django.db import migrations

from apps.habilitations.actions import ROLES_INITIAUX


def creer(apps, schema_editor):
    Role = apps.get_model("habilitations", "Role")
    Perimetre = apps.get_model("habilitations", "Perimetre")
    for code, definition in ROLES_INITIAUX.items():
        Role.objects.update_or_create(
            code=code,
            defaults={
                "libelle": definition["libelle"],
                "actions": sorted(definition["actions"]),
                "double_authentification": definition["double_authentification"],
            },
        )
    Perimetre.objects.get_or_create(nom="Ville entière", defaults={"tous_sites": True})


def supprimer(apps, schema_editor):
    apps.get_model("habilitations", "Role").objects.filter(code__in=list(ROLES_INITIAUX), habilitations__isnull=True).delete()
    apps.get_model("habilitations", "Perimetre").objects.filter(nom="Ville entière", habilitations__isnull=True).delete()


class Migration(migrations.Migration):
    dependencies = [("habilitations", "0001_initial")]
    operations = [migrations.RunPython(creer, supprimer)]
