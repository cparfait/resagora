"""USR-06 et ADR 0006 (revues du lot 2) : aucune donnée personnelle de gestion ne survit à l'anonymisation ; les
archives publiques restent intactes jusqu'au terme de leur durée d'utilité, puis sont purgées."""

from __future__ import annotations

from datetime import date

import pytest
from django.apps import apps
from django.db import models
from freezegun import freeze_time

from apps.communication.models import Message
from apps.communication.services import notifier
from apps.documents import services as documents
from apps.documents.models import Document, Signataire
from apps.noyau import fichiers
from apps.noyau.exceptions import ErreurMetier
from apps.portail.tests.outils import compte_actif
from apps.reservations.tests.outils import reserver, valider_systeme
from apps.usagers import rgpd
from tests.fabriques import EspaceFabrique, agent, saison_2026, usager_avec_contact

pytestmark = pytest.mark.django_db
PDF = b"%PDF-1.7\n% convention\n%%EOF\n"


@pytest.fixture(autouse=True)
def sans_services_externes(monkeypatch, modeles_documents):
    monkeypatch.setattr(documents, "convertir_en_pdfa", lambda nom, docx, transport=None: PDF)
    monkeypatch.setattr(fichiers, "analyser_clamav", lambda contenu: None)


def _occurrences_du_nom(nom: str) -> list[str]:
    """Toutes les colonnes texte de toutes les tables métier où le nom apparaît encore."""
    trouves = []
    for modele in apps.get_models():
        if modele._meta.app_label in {"audit", "sessions", "admin", "contenttypes", "auth"}:
            continue
        for champ in modele._meta.get_fields():
            if isinstance(champ, (models.CharField, models.TextField)) and not champ.is_relation:
                if modele.objects.filter(**{f"{champ.name}__icontains": nom}).exists():
                    trouves.append(f"{modele._meta.label}.{champ.name}")
    return trouves


def test_usr06_aucune_donnee_personnelle_de_gestion_apres_anonymisation(django_capture_on_commit_callbacks):
    with freeze_time("2022-01-10 10:00"):
        saison_2026()
        particulier = usager_avec_contact(type="particulier", nom="Zephyrin Quillebeuf")
        contact = particulier.rattachements.first().contact
        contact.nom = "Quillebeuf"
        contact.save()
        compte = compte_actif(particulier)
        reservation = valider_systeme(
            reserver(EspaceFabrique(), date(2022, 2, 1), "14:00", "18:00", usager=particulier, type_code="location")
        )
        dossier = reservation.dossier
        dossier.objet = "Anniversaire de Zephyrin Quillebeuf"
        dossier.save()
        message = Message.objects.create(dossier=dossier, auteur_contact=compte.contact, corps="Je suis Zephyrin Quillebeuf")
        notifier(
            "message_usager",
            {"dossier": dossier, "usager": particulier, "auteur": str(contact), "extrait": message.corps, "lien": ""},
            courriels=["service@chatillon.test"],
            objet=message,
        )
        convention = documents.generer("convention", dossier, acteur=agent("gestionnaire"))
        documents.envoyer_en_signature(convention, acteur=agent("gestionnaire"), mode="manuel")
    with freeze_time("2026-11-01 10:00"):
        rgpd.anonymiser_usager(particulier, acteur="système", motif="Demande d'effacement")
    restes = [r for r in _occurrences_du_nom("Quillebeuf") if r != "documents.Document.contexte"]
    assert restes == [], restes
    assert Signataire.objects.filter(circuit__document=convention, role="usager").get().nom.startswith("Contact anonymisé")
    # Archive publique : le contenu signé ou généré reste intact jusqu'au terme de sa durée (ADR 0006).
    assert "Quillebeuf" in str(Document.objects.get(pk=convention.pk).contexte)


def test_adr0006_archives_purgees_au_terme_de_leur_duree_pour_un_usager_anonymise():
    with freeze_time("2020-01-10 10:00"):
        saison_2026()
        particulier = usager_avec_contact(type="particulier", nom="Camille Archivee")
        reservation = valider_systeme(reserver(EspaceFabrique(), date(2020, 2, 1), "14:00", "18:00", usager=particulier))
        convention = documents.generer("convention", reservation.dossier, acteur=agent("gestionnaire"))
        actif = usager_avec_contact(nom="Association Toujours Active")
        reservation_active = valider_systeme(reserver(EspaceFabrique(), date(2020, 2, 2), "14:00", "18:00", usager=actif))
        conservee = documents.generer("convention", reservation_active.dossier, acteur=agent("gestionnaire"))
    with freeze_time("2024-06-01 10:00"):
        rgpd.anonymiser_usager(particulier, acteur="système", motif="Durée échue")
        assert rgpd.purger_archives_echues() == 0, "durée d'utilité (5 ans) non échue"
    with freeze_time("2025-03-01 10:00"):
        assert rgpd.purger_archives_echues() == 1
        assert rgpd.purger_archives_echues() == 0
    purgee = Document.objects.get(pk=convention.pk)
    assert "purge" in purgee.contexte and "Archivee" not in str(purgee.contexte)
    assert purgee.numero == convention.numero and purgee.sha256 == convention.sha256
    with pytest.raises(ErreurMetier) as refus:
        fichiers.lire(purgee.fichier)
    assert refus.value.code == "fichier_purge"
    assert "Association Toujours Active" in str(Document.objects.get(pk=conservee.pk).contexte), "usager non anonymisé"
