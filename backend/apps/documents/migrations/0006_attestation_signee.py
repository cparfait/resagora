"""VAL-04 (revue métier du lot 6, m8) : l'attestation de valorisation est signée par l'élu délégataire et cite son
fondement (CGPPP L. 2125-1) ; version 2 du modèle livré. Réversible : la version précédente redevient active (les
versions de modèle sont immuables, RG-13 : la version 2 reste conservée, inactive)."""

import hashlib
import secrets
from pathlib import Path

from django.conf import settings
from django.db import migrations

CODE = "attestation-valorisation"
TYPE_DOCX = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"


def installer(apps, schema_editor):
    from apps.documents.modeles_initiaux import attestation_valorisation

    Modele = apps.get_model("documents", "ModeleDocument")
    Version = apps.get_model("documents", "VersionModele")
    Fichier = apps.get_model("noyau", "Fichier")
    modele = Modele.objects.filter(code=CODE).first()
    if modele is None:
        return
    modele.signature_requise, modele.signataires = True, ["elu"]
    existante = Version.objects.filter(modele=modele, commentaire__startswith="Modèle livré v2").first()
    if existante is not None:
        modele.version_active = existante
    else:
        contenu = attestation_valorisation()
        relatif = f"{secrets.token_hex(2)}/{secrets.token_hex(16)}"
        destination = Path(settings.MEDIA_ROOT) / relatif
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_bytes(contenu)
        fichier = Fichier.objects.create(
            nom_origine=f"{CODE}-v2.docx",
            type_mime=TYPE_DOCX,
            taille=len(contenu),
            sha256=hashlib.sha256(contenu).hexdigest(),
            chemin=relatif,
            controle_antivirus="genere",
            depose_par="installation",
        )
        numero = (Version.objects.filter(modele=modele).order_by("-numero").values_list("numero", flat=True).first() or 0) + 1
        modele.version_active = Version.objects.create(
            modele=modele,
            numero=numero,
            fichier=fichier,
            commentaire="Modèle livré v2 : signature de l'élu, fondement CGPPP L. 2125-1",
            deposee_par="installation",
        )
    modele.save(update_fields=["signature_requise", "signataires", "version_active"])


def retirer(apps, schema_editor):
    Modele = apps.get_model("documents", "ModeleDocument")
    Version = apps.get_model("documents", "VersionModele")
    modele = Modele.objects.filter(code=CODE).first()
    if modele is None:
        return
    v2 = Version.objects.filter(modele=modele, commentaire__startswith="Modèle livré v2").first()
    precedente = Version.objects.filter(modele=modele).exclude(pk=getattr(v2, "pk", None)).order_by("-numero").first()
    modele.signature_requise, modele.signataires = False, []
    if precedente is not None:
        modele.version_active = precedente
    modele.save(update_fields=["signature_requise", "signataires", "version_active"])


class Migration(migrations.Migration):
    dependencies = [("documents", "0005_scan_et_invitations"), ("noyau", "0002_parametres_et_fichiers")]
    operations = [migrations.RunPython(installer, retirer)]
