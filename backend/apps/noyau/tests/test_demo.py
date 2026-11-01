"""Jeu de démonstration : les données d'exemple de CityResa (mêmes sites, espaces, usagers et réservations, pour comparer
les deux applications), sans donnée personnelle réelle, et les parties des lots suivants."""

from __future__ import annotations

import collections

import pytest
from django.core.management import call_command
from django.core.management.base import CommandError

from apps.noyau.demo import cityresa, simulation
from apps.referentiel.models import Espace, Site
from apps.reservations.models import Reservation, Verrou
from apps.usagers.models import Contact, Usager

pytestmark = pytest.mark.django_db

# Statuts de CityResa → statuts de la plateforme.
STATUTS = {
    "a_traiter": "demande",
    "en_traitement": "en_instruction",
    "acceptee": "validee",
    "signee": "validee",
    "confirmee": "confirmee",
    "terminee": "realisee",
    "archivee": "cloturee",
    "refusee": "refusee",
    "annulee": "annulee",
}


def test_jeu_de_demonstration_complet_et_coherent(monkeypatch, modeles_documents):
    from apps.documents import services as documents
    from apps.finances.models import Caution, GrilleTarifaire, PieceComptable
    from apps.noyau import fichiers

    monkeypatch.setattr(documents, "convertir_en_pdfa", lambda nom, docx, transport=None: b"%PDF-1.7 %%EOF")
    monkeypatch.setattr(fichiers, "analyser_clamav", lambda contenu: None)
    call_command("charger_demo")
    d = cityresa.donnees()
    # Mêmes données que CityResa : sites, espaces, usagers, et toutes les réservations à leur statut.
    assert Site.objects.filter(code__startswith="demo-").count() == len(d["sites"])
    assert Espace.objects.count() == len(d["espaces"])
    attendus = collections.Counter(cityresa.TYPES_USAGER.get(u["type"], u["type"]) for u in d["usagers"])
    assert collections.Counter(Usager.objects.values_list("type", flat=True)) == attendus
    reprises = Reservation.objects.exclude(dossier__observations=simulation.MENTION)
    assert reprises.count() == len(d["reservations"]), "aucune réservation de CityResa écartée"
    assert collections.Counter(reprises.values_list("statut", flat=True)) == collections.Counter(
        STATUTS[r["statut"]] for r in d["reservations"]
    )
    # Plannings simulés (repérables, absents de CityResa) : créneaux réguliers, manifestations, assemblées générales.
    simulees = Reservation.objects.filter(dossier__observations=simulation.MENTION)
    assert simulees.filter(dossier__type_reservation__code="creneau_annuel").count() >= 40
    assert simulees.filter(espace__code="mb-polyvalente").exists() and simulees.filter(espace__code="doret").exists()
    assert Verrou.objects.exists()
    assert Reservation.objects.filter(dossier__usager__type="particulier", dossier__type_reservation__code="location").exists()
    # Aucune donnée personnelle réelle (CLAUDE.md, règle 7) : contacts fictifs, domaine réservé .test.
    assert not Contact.objects.exclude(courriel__endswith="@exemple.test").exists()
    # Lot 3 : grille votée aux tarifs de CityResa, devis des locations, caution de 1 000 € de la salle polyvalente de
    # l'Espace Maison Blanche (CAU-01), factures.
    assert GrilleTarifaire.objects.filter(statut="votee").count() == 1
    assert PieceComptable.objects.filter(nature="devis").exists() and PieceComptable.objects.filter(nature="facture").exists()
    assert Caution.objects.filter(reservation__espace__code="mb-polyvalente", montant=100000).exists()
    # Lot 4 : huit gardiens rattachables aux comptes de recette, vacations issues des trames, besoins, absence.
    from apps.personnel.models import Absence, Agent, Besoin, Vacation

    assert Agent.objects.filter(identifiant_ad__regex=r"^gardien0[1-8]$").count() == 8
    assert Vacation.objects.filter(statut="planifiee").count() > 20 and Besoin.objects.exists()
    assert Absence.objects.exists() and Vacation.objects.filter(statut="a_pourvoir").exists()
    # Lot 5 : matériel de CityResa, prêts demandés par ses réservations dont un retour avec manquants, une panne.
    from apps.materiel.models import Panne, ReservationMateriel, Stock

    assert Stock.objects.filter(materiel__code="tables").count() == 1
    assert ReservationMateriel.objects.filter(manquants=2).exists() and Panne.objects.filter(statut="ouverte").exists()
    # Lot 6 : exercice valorisé, subventions en numéraire, attestation déposée, envoi programmé du planning.
    from apps.pilotage.models import EnvoiProgramme
    from apps.valorisation.models import Exercice, SubventionNumeraire, Valorisation

    exercice = Exercice.objects.get()
    assert SubventionNumeraire.objects.filter(exercice=exercice).count() == 3
    assert Valorisation.objects.filter(exercice=exercice, actuelle=True, total__gt=0).count() >= 5
    assert not Valorisation.objects.filter(document__isnull=False).exists(), "pas d'attestation avant la clôture"
    assert EnvoiProgramme.objects.filter(prochain_envoi_le__isnull=False).count() == 1
    with pytest.raises(CommandError):
        call_command("charger_demo")
