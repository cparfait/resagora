"""POR-01 : inscription et validation par la Ville ; SEC-04 : mots de passe, verrouillage, TOTP, liens uniques."""

from __future__ import annotations

import re
import time

import pyotp
import pytest
from django.core import mail
from django.test import override_settings
from freezegun import freeze_time

from apps.communication.models import Notification
from apps.comptes import services
from apps.comptes.models import CompteUsager, JetonPortail
from apps.noyau.chiffrement import dechiffrer
from apps.noyau.exceptions import AccesRefuse, ErreurValidation
from apps.usagers.models import Usager
from tests.fabriques import UsagerFabrique, agent

from .outils import MOT_DE_PASSE, client_contact, compte_actif

pytestmark = [pytest.mark.django_db, pytest.mark.urls("config.urls_portail")]
INSCRIPTION = {
    "contact": {"prenom": "Camille", "nom": "Rivière", "courriel": "camille.riviere@exemple.test", "telephone": "0600000001"},
    "usager": {
        "type": "association",
        "nom": "Badminton des Coteaux",
        "adresse": "1 rue du Parc",
        "code_postal": "92320",
        "commune": "Châtillon",
    },
    "mot_de_passe": "Volant-Plume-Raquette-7",
    "consentement": True,
}


def _lien(corps: str, chemin: str) -> str:
    trouve = re.search(rf"/{chemin}\?jeton=([\w-]+)", corps)
    assert trouve, corps
    return trouve.group(1)


@override_settings(CANAL="portail", PASSWORD_HASHERS=["django.contrib.auth.hashers.Argon2PasswordHasher"])
def test_por01_inscription_confirmation_puis_validation_par_la_ville(client_api, django_capture_on_commit_callbacks):
    with django_capture_on_commit_callbacks(execute=True):
        reponse = client_api.post("/api/portail/auth/inscription", INSCRIPTION, format="json")
    assert reponse.status_code == 202
    compte = CompteUsager.objects.get(identifiant="camille.riviere@exemple.test")
    assert compte.statut == "a_confirmer" and compte.mot_de_passe.startswith("argon2")
    assert Usager.objects.get(nom="Badminton des Coteaux").statut == "en_attente"
    notification = Notification.objects.get(modele__code="compte_confirmation")
    assert "masqué" in notification.corps and "jeton=" not in notification.corps and notification.corps_secret == ""
    premier = _lien(mail.outbox[-1].body, "confirmation")
    with django_capture_on_commit_callbacks(execute=True):
        relance = client_api.post(
            "/api/portail/auth/connexion",
            {"identifiant": compte.identifiant, "mot_de_passe": INSCRIPTION["mot_de_passe"]},
            format="json",
        )
    assert relance.json()["code"] == "compte_a_confirmer"
    jeton = _lien(mail.outbox[-1].body, "confirmation")
    assert jeton != premier
    assert client_api.post("/api/portail/auth/confirmation-courriel", {"jeton": premier}, format="json").status_code == 400
    assert client_api.post("/api/portail/auth/confirmation-courriel", {"jeton": jeton}, format="json").status_code == 200
    assert client_api.post("/api/portail/auth/confirmation-courriel", {"jeton": jeton}, format="json").status_code == 400
    compte.refresh_from_db()
    assert compte.statut == "a_valider"
    attente = client_api.post(
        "/api/portail/auth/connexion",
        {"identifiant": compte.identifiant, "mot_de_passe": INSCRIPTION["mot_de_passe"]},
        format="json",
    )
    assert attente.status_code == 403 and attente.json()["code"] == "compte_a_valider"
    with pytest.raises(AccesRefuse):
        services.valider_compte(compte, acteur=agent("accueil"))
    services.valider_compte(compte, acteur=agent("gestionnaire"))
    assert Usager.objects.get(nom="Badminton des Coteaux").statut == "valide"
    ouverte = client_api.post(
        "/api/portail/auth/connexion",
        {"identifiant": "Camille.Riviere@exemple.test", "mot_de_passe": INSCRIPTION["mot_de_passe"]},
        format="json",
    )
    assert ouverte.status_code == 200 and ouverte.json()["jeton"] and ouverte.json()["contact"]["prenom"] == "Camille"


@override_settings(CANAL="portail")
def test_por01_validation_avec_rattachement_a_un_usager_connu(client_api):
    client_api.post("/api/portail/auth/inscription", INSCRIPTION, format="json")
    compte = CompteUsager.objects.get(identifiant="camille.riviere@exemple.test")
    connu = UsagerFabrique(nom="Badminton des Coteaux (déjà connu)")
    services.valider_compte(compte, acteur=agent("gestionnaire"), usager_existant=connu)
    assert not Usager.objects.filter(nom="Badminton des Coteaux").exists()
    assert connu.rattachements.filter(contact=compte.contact).exists()


@override_settings(CANAL="portail")
def test_sec04_pas_d_enumeration_des_comptes(client_api, django_capture_on_commit_callbacks):
    compte = compte_actif()
    inconnu = client_api.post(
        "/api/portail/auth/connexion", {"identifiant": "personne@exemple.test", "mot_de_passe": "x" * 12}, format="json"
    )
    mauvais = client_api.post(
        "/api/portail/auth/connexion", {"identifiant": compte.identifiant, "mot_de_passe": "x" * 12}, format="json"
    )
    assert inconnu.status_code == mauvais.status_code == 401
    assert inconnu.json()["message"] == mauvais.json()["message"]
    oubli_connu = client_api.post("/api/portail/auth/mot-de-passe-oublie", {"identifiant": compte.identifiant}, format="json")
    oubli_inconnu = client_api.post(
        "/api/portail/auth/mot-de-passe-oublie", {"identifiant": "personne@exemple.test"}, format="json"
    )
    assert oubli_connu.status_code == oubli_inconnu.status_code == 202 and oubli_connu.json() == oubli_inconnu.json()
    with django_capture_on_commit_callbacks(execute=True):
        double = client_api.post(
            "/api/portail/auth/inscription",
            {**INSCRIPTION, "contact": {**INSCRIPTION["contact"], "courriel": compte.identifiant}},
            format="json",
        )
    assert double.status_code == 202 and "déjà un compte" in mail.outbox[-1].body
    assert CompteUsager.objects.filter(identifiant=compte.identifiant).count() == 1


@override_settings(CANAL="portail")
def test_sec04_cinq_echecs_puis_attente_imposee_meme_message_compte_connu_ou_non(client_api, settings):
    settings.REST_FRAMEWORK = {
        **settings.REST_FRAMEWORK,
        "DEFAULT_THROTTLE_RATES": {**settings.REST_FRAMEWORK["DEFAULT_THROTTLE_RATES"], "connexion": "1000/min"},
    }
    compte = compte_actif()
    with freeze_time("2026-11-01 10:00"):
        for identifiant in (compte.identifiant, "inconnu@exemple.test"):
            reponses = [
                client_api.post(
                    "/api/portail/auth/connexion", {"identifiant": identifiant, "mot_de_passe": "Mauvais-Mot-2026"}, format="json"
                )
                for _ in range(5)
            ]
            assert [r.status_code for r in reponses] == [401, 401, 401, 401, 429]
            bloque = client_api.post(
                "/api/portail/auth/connexion", {"identifiant": identifiant, "mot_de_passe": MOT_DE_PASSE}, format="json"
            )
            assert bloque.status_code == 429 and "Réessayez dans 1 minute" in bloque.json()["message"]
    with freeze_time("2026-11-01 10:02"):
        assert (
            client_api.post(
                "/api/portail/auth/connexion", {"identifiant": compte.identifiant, "mot_de_passe": MOT_DE_PASSE}, format="json"
            ).status_code
            == 200
        )


def test_sec04_politique_de_mot_de_passe_anssi():
    for faible in ("court1!", "motdepasse123", "123456789012", "camilleriviere2026"):
        with pytest.raises(ErreurValidation):
            services.verifier_politique(faible, identifiant="camille.riviere@exemple.test", prenom="Camille", nom="Riviere")
    services.verifier_politique("Volant-Plume-Raquette-7")
    services.verifier_politique("une phrase de passe assez longue")


@override_settings(CANAL="portail")
def test_sec04_reinitialisation_a_usage_unique_ferme_les_sessions(client_api, django_capture_on_commit_callbacks):
    compte = compte_actif()
    services.ouvrir_session(compte)
    with django_capture_on_commit_callbacks(execute=True):
        client_api.post("/api/portail/auth/mot-de-passe-oublie", {"identifiant": compte.identifiant}, format="json")
    jeton = _lien(mail.outbox[-1].body, "reinitialisation")
    faible = client_api.post("/api/portail/auth/reinitialisation", {"jeton": jeton, "mot_de_passe": "faible"}, format="json")
    assert faible.status_code == 400
    assert (
        client_api.post(
            "/api/portail/auth/reinitialisation", {"jeton": jeton, "mot_de_passe": "Nouveau-Filet-Smash-9"}, format="json"
        ).status_code
        == 200
    )
    assert (
        client_api.post(
            "/api/portail/auth/reinitialisation", {"jeton": jeton, "mot_de_passe": "Encore-Autre-Smash-9"}, format="json"
        ).status_code
        == 400
    )
    assert not JetonPortail.objects.filter(compte=compte, revoque_le__isnull=True).exists()


@override_settings(CANAL="portail")
def test_sec04_lien_de_reinitialisation_expire(client_api, django_capture_on_commit_callbacks):
    compte = compte_actif()
    with freeze_time("2026-11-01 10:00"), django_capture_on_commit_callbacks(execute=True):
        client_api.post("/api/portail/auth/mot-de-passe-oublie", {"identifiant": compte.identifiant}, format="json")
    jeton = _lien(mail.outbox[-1].body, "reinitialisation")
    with freeze_time("2026-11-01 10:31"):
        assert (
            client_api.post(
                "/api/portail/auth/reinitialisation", {"jeton": jeton, "mot_de_passe": "Nouveau-Filet-Smash-9"}, format="json"
            ).status_code
            == 400
        )


@override_settings(CANAL="portail")
def test_sec04_double_authentification_proposee_et_exigee(client_api):
    compte = compte_actif()
    client = client_contact(compte)
    enrolement = client.get("/api/portail/compte/totp").json()
    assert enrolement["actif"] is False and "<svg" in enrolement["qr_svg"]
    graine = dechiffrer(CompteUsager.objects.get(pk=compte.pk).totp_en_attente_chiffre)
    assert client.post("/api/portail/compte/totp", {"code": pyotp.TOTP(graine).now()}, format="json").status_code == 200
    etape = client_api.post(
        "/api/portail/auth/connexion", {"identifiant": compte.identifiant, "mot_de_passe": MOT_DE_PASSE}, format="json"
    ).json()
    assert etape["etape"] == "totp" and "jeton" not in etape
    assert client_api.post("/api/portail/auth/totp", {"defi": etape["defi"], "code": "000000"}, format="json").status_code == 401
    code = pyotp.TOTP(graine).at(time.time() + 30)
    reponse = client_api.post("/api/portail/auth/totp", {"defi": etape["defi"], "code": code}, format="json")
    assert reponse.status_code == 200 and reponse.json()["jeton"]
    assert client_api.post("/api/portail/auth/totp", {"defi": etape["defi"], "code": code}, format="json").status_code == 401


@override_settings(CANAL="portail")
def test_sec04_jeton_revoque_a_la_deconnexion_et_refuse_hors_canal(client_api):
    compte = compte_actif()
    client = client_contact(compte)
    assert client.get("/api/portail/compte").status_code == 200
    assert client.post("/api/portail/auth/deconnexion").status_code == 204
    assert client.get("/api/portail/compte").status_code == 401
    assert client_api.get("/api/portail/compte").status_code in {401, 403}


@override_settings(CANAL="gestion")
def test_sec04_api_portail_refusee_sur_le_canal_de_gestion():
    compte = compte_actif()
    assert client_contact(compte).get("/api/portail/compte").status_code in {403, 404}


@override_settings(CANAL="portail")
def test_usr06_export_des_donnees_du_contact():
    compte = compte_actif()
    reponse = client_contact(compte).get("/api/portail/compte/export")
    assert reponse.status_code == 200 and "attachment" in reponse["Content-Disposition"]
    donnees = reponse.json()
    assert donnees["contact"]["courriel"] == compte.identifiant and donnees["structures"]
    assert "mot_de_passe" not in reponse.content.decode()
