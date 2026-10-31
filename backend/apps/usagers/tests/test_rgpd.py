"""USR-06 : durées de conservation, anonymisation, export ; POR-01 : validation des comptes par la Ville."""

from __future__ import annotations

from datetime import date, timedelta

import pytest
from django.utils import timezone
from freezegun import freeze_time

from apps.communication.models import Message
from apps.comptes.models import CompteUsager
from apps.portail.tests.outils import compte_actif
from apps.reservations.tests.outils import reserver
from apps.usagers import rgpd
from apps.usagers.models import PieceJustificative, TypePiece, Usager
from tests.fabriques import EspaceFabrique, agent, usager_avec_contact

pytestmark = pytest.mark.django_db


def _piece(usager: Usager, fin: date) -> PieceJustificative:
    from apps.noyau.fichiers import enregistrer_genere

    return PieceJustificative.objects.create(
        usager=usager,
        type_piece=TypePiece.objects.get(code="assurance"),
        fichier=enregistrer_genere("assurance.pdf", b"%PDF-1.7 test", "application/pdf"),
        statut="valide",
        valide_jusqu_au=fin,
    )


def test_usr06_anonymisation_d_un_usager_inactif_apres_la_duree_parametree():
    with freeze_time("2022-01-10"):
        inactif = usager_avec_contact(type="particulier", nom="Dominique Exemple")
        inactif.derniere_activite = timezone.now()
        inactif.save()
        compte = compte_actif(inactif)
        reserver(EspaceFabrique(), date(2022, 2, 1), "14:00", "18:00", usager=inactif)
        _piece(inactif, date(2022, 12, 31))
        Message.objects.create(
            dossier=inactif.dossiers.first(), auteur_contact=compte.contact, corps="Mon numéro : 06 00 00 00 00"
        )
    with freeze_time("2026-11-01"):
        actif = usager_avec_contact()
        assert rgpd.anonymiser_inactifs() == 1
    inactif.refresh_from_db()
    compte.refresh_from_db()
    assert inactif.statut == "anonymise" and inactif.nom.startswith("Particulier anonymisé")
    assert compte.statut == "ferme" and compte.identifiant.startswith("anonyme-")
    assert compte.contact.courriel.endswith("@invalide.test") and "Exemple" not in compte.contact.nom
    assert not inactif.pieces.exists()
    assert "06 00" not in Message.objects.get().corps
    assert inactif.dossiers.count() == 1
    assert Usager.objects.get(pk=actif.pk).statut == "valide"


def test_usr06_anonymisation_manuelle_reservee_et_refusee_si_reservations_en_cours(client_agent):
    usager = usager_avec_contact()
    reserver(EspaceFabrique(), timezone.localdate() + timedelta(days=30), "18:00", "20:00", usager=usager)
    url = f"/api/gestion/usagers/usagers/{usager.pk}/anonymiser"
    assert client_agent(agent("gestionnaire")).post(url, {"motif": "Demande d'effacement"}, format="json").status_code == 403
    refus = client_agent(agent("administrateur")).post(url, {"motif": "Demande d'effacement"}, format="json")
    assert refus.status_code == 409 and refus.json()["code"] == "reservations_en_cours"


def test_usr06_export_des_donnees_d_un_usager(client_agent):
    usager = usager_avec_contact()
    reponse = client_agent(agent("administrateur")).get(f"/api/gestion/usagers/usagers/{usager.pk}/export")
    assert reponse.status_code == 200 and "attachment" in reponse["Content-Disposition"]
    assert reponse.json()["contacts"][0]["contact"]["courriel"]
    assert client_agent(agent("accueil")).get(f"/api/gestion/usagers/usagers/{usager.pk}/export").status_code == 403


def test_usr06_purge_des_pieces_expirees_depuis_la_duree_parametree():
    usager = usager_avec_contact()
    with freeze_time("2026-11-01"):
        ancienne = _piece(usager, date(2025, 6, 30))
        recente = _piece(usager, date(2026, 6, 30))
        assert rgpd.purger_pieces_expirees() == 1
    assert not PieceJustificative.objects.filter(pk=ancienne.pk).exists()
    assert PieceJustificative.objects.filter(pk=recente.pk).exists()


def test_por01_comptes_a_valider_dans_le_back_office(client_agent):
    compte = compte_actif()
    CompteUsager.objects.filter(pk=compte.pk).update(statut="a_valider")
    gestionnaire = client_agent(agent("gestionnaire"))
    liste = gestionnaire.get("/api/gestion/usagers/comptes", {"statut": "a_valider"}).json()
    assert [c["identifiant"] for c in liste["results"]] == [compte.identifiant]
    assert (
        client_agent(agent("accueil")).post(f"/api/gestion/usagers/comptes/{compte.pk}/valider", {}, format="json").status_code
        == 403
    )
    assert gestionnaire.post(f"/api/gestion/usagers/comptes/{compte.pk}/valider", {}, format="json").json()["statut"] == "actif"
    suspendu = gestionnaire.post(f"/api/gestion/usagers/comptes/{compte.pk}/suspendre", {"motif": "Impayés"}, format="json")
    assert suspendu.json()["statut"] == "suspendu"
    assert gestionnaire.post(f"/api/gestion/usagers/comptes/{compte.pk}/reactiver").json()["statut"] == "actif"
