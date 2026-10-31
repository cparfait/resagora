from django.db import migrations

# Pièces demandées par type d'usager (USR-03) ; aucune copie de pièce d'identité n'est exigée (minimisation).
PIECES = [
    ("statuts", "Statuts à jour", ["association"], True, None),
    ("recepisse", "Récépissé de déclaration en préfecture (ou extrait du JOAFE)", ["association"], True, None),
    ("bureau", "Composition du bureau", ["association"], True, 12),
    ("assurance", "Attestation d'assurance responsabilité civile", ["association", "entreprise", "particulier", "ecole", "autre_collectivite"], True, 12),
    ("kbis", "Extrait Kbis de moins de trois mois", ["entreprise"], True, 3),
    ("domicile", "Justificatif de domicile de moins de trois mois (tarif résident)", ["particulier"], False, 3),
]


def creer(apps, schema_editor):
    TypePiece = apps.get_model("usagers", "TypePiece")
    for code, libelle, types, obligatoire, validite in PIECES:
        TypePiece.objects.update_or_create(code=code, defaults={
            "libelle": libelle, "types_usager": types, "obligatoire": obligatoire, "validite_mois": validite,
        })


def supprimer(apps, schema_editor):
    apps.get_model("usagers", "TypePiece").objects.filter(code__in=[p[0] for p in PIECES], pieces__isnull=True).delete()


class Migration(migrations.Migration):
    dependencies = [("usagers", "0001_initial")]
    operations = [migrations.RunPython(creer, supprimer)]
