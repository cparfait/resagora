from django.db import migrations

# Conditions de confirmation par type (RG-06), modifiables ensuite dans « Types de réservation ».
TYPES = [
    ("ponctuelle", "Réservation ponctuelle", True, False, False, False, 1),
    ("creneau_annuel", "Créneau annuel (saison sportive)", True, True, False, False, 2),
    ("location", "Location de salle", True, True, True, True, 3),
    ("manifestation", "Manifestation ou événement", True, True, False, True, 4),
    ("scolaire", "Occupation scolaire", False, False, False, False, 5),
    ("municipal", "Service municipal", False, False, False, False, 6),
]


def creer(apps, schema_editor):
    Type = apps.get_model("reservations", "TypeReservation")
    for code, libelle, pieces, convention, acompte, caution, ordre in TYPES:
        Type.objects.update_or_create(code=code, defaults={
            "libelle": libelle, "exige_pieces": pieces, "exige_convention": convention, "exige_acompte": acompte,
            "exige_caution": caution, "ordre": ordre,
        })


def supprimer(apps, schema_editor):
    apps.get_model("reservations", "TypeReservation").objects.filter(code__in=[t[0] for t in TYPES], dossiers__isnull=True).delete()


class Migration(migrations.Migration):
    dependencies = [("reservations", "0001_initial")]
    operations = [migrations.RunPython(creer, supprimer)]
