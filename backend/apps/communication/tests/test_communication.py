"""COM-01 à COM-05, ADM-04 : notifications, messagerie, envois groupés, journal, préférences, SMS, modèles."""

from __future__ import annotations

import json
from datetime import date

import httpx
import pytest
from django.core import mail
from freezegun import freeze_time

from apps.communication import services, sms
from apps.communication.models import Message, ModeleMessage, Notification, PreferenceNotification
from apps.reservations import services as reservations
from apps.reservations.tests.outils import reserver, valider_systeme
from tests.fabriques import EspaceFabrique, SiteFabrique, agent, usager_avec_contact

pytestmark = pytest.mark.django_db


@pytest.fixture(autouse=True)
def maintenant():
    with freeze_time("2026-11-01 10:00"):
        yield


def test_com01_valider_une_demande_envoie_un_courriel(django_capture_on_commit_callbacks):
    espace = EspaceFabrique()
    r = reserver(espace, date(2026, 11, 20), "18:00", "20:00")
    with django_capture_on_commit_callbacks(execute=True):
        reservations.valider(r, acteur=agent("gestionnaire"))
    assert any("est validée" in m.subject for m in mail.outbox)
    assert Notification.objects.filter(modele__code="reservation_validee", statut="envoyee").exists()


def test_com01_gabarit_sans_acces_aux_secrets():
    modele = ModeleMessage.objects.get(code="reservation_validee")
    modele.corps = "{{ reservation.valide_par.totp_secret_chiffre }}|{{ reservation.dossier.usager }}|{{ dossier.numero }}"
    modele.save()
    r = reserver(EspaceFabrique(), date(2026, 11, 20), "18:00", "20:00")
    r.valide_par = agent("gestionnaire", totp_secret_chiffre="SECRET-NE-PAS-DIVULGUER")
    r.save()
    notification = services.notifier("reservation_validee", {"dossier": r.dossier, "reservation": r}, usager=r.dossier.usager)[0]
    assert "SECRET" not in notification.corps and r.dossier.numero in notification.corps


def test_com02_message_de_l_agent_prevenu_par_courriel(client_agent, django_capture_on_commit_callbacks):
    site = SiteFabrique()
    r = reserver(EspaceFabrique(batiment__site=site), date(2026, 11, 20), "18:00", "20:00")
    r.dossier.contact = r.dossier.usager.rattachements.first().contact
    r.dossier.save()
    with django_capture_on_commit_callbacks(execute=True):
        reponse = client_agent(agent("gestionnaire", site)).post(
            "/api/gestion/communication/messages",
            {"dossier": r.dossier_id, "corps": "Le gardien ouvrira à 17 h 30."},
            format="json",
        )
    assert reponse.status_code == 201
    assert any("Nouveau message" in m.subject for m in mail.outbox)
    autre_site = agent("gestionnaire", SiteFabrique())
    assert client_agent(autre_site).get("/api/gestion/communication/messages", {"dossier": r.dossier_id}).json()["results"] == []
    assert (
        client_agent(autre_site)
        .post("/api/gestion/communication/messages", {"dossier": r.dossier_id, "corps": "Intrusion"}, format="json")
        .status_code
        == 403
    )


def test_com02_messages_non_lus_puis_lus(client_agent):
    site = SiteFabrique()
    r = reserver(EspaceFabrique(batiment__site=site), date(2026, 11, 20), "18:00", "20:00")
    Message.objects.create(dossier=r.dossier, auteur_contact=r.dossier.usager.rattachements.first().contact, corps="Question")
    client = client_agent(agent("gestionnaire", site))
    assert client.get("/api/gestion/communication/messages/non-lus").json()[0]["nombre"] == 1
    client.get("/api/gestion/communication/messages", {"dossier": r.dossier_id})
    assert client.get("/api/gestion/communication/messages/non-lus").json() == []


def test_com03_notifier_tous_les_usagers_d_une_fermeture(client_agent, django_capture_on_commit_callbacks):
    site = SiteFabrique()
    espace = EspaceFabrique(batiment__site=site)
    for jour in (10, 12):
        valider_systeme(reserver(espace, date(2026, 11, jour), "18:00", "20:00"))
    with django_capture_on_commit_callbacks(execute=True):
        reponse = client_agent(agent("gestionnaire", site)).post(
            "/api/gestion/referentiel/fermetures",
            {
                "espace": espace.pk,
                "debut": "2026-11-09T00:00:00+01:00",
                "fin": "2026-11-13T00:00:00+01:00",
                "motif": "Dégât des eaux",
            },
            format="json",
        )
    assert reponse.status_code == 201
    assert len([m for m in mail.outbox if "Fermeture" in m.subject]) == 2


def test_com03_envoi_groupe_aux_occupants_et_preferences(client_agent, django_capture_on_commit_callbacks):
    site = SiteFabrique()
    espace = EspaceFabrique(batiment__site=site)
    occupants = [valider_systeme(reserver(espace, date(2026, 11, 10 + i), "18:00", "20:00")).dossier.usager for i in range(3)]
    refus = occupants[2].rattachements.first().contact
    PreferenceNotification.objects.create(contact=refus, informations=False)
    corps = {
        "titre": "Travaux de peinture",
        "texte": "Les vestiaires seront repeints.",
        "espace": espace.pk,
        "debut": "2026-11-09T00:00:00+01:00",
        "fin": "2026-11-20T00:00:00+01:00",
    }
    assert (
        client_agent(agent("accueil", site)).post("/api/gestion/communication/envois-groupes", corps, format="json").status_code
        == 403
    )
    with django_capture_on_commit_callbacks(execute=True):
        reponse = client_agent(agent("gestionnaire", site)).post(
            "/api/gestion/communication/envois-groupes", corps, format="json"
        )
    assert reponse.status_code == 201 and reponse.json()["usagers"] == 3
    assert len([m for m in mail.outbox if m.subject == "Travaux de peinture"]) == 2
    groupe = reponse.json()["groupe"]
    journal = client_agent(agent("gestionnaire", site)).get("/api/gestion/communication/envois", {"groupe": groupe}).json()
    assert journal["count"] == 2


def test_com04_journal_des_envois_et_lien_masque(client_agent):
    from apps.comptes.services import demander_reinitialisation
    from apps.portail.tests.outils import compte_actif

    compte = compte_actif()
    demander_reinitialisation(compte.identifiant)
    journal = (
        client_agent(agent("gestionnaire")).get("/api/gestion/communication/envois", {"recherche": compte.identifiant}).json()
    )
    assert journal["count"] == 1 and "jeton=" not in journal["results"][0]["corps"]
    assert client_agent(agent("gardien")).get("/api/gestion/communication/envois").status_code == 403


def test_com05_sms_par_l_adaptateur_http(monkeypatch, django_capture_on_commit_callbacks):
    recus = []

    def operateur(requete: httpx.Request) -> httpx.Response:
        recus.append((requete.headers["authorization"], json.loads(requete.content)))
        return httpx.Response(201, json={"identifiant": "SMS000001"})

    monkeypatch.setenv("SMS_ADAPTATEUR", "http")
    monkeypatch.setenv("SMS_URL", "https://sms.test/messages")
    monkeypatch.setenv("SMS_JETON", "jeton-test")
    transport = httpx.MockTransport(operateur)
    original = sms.envoyer_sms
    monkeypatch.setattr(
        services, "envoyer_sms", lambda numero, texte, reference: original(numero, texte, reference, transport=transport)
    )
    usager = usager_avec_contact()
    contact = usager.rattachements.first().contact
    PreferenceNotification.objects.create(contact=contact, sms=True, telephone_sms="06 12 34 56 78")
    espace = EspaceFabrique()
    valider_systeme(reserver(espace, date(2026, 11, 10), "18:00", "20:00", usager=usager))
    from datetime import datetime

    from apps.referentiel.models import Fermeture
    from apps.reservations.recurrence import PARIS

    fermeture = Fermeture.objects.create(
        espace=espace, debut=datetime(2026, 11, 9, tzinfo=PARIS), fin=datetime(2026, 11, 11, tzinfo=PARIS), motif="Travaux"
    )
    with django_capture_on_commit_callbacks(execute=True):
        reservations.enregistrer_fermeture(fermeture, acteur=agent("gestionnaire"))
    notification = Notification.objects.get(canal="sms")
    assert notification.statut == "envoyee"
    assert recus and recus[0][0] == "Bearer jeton-test" and recus[0][1]["destinataire"] == "+33612345678"


def test_com05_sms_desactive_par_defaut(monkeypatch):
    monkeypatch.delenv("SMS_ADAPTATEUR", raising=False)
    assert sms.envoyer_sms("0612345678", "Test", "N1").envoye is False
    assert sms.normaliser_mobile("01 23 45 67 89") is None


def test_adm04_modele_de_message_modifiable_et_apercu(client_agent):
    modele = ModeleMessage.objects.get(code="reservation_validee")
    administrateur = client_agent(agent("administrateur"))
    reponse = administrateur.patch(
        f"/api/gestion/communication/modeles/{modele.pk}",
        {"sujet": "Bonne nouvelle : {{ dossier.numero }} validé"},
        format="json",
    )
    assert reponse.status_code == 200
    assert (
        administrateur.post(f"/api/gestion/communication/modeles/{modele.pk}/apercu").json()["sujet"]
        == "Bonne nouvelle : D2026-00001 validé"
    )
    invalide = administrateur.patch(f"/api/gestion/communication/modeles/{modele.pk}", {"corps": "{% if %}"}, format="json")
    assert invalide.status_code == 400
    assert (
        client_agent(agent("gestionnaire"))
        .patch(f"/api/gestion/communication/modeles/{modele.pk}", {"sujet": "x"}, format="json")
        .status_code
        == 403
    )
