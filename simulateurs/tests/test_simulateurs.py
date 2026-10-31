"""Les simulateurs reproduisent fidèlement les protocoles utilisés par la plateforme (COM-05, SIG-01 à SIG-04, TAR-07)."""

from __future__ import annotations

import base64

import pytest
from starlette.testclient import TestClient

from simulateurs.app import SOUMISSIONS, creer_application
from simulateurs.pdf import pdf_texte

JETON = "jeton-de-recette"


@pytest.fixture
def client(monkeypatch):
    monkeypatch.setenv("SIMULATEUR_RECETTE", "1")
    monkeypatch.setenv("SIMULATEUR_SMS_JETON", JETON)
    monkeypatch.setenv("SIMULATEUR_DOCUSEAL_JETON", JETON)
    monkeypatch.setenv("SIMULATEUR_PAYFIP_NUMCLI", "012345")
    monkeypatch.delenv("SIMULATEUR_DOCUSEAL_WEBHOOK_URL", raising=False)
    SOUMISSIONS.clear()
    return TestClient(creer_application())


def test_com05_sms_recu_avec_jeton(client):
    assert client.post("/sms/messages", json={"destinataire": "+33612345678", "texte": "Rappel"}).status_code == 401
    reponse = client.post(
        "/sms/messages",
        json={"destinataire": "+33612345678", "texte": "Rappel", "reference": "N1"},
        headers={"Authorization": f"Bearer {JETON}"},
    )
    assert reponse.status_code == 201 and reponse.json()["identifiant"].startswith("SMS")
    assert client.get("/sms.json").json()[0]["texte"] == "Rappel"


def test_sig01_signataires_ordonnes_puis_documents_et_purge(client):
    pdf = pdf_texte(["Convention d'occupation"])
    creation = client.post(
        "/api/submissions/pdf",
        headers={"X-Auth-Token": JETON},
        json={
            "name": "Convention 2026",
            "documents": [{"name": "convention.pdf", "file": base64.b64encode(pdf).decode()}],
            "submitters": [
                {"role": "Usager", "email": "a@exemple.test", "name": "A"},
                {"role": "Élu", "email": "b@exemple.test", "name": "B"},
            ],
            "order": "preserved",
        },
    )
    assert creation.status_code == 200
    soumission = creation.json()
    usager, elu = soumission["submitters"]
    assert "En attente" in client.get(f"/s/{elu['slug']}").text
    assert client.post(f"/s/{elu['slug']}", data={"accord": "1"}, follow_redirects=False).status_code == 303
    assert (
        client.get(f"/api/submissions/{soumission['id']}", headers={"X-Auth-Token": JETON}).json()["submitters"][1]["status"]
        != "completed"
    )
    client.get(f"/s/{usager['slug']}")
    client.post(f"/s/{usager['slug']}", data={"accord": "1"})
    client.post(f"/s/{elu['slug']}", data={"accord": "1"})
    etat = client.get(f"/api/submissions/{soumission['id']}", headers={"X-Auth-Token": JETON}).json()
    assert etat["status"] == "completed" and etat["documents"]
    signe = client.get(etat["documents"][0]["url"].replace("http://localhost:53010", ""))
    preuve = client.get(etat["audit_log_url"].replace("http://localhost:53010", ""))
    assert signe.content.startswith(b"%PDF-") and preuve.content.startswith(b"%PDF-")
    assert client.delete(f"/api/submissions/{soumission['id']}", headers={"X-Auth-Token": JETON}).status_code == 200
    assert client.get(f"/api/submissions/{soumission['id']}", headers={"X-Auth-Token": JETON}).status_code == 404


def test_sig04_expiration(client):
    pdf = pdf_texte(["Contrat"])
    soumission = client.post(
        "/api/submissions/pdf",
        headers={"X-Auth-Token": JETON},
        json={
            "documents": [{"name": "c.pdf", "file": base64.b64encode(pdf).decode()}],
            "submitters": [{"email": "a@exemple.test"}],
        },
    ).json()
    client.post(f"/simulateur/submissions/{soumission['id']}/expirer", headers={"X-Auth-Token": JETON})
    assert client.get(f"/api/submissions/{soumission['id']}", headers={"X-Auth-Token": JETON}).json()["status"] == "expired"


def test_tar07_payfip_creation_paiement_et_detail(client):
    creation = client.post(
        "/payfip/services/securite",
        content=(
            "<Envelope><Body><creerPaiementSecurise><arg0><exer>2026</exer><mel>a@exemple.test</mel><montant>12550</montant>"
            "<numcli>012345</numcli><objet>Location</objet><refdet>F2026-00001</refdet><saisie>T</saisie>"
            "<urlnotif>http://api.test/notif</urlnotif><urlredirect>http://portail.test/retour</urlredirect></arg0>"
            "</creerPaiementSecurise></Body></Envelope>"
        ),
    )
    assert creation.status_code == 200
    id_op = creation.text.split("<idOp>")[1].split("</idOp>")[0]
    assert "125,50 €" in client.get("/payfip/paiementws.web", params={"idop": id_op}).text
    retour = client.post(f"/payfip/paiementws.web?idop={id_op}", data={"resultat": "P"}, follow_redirects=False)
    assert retour.status_code == 303 and retour.headers["location"].endswith(f"idop={id_op}")
    detail = client.post(
        "/payfip/services/securite",
        content=f"<recupererDetailPaiementSecurise><idOp>{id_op}</idOp></recupererDetailPaiementSecurise>",
    )
    assert "<resultrans>P</resultrans>" in detail.text and "<montant>12550</montant>" in detail.text
    inconnu = client.post("/payfip/services/securite", content=creation.request.content.decode().replace("012345", "999999"))
    assert inconnu.status_code == 500 and "P1" in inconnu.text


def test_refuse_de_demarrer_hors_recette(monkeypatch):
    monkeypatch.delenv("SIMULATEUR_RECETTE", raising=False)
    with pytest.raises(RuntimeError, match="SIMULATEUR_RECETTE"):
        creer_application()
