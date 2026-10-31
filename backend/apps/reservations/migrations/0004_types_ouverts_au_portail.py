from django.db import migrations

# POR-04 : types demandables sur le portail. Les créneaux annuels passent par les campagnes, les
# occupations municipales par le back-office ; l'occupation scolaire est réservée aux écoles.
REGLES = {
    "creneau_annuel": (False, []),
    "municipal": (False, []),
    "scolaire": (True, ["ecole"]),
    "location": (True, ["particulier", "entreprise", "association", "autre_collectivite"]),
}


def appliquer(apps, schema_editor):
    Type = apps.get_model("reservations", "TypeReservation")
    for code, (ouvert, types) in REGLES.items():
        Type.objects.filter(code=code).update(ouvert_portail=ouvert, types_usager=types)


def retablir(apps, schema_editor):
    apps.get_model("reservations", "TypeReservation").objects.filter(code__in=list(REGLES)).update(ouvert_portail=True, types_usager=[])


class Migration(migrations.Migration):
    dependencies = [("reservations", "0003_brouillon_portail_types")]
    operations = [migrations.RunPython(appliquer, retablir)]
