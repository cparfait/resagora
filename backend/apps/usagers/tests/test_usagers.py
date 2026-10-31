"""USR-01 à USR-05 : usagers, contacts, pièces justificatives et alertes, historique."""

from __future__ import annotations

from datetime import date, timedelta

import pytest
from django.core.files.uploadedfile import SimpleUploadedFile
from django.utils import timezone

from apps.usagers.models import PieceJustificative, TypePiece, Usager
from apps.usagers.services import alertes_expiration, pieces_manquantes
from tests.fabriques import UsagerFabrique, agent, usager_avec_contact

pytestmark = pytest.mark.django_db
PDF = b"%PDF-1.7\n%%EOF"


@pytest.fixture(autouse=True)
def antivirus_sain(monkeypatch):
    from apps.noyau import fichiers

    monkeypatch.setattr(fichiers, "analyser_clamav", lambda contenu: "Eicar-Test-Signature" if b"EICAR" in contenu else None)


def test_usr01_fiche_usager_typee_et_residence(client_agent):
    client = client_agent(agent("gestionnaire"))
    reponse = client.post(
        "/api/gestion/usagers/usagers",
        {"type": "association", "nom": "Châtillon Basket", "commune": "CHATILLON", "rna": "w123456789", "local": True},
        format="json",
    )
    assert reponse.status_code == 201 and reponse.json()["resident"] is True and reponse.json()["rna"] == "W123456789"
    externe = client.post(
        "/api/gestion/usagers/usagers", {"type": "particulier", "nom": "Dominique Martin", "commune": "Bagneux"}, format="json"
    )
    assert externe.json()["resident"] is False
    assert (
        client.post("/api/gestion/usagers/usagers", {"type": "entreprise", "nom": "X", "siret": "123"}, format="json").status_code
        == 400
    )


def test_usr01_lecture_et_ecriture_selon_le_role(client_agent, client_api):
    usager = UsagerFabrique()
    assert client_api.get("/api/gestion/usagers/usagers").status_code == 401
    assert client_agent(agent("gardien")).get("/api/gestion/usagers/usagers").status_code == 403
    assert (
        client_agent(agent("elu_commission"))
        .patch(f"/api/gestion/usagers/usagers/{usager.pk}", {"nom": "X"}, format="json")
        .status_code
        == 403
    )
    assert (
        client_agent(agent("accueil"))
        .patch(f"/api/gestion/usagers/usagers/{usager.pk}", {"nom": "Club rebaptisé"}, format="json")
        .status_code
        == 200
    )


def test_usr02_contact_rattache_a_deux_associations(client_agent):
    client = client_agent(agent("gestionnaire"))
    contact = client.post(
        "/api/gestion/usagers/contacts",
        {"prenom": "Camille", "nom": "Bernard", "courriel": "camille@exemple.test"},
        format="json",
    ).json()
    for usager in (UsagerFabrique(), UsagerFabrique()):
        assert (
            client.post(
                "/api/gestion/usagers/rattachements",
                {"usager": usager.pk, "contact": contact["id"], "role": "tresorier"},
                format="json",
            ).status_code
            == 201
        )
    assert len(client.get(f"/api/gestion/usagers/contacts/{contact['id']}").json()["rattachements"]) == 2


def test_usr03_depot_verification_et_pieces_manquantes(client_agent):
    usager = usager_avec_contact()
    assurance = TypePiece.objects.get(code="assurance")
    client = client_agent(agent("gestionnaire"))
    assert assurance in pieces_manquantes(usager, date(2026, 11, 10))
    depot = client.post(
        "/api/gestion/usagers/pieces",
        {"usager": usager.pk, "type_piece": assurance.pk, "fichier": SimpleUploadedFile("assurance.pdf", PDF)},
        format="multipart",
    )
    assert depot.status_code == 201 and depot.json()["statut"] == "a_verifier"
    piece = depot.json()["id"]
    assert client.post(f"/api/gestion/usagers/pieces/{piece}/verifier", {"valide": False}, format="json").status_code == 400
    meme_agent = client.post(f"/api/gestion/usagers/pieces/{piece}/verifier", {"valide": True}, format="json")
    assert meme_agent.status_code == 409 and meme_agent.json()["code"] == "double_controle"
    assert (
        client_agent(agent("gestionnaire"))
        .post(f"/api/gestion/usagers/pieces/{piece}/verifier", {"valide": True, "valide_jusqu_au": "2027-09-01"}, format="json")
        .status_code
        == 200
    )
    assert assurance not in pieces_manquantes(usager, date(2026, 11, 10))
    assert assurance in pieces_manquantes(usager, date(2027, 9, 2))
    telechargement = client.get(f"/api/gestion/usagers/pieces/{piece}/fichier")
    assert telechargement.status_code == 200 and telechargement["Content-Disposition"].startswith("attachment")


def test_usr03_fichier_non_conforme_ou_infecte_refuse(client_agent):
    usager = usager_avec_contact()
    assurance = TypePiece.objects.get(code="assurance")
    client = client_agent(agent("gestionnaire"))
    exe = client.post(
        "/api/gestion/usagers/pieces",
        {"usager": usager.pk, "type_piece": assurance.pk, "fichier": SimpleUploadedFile("a.pdf", b"MZ\x90")},
        format="multipart",
    )
    assert exe.status_code == 400 and exe.json()["code"] == "format_refuse"
    virus = client.post(
        "/api/gestion/usagers/pieces",
        {"usager": usager.pk, "type_piece": assurance.pk, "fichier": SimpleUploadedFile("a.pdf", PDF + b"EICAR")},
        format="multipart",
    )
    assert virus.json()["code"] == "fichier_infecte"
    kbis = TypePiece.objects.get(code="kbis")
    assert (
        client.post(
            "/api/gestion/usagers/pieces",
            {"usager": usager.pk, "type_piece": kbis.pk, "fichier": SimpleUploadedFile("k.pdf", PDF)},
            format="multipart",
        ).status_code
        == 400
    )


def test_usr03_alerte_avant_expiration(client_agent):
    from apps.noyau.models import Fichier

    usager = usager_avec_contact()
    fichier = Fichier.objects.create(nom_origine="a.pdf", type_mime="application/pdf", taille=1, sha256="0" * 64, chemin="x/a")
    bientot = PieceJustificative.objects.create(
        usager=usager,
        type_piece=TypePiece.objects.get(code="assurance"),
        fichier=fichier,
        statut="valide",
        valide_jusqu_au=timezone.localdate() + timedelta(days=10),
    )
    PieceJustificative.objects.create(
        usager=usager,
        type_piece=TypePiece.objects.get(code="statuts"),
        fichier=fichier,
        statut="valide",
        valide_jusqu_au=timezone.localdate() + timedelta(days=300),
    )
    assert list(alertes_expiration()) == [bientot]
    assert [p["id"] for p in client_agent(agent("accueil")).get("/api/gestion/usagers/pieces/alertes").json()] == [bientot.pk]


def test_usr04_conventionnement_actif_selon_la_date():
    usager = UsagerFabrique(conventionne=True, convention_fin=date(2026, 12, 31))
    assert usager.convention_active(date(2026, 11, 1)) and not usager.convention_active(date(2027, 1, 1))


def test_usr05_historique_de_l_usager(client_agent):
    from apps.reservations.tests.outils import reserver
    from tests.fabriques import EspaceFabrique

    usager = usager_avec_contact()
    reserver(EspaceFabrique(), date(2026, 11, 10), "18:00", "20:00", usager=usager)
    historique = client_agent(agent("accueil")).get(f"/api/gestion/usagers/usagers/{usager.pk}/historique").json()
    assert historique["occurrences_total"] == 1 and len(historique["dossiers"]) == 1


def test_usr01_recherche_sans_accent():
    UsagerFabrique(nom="Étoile sportive de Châtillon")
    from apps.usagers.services import rechercher

    assert rechercher(Usager.objects.all(), "etoile").count() == 1
