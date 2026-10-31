"""Lot 7 : messages du paiement en ligne (TAR-07). Textes figés dans la migration (indépendants du code courant)."""

from django.db import migrations

SIGNATURE = "\n\nService des équipements sportifs et associatifs\nVille de Châtillon\n{{ portail_url }}"
MODELES = {
    "paiement_en_ligne_recu": (
        "Paiement en ligne accepté (PayFiP)",
        "Paiement accepté : facture {{ piece.numero }}",
        "Bonjour {{ contact.prenom }},\n\nVotre paiement en ligne de {{ montant }} pour la facture {{ piece.numero }} a été "
        "accepté (autorisation {{ numauto }}). Ce message vaut accusé de réception." + SIGNATURE,
        "Ville de Châtillon : paiement de {{ montant }} accepté pour la facture {{ piece.numero }}.",
    ),
    "paiement_en_ligne_trop_percu": (
        "Paiement en ligne : trop-perçu (service financier)",
        "Trop-perçu PayFiP sur la facture {{ piece.numero }}",
        "Un paiement en ligne de {{ montant }} (autorisation {{ numauto }}) est arrivé sur la facture {{ piece.numero }}, déjà "
        "réglée en tout ou partie. Excédent : {{ trop_percu }}. {{ verification }}\nVoir Finances → Paiements en ligne.",
        "",
    ),
    "paiement_en_ligne_a_controler": (
        "Paiement en ligne à contrôler (service financier)",
        "Paiement PayFiP à contrôler : facture {{ piece.numero }}",
        "Le résultat d'un paiement en ligne de {{ montant }} sur la facture {{ piece.numero }} demande une vérification "
        "auprès de la DGFiP : {{ motif }}.\nLe paiement en ligne de cette facture est suspendu jusqu'à la clôture du "
        "contrôle (Finances → Paiements en ligne).",
        "",
    ),
    "paiements_en_ligne_rapprochement": (
        "Rapprochement des paiements en ligne (service financier)",
        "Paiements en ligne : actions à mener",
        "Rapprochement des paiements PayFiP.\nTentatives à contrôler : {{ a_controler }}.\nTrop-perçus non remboursés : "
        "{{ trop_percus }}.\nPaiements dont l'encaissement ne correspond pas : {{ ecarts }}.\nVoir Finances → Paiements en ligne.",
        "",
    ),
}


def creer(apps, schema_editor):
    Modele = apps.get_model("communication", "ModeleMessage")
    for code, (libelle, sujet, corps, sms) in MODELES.items():
        Modele.objects.get_or_create(code=code, defaults={"libelle": libelle, "sujet": sujet, "corps": corps, "sms": sms})


def supprimer(apps, schema_editor):
    apps.get_model("communication", "ModeleMessage").objects.filter(code__in=list(MODELES), notifications__isnull=True).delete()


class Migration(migrations.Migration):
    dependencies = [("communication", "0013_modeles_lot6")]
    operations = [migrations.RunPython(creer, supprimer)]
