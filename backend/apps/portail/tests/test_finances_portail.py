"""Portail, lot 3 : simulation de tarif (TAR-11), devis accepté en ligne (TAR-04), factures avec coordonnées de
règlement (TAR-12), cautions (CAU-02), accès refusés aux pièces d'un autre usager (RG-14)."""

from __future__ import annotations

from datetime import date

import pytest
from django.test import override_settings
from freezegun import freeze_time

from apps.documents import services as documents
from apps.finances import cautions, facturation
from apps.finances.models import Caution
from apps.finances.tests.outils import PDF, grille_votee, location
from apps.noyau import fichiers
from apps.noyau.parametres import parametre
from apps.reservations import services as reservations
from tests.fabriques import EspaceFabrique, agent

from .outils import client_contact, compte_actif

pytestmark = [pytest.mark.django_db, pytest.mark.urls("config.urls_portail")]


@pytest.fixture(autouse=True)
def environnement(monkeypatch, modeles_documents):
    monkeypatch.setattr(documents, "convertir_en_pdfa", lambda nom, docx, transport=None: PDF)
    monkeypatch.setattr(fichiers, "analyser_clamav", lambda contenu: None)
    with freeze_time("2026-11-02 10:00"):
        yield


@pytest.fixture
def espace():
    espace = EspaceFabrique(nom="Salle des fêtes Henri-Barbusse")
    espace.reservable_portail = True
    espace.save()
    grille_votee(espace)
    return espace


@override_settings(CANAL="portail")
def test_tar11_simulation_de_tarif_publique(client_api, espace):
    reponse = client_api.post(
        "/api/portail/simulation-tarif",
        {
            "espace": espace.pk,
            "date": "2026-12-12",
            "heure_debut": "14:00",
            "heure_fin": "18:00",
            "categorie": "particulier",
            "resident": False,
        },
        format="json",
    )
    assert reponse.status_code == 200
    resultat = reponse.json()
    # 4 h à 40 € = 160 € ; samedi +25 % = 40 € ; non-résident +50 % = 80 €.
    assert resultat["total"] == 28000 and resultat["total_texte"] == "280,00 €" and resultat["caution_texte"] == "300,00 €"
    sans_grille = client_api.post(
        "/api/portail/simulation-tarif",
        {"espace": espace.pk, "date": "2025-06-01", "heure_debut": "14:00", "heure_fin": "18:00", "categorie": "particulier"},
        format="json",
    )
    assert sans_grille.status_code == 409 and sans_grille.json()["code"] == "tarif_indisponible"
    prive = EspaceFabrique(reservable_portail=False)
    assert (
        client_api.post(
            "/api/portail/simulation-tarif",
            {"espace": prive.pk, "date": "2026-12-12", "heure_debut": "14:00", "heure_fin": "18:00", "categorie": "particulier"},
            format="json",
        ).status_code
        == 404
    )


@override_settings(CANAL="portail")
def test_tar04_devis_accepte_en_ligne_par_un_contact_habilite(espace):
    compte = compte_actif()
    usager = compte.contact.rattachements.first().usager
    reservation = location(usager=usager, espace=espace)
    devis = facturation.etablir_devis(reservation.dossier, acteur=agent("gestionnaire"))
    client = client_contact(compte)
    liste = client.get("/api/portail/factures", {"dossier": reservation.dossier_id}).json()
    assert liste[0]["numero"] == devis.numero and liste[0]["a_accepter"] is True and liste[0]["statut_libelle"] == "À accepter"
    url = f"/api/portail/dossiers/{reservation.dossier_id}/devis/{devis.pk}/accepter"
    intrus = client_contact(compte_actif())
    assert intrus.post(url).status_code == 404
    usager.rattachements.update(peut_signer=False)
    assert client.post(url).status_code == 403
    usager.rattachements.update(peut_signer=True)
    accepte = client.post(url).json()
    assert accepte["statut"] == "accepte"
    assert client.post(url).status_code == 409


@override_settings(CANAL="portail")
def test_tar12_facture_avec_coordonnees_du_comptable_et_reference(espace):
    compte = compte_actif()
    reservation = location(usager=compte.contact.rattachements.first().usager, espace=espace)
    facture = facturation.facturer(reservation.dossier, acteur=agent("gestionnaire"))
    client = client_contact(compte)
    representation = client.get("/api/portail/factures").json()[0]
    assert representation["reglement"]["iban"] == parametre("comptable.iban")
    assert representation["reglement"]["reference"] == facture.reference_virement == facture.numero.replace("-", "")
    assert representation["statut_libelle"] == "À régler" and representation["reste_texte"] == "80,00 €"
    contexte = facture.document.contexte
    assert contexte["reglement"]["iban"] == parametre("comptable.iban") and contexte["piece"]["reference_virement"]
    assert client.get(f"/api/portail/factures/{facture.pk}/fichier").status_code == 200
    intrus = client_contact(compte_actif())
    assert intrus.get(f"/api/portail/factures/{facture.pk}/fichier").status_code == 404
    assert intrus.get("/api/portail/factures").json() == []


@override_settings(CANAL="portail")
def test_cau02_caution_suivie_sur_le_portail(espace):
    compte = compte_actif()
    reservation = location(usager=compte.contact.rattachements.first().usager, espace=espace, valider=False)
    reservations.valider(reservation, acteur=agent("gestionnaire"))
    caution = Caution.objects.get(reservation=reservation)
    client = client_contact(compte)
    assert client.get("/api/portail/cautions").json()[0]["statut_libelle"] == "À déposer"
    cautions.recevoir(caution, acteur=agent("regisseur"), mode="cheque", reference="Chèque 4411", jour=date(2026, 11, 2))
    suivi = client.get("/api/portail/cautions").json()[0]
    assert suivi["statut_libelle"] == "Déposée" and suivi["montant_texte"] == "300,00 €"
    assert client_contact(compte_actif()).get("/api/portail/cautions").json() == []
