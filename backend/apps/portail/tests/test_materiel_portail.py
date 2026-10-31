"""Portail, lot 5 : matériel demandé à l'étape 2 de la demande puis prêt « demandé » à l'envoi (MAT-02, POR-04),
demande sur un dossier envoyé, refus lisible quand la quantité manque, accès refusé à un autre usager (RG-14)."""

from __future__ import annotations

import pytest
from django.test import override_settings
from freezegun import freeze_time

from apps.materiel import services as materiel
from apps.materiel.models import Materiel, ReservationMateriel
from apps.reservations.models import TypeReservation
from tests.fabriques import EspaceFabrique

from .outils import client_contact, compte_actif

pytestmark = [pytest.mark.django_db, pytest.mark.urls("config.urls_portail")]


@pytest.fixture(autouse=True)
def horloge():
    with freeze_time("2026-11-02 10:00"):
        yield


@pytest.fixture
def lieu():
    espace = EspaceFabrique(nom="Salle polyvalente")
    tables = Materiel.objects.create(
        code="table", libelle="Table pliante", unite="table", propose_portail=True, valeur_journaliere_centimes=300
    )
    interne = Materiel.objects.create(code="podium", libelle="Podium", propose_portail=False, valeur_journaliere_centimes=15000)
    stock = materiel.entrer(tables, espace.batiment.site, 15, acteur="système")
    materiel.entrer(interne, espace.batiment.site, 1, acteur="système")
    return espace, stock


def _brouillon(client, usager, espace, materiel_demande):
    ponctuelle = TypeReservation.objects.get(code="ponctuelle")
    creneau = {"espace": espace.pk, "date_debut": "2026-12-12", "heure_debut": "14:00", "heure_fin": "23:00"}
    dossier = client.post(
        "/api/portail/dossiers", {"usager": usager.pk, "type_reservation": ponctuelle.pk, "creneaux": [creneau]}, format="json"
    ).json()
    reponse = client.patch(
        f"/api/portail/dossiers/{dossier['id']}",
        {"etape": 2, "objet": "Repas associatif", "materiel": materiel_demande},
        format="json",
    )
    return dossier["id"], reponse


@override_settings(CANAL="portail")
def test_mat02_catalogue_du_site_sans_le_materiel_interne(lieu):
    espace, _stock = lieu
    compte = compte_actif()
    catalogue = client_contact(compte).get("/api/portail/materiel", {"espace": espace.pk}).json()
    assert [m["libelle"] for m in catalogue] == ["Table pliante"] and catalogue[0]["maximum"] == 15


@override_settings(CANAL="portail")
def test_mat02_materiel_demande_a_l_etape_2_devient_un_pret_a_valider(lieu):
    espace, stock = lieu
    compte = compte_actif()
    usager = compte.contact.rattachements.first().usager
    client = client_contact(compte)
    identifiant, reponse = _brouillon(client, usager, espace, [{"materiel": stock.materiel_id, "quantite": 12}])
    assert reponse.status_code == 200 and reponse.json()["materiel_demande"] == [{"materiel": stock.materiel_id, "quantite": 12}]
    envoye = client.post(f"/api/portail/dossiers/{identifiant}/envoyer")
    assert envoye.status_code == 200, envoye.json()
    prets = envoye.json()["materiel"]
    assert [(p["materiel"], p["quantite"], p["statut_libelle"]) for p in prets] == [
        ("Table pliante", 12, "Demandé, en attente de la Ville")
    ]
    assert "valeur" not in str(prets) and ReservationMateriel.objects.get().origine == "portail"


@override_settings(CANAL="portail")
def test_mat02_quantite_indisponible_refusee_a_l_envoi(lieu):
    espace, stock = lieu
    compte = compte_actif()
    usager = compte.contact.rattachements.first().usager
    client = client_contact(compte)
    identifiant, _ = _brouillon(client, usager, espace, [{"materiel": stock.materiel_id, "quantite": 20}])
    refus = client.post(f"/api/portail/dossiers/{identifiant}/envoyer")
    assert refus.status_code == 400 and "15" in refus.json()["message"]
    assert ReservationMateriel.objects.count() == 0


@override_settings(CANAL="portail")
def test_mat02_materiel_non_propose_refuse_au_brouillon(lieu):
    espace, _stock = lieu
    compte = compte_actif()
    usager = compte.contact.rattachements.first().usager
    podium = Materiel.objects.get(code="podium")
    _identifiant, reponse = _brouillon(client_contact(compte), usager, espace, [{"materiel": podium.pk, "quantite": 1}])
    assert reponse.status_code == 400 and reponse.json()["code"] == "materiel_invalide"


@override_settings(CANAL="portail")
def test_rg14_demande_de_materiel_sur_le_dossier_d_un_autre_usager_refusee(lieu):
    espace, stock = lieu
    compte = compte_actif()
    usager = compte.contact.rattachements.first().usager
    client = client_contact(compte)
    identifiant, _ = _brouillon(client, usager, espace, [])
    envoye = client.post(f"/api/portail/dossiers/{identifiant}/envoyer").json()
    reservation = envoye["reservations"][0]["id"]
    ajout = client.post(
        f"/api/portail/dossiers/{identifiant}/materiel",
        {"reservation": reservation, "materiel": stock.materiel_id, "quantite": 4},
        format="json",
    )
    assert ajout.status_code == 201 and ajout.json()["materiel"][0]["quantite"] == 4
    intrus = client_contact(compte_actif())
    refus = intrus.post(
        f"/api/portail/dossiers/{identifiant}/materiel",
        {"reservation": reservation, "materiel": stock.materiel_id, "quantite": 1},
        format="json",
    )
    assert refus.status_code == 404
