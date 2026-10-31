"""Lot 5 (revue sécurité, M2) : signaler une panne de matériel est une action à part, que n'ont pas les rôles en
lecture seule (direction, contrôle interne, accueil)."""

from django.db import migrations

ROLES = ("gestionnaire", "planificateur", "gardien", "technicien_materiel")
ACTION = "signaler_panne_materiel"


def ajouter(apps, schema_editor):
    for role in apps.get_model("habilitations", "Role").objects.filter(code__in=ROLES):
        if ACTION not in role.actions:
            role.actions = sorted([*role.actions, ACTION])
            role.save(update_fields=["actions"])


def retirer(apps, schema_editor):
    for role in apps.get_model("habilitations", "Role").objects.filter(code__in=ROLES):
        role.actions = [a for a in role.actions if a != ACTION]
        role.save(update_fields=["actions"])


class Migration(migrations.Migration):
    dependencies = [("habilitations", "0005_roles_separation_des_taches")]
    operations = [migrations.RunPython(ajouter, retirer)]
