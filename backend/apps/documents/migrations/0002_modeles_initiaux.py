"""DOC-02 : modèles livrés (version 1 de chaque modèle, .docx construits par `modeles_initiaux`)."""

import hashlib
import secrets
from pathlib import Path

from django.conf import settings
from django.db import migrations

from apps.documents.modeles_initiaux import MODELES_INITIAUX

TYPE_DOCX = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"


def creer(apps, schema_editor):
    Modele = apps.get_model("documents", "ModeleDocument")
    Version = apps.get_model("documents", "VersionModele")
    Fichier = apps.get_model("noyau", "Fichier")
    for initial in MODELES_INITIAUX:
        modele, cree = Modele.objects.get_or_create(
            code=initial.code,
            defaults={
                "libelle": initial.libelle,
                "nature": initial.nature,
                "description": initial.description,
                "signature_requise": initial.signature_requise,
                "signataires": list(initial.signataires),
            },
        )
        if not cree and modele.version_active_id:
            continue
        contenu = initial.construire()
        relatif = f"{secrets.token_hex(2)}/{secrets.token_hex(16)}"
        destination = Path(settings.MEDIA_ROOT) / relatif
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_bytes(contenu)
        fichier = Fichier.objects.create(
            nom_origine=f"{initial.code}.docx",
            type_mime=TYPE_DOCX,
            taille=len(contenu),
            sha256=hashlib.sha256(contenu).hexdigest(),
            chemin=relatif,
            controle_antivirus="genere",
            depose_par="installation",
        )
        version = Version.objects.create(modele=modele, numero=1, fichier=fichier, commentaire="Modèle livré", deposee_par="installation")
        modele.version_active = version
        modele.save(update_fields=["version_active"])


def supprimer(apps, schema_editor):
    Modele = apps.get_model("documents", "ModeleDocument")
    Version = apps.get_model("documents", "VersionModele")
    for modele in Modele.objects.filter(code__in=[m.code for m in MODELES_INITIAUX], documents__isnull=True):
        modele.version_active = None
        modele.save(update_fields=["version_active"])
        Version.objects.filter(modele=modele).delete()
        modele.delete()


class Migration(migrations.Migration):
    dependencies = [("documents", "0001_initial"), ("noyau", "0003_compteur")]
    operations = [migrations.RunPython(creer, supprimer)]
