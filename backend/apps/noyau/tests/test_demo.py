"""Jeu de démonstration : volumes attendus (tests-recette) et cohérence des réservations."""

from __future__ import annotations

import pytest
from django.core.management import call_command
from django.core.management.base import CommandError

from apps.referentiel.models import Espace, Site
from apps.reservations.models import Occurrence, Verrou
from apps.usagers.models import Usager

pytestmark = pytest.mark.django_db


def test_jeu_de_demonstration_complet_et_coherent(monkeypatch, modeles_documents):
    from apps.documents import services as documents
    from apps.finances.models import Caution, GrilleTarifaire, PieceComptable
    from apps.noyau import fichiers

    monkeypatch.setattr(documents, "convertir_en_pdfa", lambda nom, docx, transport=None: b"%PDF-1.7 %%EOF")
    monkeypatch.setattr(fichiers, "analyser_clamav", lambda contenu: None)
    call_command("charger_demo")
    assert Site.objects.filter(code__startswith="demo-").count() == 3
    assert Espace.objects.count() == 40 and Espace.objects.filter(parent__isnull=False).count() == 5
    assert Usager.objects.filter(type="association").count() == 40 and Usager.objects.filter(type="ecole").count() == 5
    assert Usager.objects.filter(type="particulier").count() == 10
    assert Occurrence.objects.filter(statut__in=["validee", "confirmee"]).count() > 500
    assert Verrou.objects.exists()
    assert (
        Occurrence.objects.filter(
            reservation__dossier__usager__type="particulier", reservation__dossier__type_reservation__code="location"
        ).count()
        >= 5
    )
    # Lot 3 : grille votée, devis des locations, caution de 500 € de la salle des fêtes (CAU-01), factures.
    assert GrilleTarifaire.objects.filter(statut="votee").count() == 1
    assert PieceComptable.objects.filter(nature="devis").exists() and PieceComptable.objects.filter(nature="facture").exists()
    assert Caution.objects.filter(reservation__espace__famille__code="salle-fetes", montant=50000).exists()
    with pytest.raises(CommandError):
        call_command("charger_demo")
