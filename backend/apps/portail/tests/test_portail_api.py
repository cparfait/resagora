"""API du portail : disponibilités anonymisées (POR-02), demande en quatre étapes (POR-04), suivi (POR-05),
pièces (POR-06, SEC-07), messagerie (POR-08, COM-02), accès limité aux usagers du contact (R2-27)."""

from __future__ import annotations

from datetime import date

import pytest
from django.core import mail
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import override_settings
from freezegun import freeze_time

from apps.communication.models import Message
from apps.reservations.models import Campagne, Dossier, TypeReservation
from apps.reservations.tests.outils import reserver, valider_systeme
from apps.usagers.models import PieceJustificative, TypePiece
from tests.fabriques import EspaceFabrique, agent, saison_2026, usager_avec_contact

from .outils import client_contact, compte_actif

pytestmark = [pytest.mark.django_db, pytest.mark.urls("config.urls_portail")]
PDF = b"%PDF-1.7\n1 0 obj<<>>endobj\ntrailer<<>>\n%%EOF"


@pytest.fixture(autouse=True)
def maintenant():
    with freeze_time("2026-11-01 10:00"):
        yield


@pytest.fixture
def espace():
    return EspaceFabrique(nom="Gymnase des Écoles")


@override_settings(CANAL="portail")
def test_por02_disponibilites_publiques_sans_nom_d_usager(client_api, espace):
    usager = usager_avec_contact(nom="Club Secret de Volley")
    valider_systeme(reserver(espace, date(2026, 11, 10), "18:00", "20:00", usager=usager))
    reserver(espace, date(2026, 11, 11), "18:00", "20:00", usager=usager)
    reponse = client_api.get("/api/portail/disponibilites", {"espace": espace.pk, "debut": "2026-11-09", "jours": 7})
    assert reponse.status_code == 200
    assert "Club Secret" not in reponse.content.decode()
    assert {p["etat"] for p in reponse.json()["plages"]} == {"occupe", "demande"}
    assert len(reponse.json()["jours"]) == 7
    assert client_api.get("/api/portail/disponibilites", {"espace": espace.pk, "jours": 90}).status_code == 400


@override_settings(CANAL="portail")
def test_por04_demande_en_quatre_etapes_avec_brouillon(espace, django_capture_on_commit_callbacks):
    compte = compte_actif()
    usager = compte.contact.rattachements.first().usager
    client = client_contact(compte)
    ponctuelle = TypeReservation.objects.get(code="ponctuelle")
    creneau = {"espace": espace.pk, "date_debut": "2026-12-12", "heure_debut": "14:00", "heure_fin": "17:00"}
    cree = client.post(
        "/api/portail/dossiers", {"usager": usager.pk, "type_reservation": ponctuelle.pk, "creneaux": [creneau]}, format="json"
    )
    assert cree.status_code == 201, cree.json()
    dossier = cree.json()
    assert dossier["brouillon"] and dossier["creneaux"][0]["seances"] == 1 and dossier["creneaux"][0]["indisponibles"] == []
    assert Dossier.objects.get(pk=dossier["id"]).reservations.count() == 0
    trop_tot = client.post(f"/api/portail/dossiers/{dossier['id']}/envoyer")
    assert trop_tot.status_code == 400 and trop_tot.json()["code"] == "objet_requis"
    assert (
        client.patch(
            f"/api/portail/dossiers/{dossier['id']}",
            {"etape": 2, "objet": "Tournoi de fin d'année", "effectif": 60},
            format="json",
        ).status_code
        == 200
    )
    reprise = client_contact(compte).get(f"/api/portail/dossiers/{dossier['id']}").json()
    assert reprise["etape"] == 2 and reprise["objet"] == "Tournoi de fin d'année"
    with django_capture_on_commit_callbacks(execute=True):
        envoye = client.post(f"/api/portail/dossiers/{dossier['id']}/envoyer")
    assert envoye.status_code == 200 and not envoye.json()["brouillon"]
    assert envoye.json()["reservations"][0]["statut"] == "demande"
    assert any("bien été reçue" in m.subject for m in mail.outbox)
    assert client.patch(f"/api/portail/dossiers/{dossier['id']}", {"objet": "Autre"}, format="json").status_code == 409


@override_settings(CANAL="portail")
def test_por04_regles_du_guichet_appliquees_au_portail(espace):
    compte = compte_actif()
    usager = compte.contact.rattachements.first().usager
    client = client_contact(compte)
    ponctuelle = TypeReservation.objects.get(code="ponctuelle")
    proche = {"espace": espace.pk, "date_debut": "2026-11-03", "heure_debut": "14:00", "heure_fin": "17:00"}
    cree = client.post(
        "/api/portail/dossiers",
        {"usager": usager.pk, "type_reservation": ponctuelle.pk, "objet": "Match", "creneaux": [proche]},
        format="json",
    ).json()
    assert "jours à l'avance" in cree["creneaux"][0]["erreur"]
    refus = client.post(f"/api/portail/dossiers/{cree['id']}/envoyer")
    assert refus.status_code == 400 and refus.json()["code"] == "creneaux_invalides"
    prive = EspaceFabrique(nom="Local technique", reservable_portail=False)
    autre = client.post(
        "/api/portail/dossiers",
        {
            "usager": usager.pk,
            "type_reservation": ponctuelle.pk,
            "creneaux": [{**proche, "espace": prive.pk, "date_debut": "2026-12-12"}],
        },
        format="json",
    )
    assert autre.status_code == 400
    municipal = TypeReservation.objects.get(code="municipal")
    assert (
        client.post("/api/portail/dossiers", {"usager": usager.pk, "type_reservation": municipal.pk}, format="json").status_code
        == 400
    )


@override_settings(CANAL="portail")
def test_por05_suivi_et_annulation_par_l_usager(espace):
    compte = compte_actif()
    usager = compte.contact.rattachements.first().usager
    r = valider_systeme(reserver(espace, date(2026, 11, 3), "18:00", "20:00", usager=usager))
    client = client_contact(compte)
    liste = client.get("/api/portail/dossiers").json()
    assert [d["numero"] for d in liste] == [r.dossier.numero]
    detail = client.get(f"/api/portail/dossiers/{r.dossier_id}").json()
    seance = detail["reservations"][0]["seances"][0]
    assert seance["annulable"] and seance["annulation_tardive_si_annulee"]
    annulee = client.post(
        f"/api/portail/dossiers/{r.dossier_id}/occurrences/{seance['id']}/annuler", {"motif": "Match reporté"}, format="json"
    )
    assert annulee.status_code == 200 and annulee.json()["annulation_tardive"] is True


@override_settings(CANAL="portail")
def test_por05_un_autre_usager_ne_voit_pas_le_dossier(espace):
    r = valider_systeme(reserver(espace, date(2026, 11, 10), "18:00", "20:00"))
    intrus = client_contact(compte_actif())
    assert intrus.get(f"/api/portail/dossiers/{r.dossier_id}").status_code == 404
    assert intrus.get(f"/api/portail/dossiers/{r.dossier_id}/messages").status_code == 404
    assert intrus.post(f"/api/portail/dossiers/{r.dossier_id}/annuler", {"motif": "x"}, format="json").status_code == 404
    assert intrus.get(f"/api/portail/usagers/{r.dossier.usager_id}").status_code == 404
    assert intrus.get("/api/portail/pieces-exigees", {"usager": r.dossier.usager_id}).status_code == 404


@override_settings(CANAL="portail")
def test_por06_depot_d_une_attestation_depuis_le_portail():
    compte = compte_actif()
    usager = compte.contact.rattachements.first().usager
    client = client_contact(compte)
    assurance = TypePiece.objects.get(code="assurance")
    exigees = {p["libelle"]: p["etat"] for p in client.get("/api/portail/pieces-exigees", {"usager": usager.pk}).json()}
    assert exigees[assurance.libelle] == "manquante"
    depot = client.post(
        f"/api/portail/usagers/{usager.pk}/pieces",
        {"type_piece": assurance.pk, "fichier": SimpleUploadedFile("assurance.pdf", PDF, content_type="application/pdf")},
        format="multipart",
        HTTP_X_FICHIER_CONTROLE="clamav",
        HTTP_X_EMPREINTE_SHA256=__import__("hashlib").sha256(PDF).hexdigest(),
    )
    assert depot.status_code == 201, depot.json()
    piece = PieceJustificative.objects.get(pk=depot.json()["id"])
    assert piece.depose_par_portail and piece.fichier.controle_antivirus == "clamav-dmz"
    exigees = {p["libelle"]: p["etat"] for p in client.get("/api/portail/pieces-exigees", {"usager": usager.pk}).json()}
    assert exigees[assurance.libelle] == "a_verifier"
    telechargement = client.get(f"/api/portail/usagers/{usager.pk}/pieces/{piece.pk}/fichier")
    assert telechargement.status_code == 200 and "attachment" in telechargement["Content-Disposition"]
    assert client_contact(compte_actif()).get(f"/api/portail/usagers/{usager.pk}/pieces/{piece.pk}/fichier").status_code == 404


@override_settings(CANAL="portail")
def test_sec07_type_reel_verifie_et_empreinte_de_la_facade_controlee(monkeypatch):
    from apps.noyau import fichiers

    compte = compte_actif()
    usager = compte.contact.rattachements.first().usager
    client = client_contact(compte)
    assurance = TypePiece.objects.get(code="assurance")
    deguise = client.post(
        f"/api/portail/usagers/{usager.pk}/pieces",
        {
            "type_piece": assurance.pk,
            "fichier": SimpleUploadedFile("assurance.pdf", b"MZ\x90\x00 executable", content_type="application/pdf"),
        },
        format="multipart",
        HTTP_X_FICHIER_CONTROLE="clamav",
    )
    assert deguise.status_code == 400 and deguise.json()["code"] == "format_refuse"
    analyses = []
    monkeypatch.setattr(fichiers, "analyser_clamav", lambda contenu: analyses.append(contenu) or "Eicar-Signature")
    falsifie = client.post(
        f"/api/portail/usagers/{usager.pk}/pieces",
        {"type_piece": assurance.pk, "fichier": SimpleUploadedFile("assurance.pdf", PDF, content_type="application/pdf")},
        format="multipart",
        HTTP_X_FICHIER_CONTROLE="clamav",
        HTTP_X_EMPREINTE_SHA256="0" * 64,
    )
    assert analyses and falsifie.status_code == 400 and falsifie.json()["code"] == "fichier_infecte"


@override_settings(CANAL="portail")
def test_por08_message_sur_un_dossier_et_reponse_de_la_ville(espace, django_capture_on_commit_callbacks):
    compte = compte_actif()
    usager = compte.contact.rattachements.first().usager
    r = reserver(espace, date(2026, 12, 10), "18:00", "20:00", usager=usager)
    client = client_contact(compte)
    with django_capture_on_commit_callbacks(execute=True):
        envoye = client.post(
            f"/api/portail/dossiers/{r.dossier_id}/messages", {"corps": "Pouvons-nous arriver à 17 h 45 ?"}, format="json"
        )
    assert envoye.status_code == 201
    assert any("dossier" in m.subject.lower() and "equipements@chatillon.test" in m.to for m in mail.outbox)
    Message.objects.create(dossier=r.dossier, auteur_agent=agent("gestionnaire"), corps="Oui, le gardien ouvre à 17 h 30.")
    fil = client.get(f"/api/portail/dossiers/{r.dossier_id}/messages").json()
    assert [m["de_la_ville"] for m in fil] == [False, True] and fil[1]["auteur"] == "Service des équipements"
    assert client.get("/api/portail/dossiers").json()[0]["messages_non_lus"] == 0


@override_settings(CANAL="portail")
def test_pla05_demande_de_creneaux_dans_une_campagne_ouverte(espace):
    saison = saison_2026()
    campagne = Campagne.objects.create(
        saison=saison, nom="Créneaux 2027-2028", ouverture=date(2026, 10, 1), cloture=date(2026, 11, 30), statut="ouverte"
    )
    compte = compte_actif()
    usager = compte.contact.rattachements.first().usager
    client = client_contact(compte)
    assert [c["nom"] for c in client.get("/api/portail/campagnes").json()] == ["Créneaux 2027-2028"]
    cree = client.post(
        f"/api/portail/campagnes/{campagne.pk}/demandes", {"usager": usager.pk, "objet": "Entraînements"}, format="json"
    )
    assert cree.status_code == 201 and cree.json()["type_libelle"].startswith("Créneau annuel")
    Campagne.objects.filter(pk=campagne.pk).update(statut="instruction")
    assert client.post(f"/api/portail/campagnes/{campagne.pk}/demandes", {"usager": usager.pk}, format="json").status_code == 404


@override_settings(CANAL="portail")
def test_por01_contact_principal_ajoute_et_invite_un_contact(django_capture_on_commit_callbacks):
    compte = compte_actif()
    usager = compte.contact.rattachements.first().usager
    with django_capture_on_commit_callbacks(execute=True):
        ajout = client_contact(compte).post(
            f"/api/portail/usagers/{usager.pk}/contacts",
            {"prenom": "Alex", "nom": "Martin", "courriel": "alex.martin@exemple.test", "role": "tresorier"},
            format="json",
        )
    assert ajout.status_code == 201
    assert any("invité" in m.subject for m in mail.outbox)
    second = usager.rattachements.get(contact__courriel="alex.martin@exemple.test")
    from apps.comptes.models import CompteUsager

    invite = CompteUsager.objects.get(contact=second.contact)
    invite.statut = "actif"
    invite.save()
    refus = client_contact(invite).post(
        f"/api/portail/usagers/{usager.pk}/contacts", {"prenom": "X", "nom": "Y", "courriel": "x.y@exemple.test"}, format="json"
    )
    assert refus.status_code == 403


@override_settings(CANAL="portail")
def test_por09_declaration_d_accessibilite_publiee(client_api):
    declaration = client_api.get("/api/portail/accessibilite").json()
    assert declaration["referentiel"] == "RGAA 4.1.2" and declaration["etat"] == "non conforme"
