"""Habilitations courantes des agents d'équipement (PER-01) ; le SSIAP 1 est exigé pour garder un site (ERP)."""

from django.db import migrations

TYPES = [
    ("ssiap1", "SSIAP 1 — agent de service de sécurité incendie", True),
    ("ssiap2", "SSIAP 2 — chef d'équipe de sécurité incendie", False),
    ("psc1", "PSC1 — prévention et secours civiques", False),
    ("sst", "Sauveteur secouriste du travail", False),
    ("habilitation-electrique-bs", "Habilitation électrique BS", False),
]


def creer(apps, schema_editor):
    Type = apps.get_model("personnel", "TypeHabilitation")
    for code, libelle, exigee in TYPES:
        Type.objects.get_or_create(code=code, defaults={"libelle": libelle, "exigee_pour_gardiennage": exigee})


def supprimer(apps, schema_editor):
    apps.get_model("personnel", "TypeHabilitation").objects.filter(code__in=[t[0] for t in TYPES]).delete()


class Migration(migrations.Migration):
    dependencies = [("personnel", "0001_initial")]
    operations = [migrations.RunPython(creer, supprimer)]
