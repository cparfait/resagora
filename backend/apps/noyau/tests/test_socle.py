"""SEC-01 (canaux), SEC-05 (en-têtes, CSRF, erreurs neutres), SEC-09 (secrets et journaux), montants en centimes."""

from __future__ import annotations

import logging

import pytest
from django.test import override_settings
from rest_framework.test import APIClient

from apps.noyau import secrets
from apps.noyau.journaux import FiltreDonneesSensibles, masquer
from apps.noyau.montants import appliquer_taux, centimes, euros, proratiser
from tests.fabriques import agent

pytestmark = pytest.mark.django_db


def test_sec01_canal_gestion_ne_sert_pas_le_portail(client_api):
    assert client_api.get("/api/portail/disponibilites").status_code == 404
    assert client_api.get("/sante").json() == {"etat": "ok"}


@override_settings(CANAL="portail", ROOT_URLCONF="config.urls_portail")
def test_sec01_canal_portail_ne_sert_pas_la_gestion(client_agent):
    client = client_agent(agent("administrateur"))
    assert client.get("/api/gestion/moi").status_code == 404
    assert client.get("/api/gestion/referentiel/sites").status_code == 404
    assert client.get("/api/schema/gestion").status_code == 404


@override_settings(CANAL="portail", ROOT_URLCONF="config.urls_portail", MOBILE_OPTION="A")
def test_sec10_option_a_api_mobile_absente_du_canal_portail(client_api):
    assert client_api.get("/api/mobile/paquet").status_code == 404


def test_sec05_entetes_de_securite(client_api):
    reponse = client_api.get("/sante")
    assert reponse["X-Content-Type-Options"] == "nosniff"
    assert reponse["Referrer-Policy"] == "same-origin"
    assert reponse["X-Frame-Options"] == "DENY"
    assert "camera=()" in reponse["Permissions-Policy"]
    csp = reponse["Content-Security-Policy"]
    assert "default-src 'self'" in csp and "unsafe-inline" not in csp and "frame-ancestors 'none'" in csp


def test_sec05_csrf_impose_sur_les_ecritures_de_session():
    utilisateur = agent("gestionnaire")
    client = APIClient(enforce_csrf_checks=True)
    client.force_login(utilisateur, backend="apps.habilitations.ldap.LdapBackend")
    reponse = client.post("/api/gestion/referentiel/sites", {"code": "x", "nom": "X"}, format="json")
    assert reponse.status_code == 403


def test_sec05_cors_ferme(client_api):
    reponse = client_api.get("/sante", HTTP_ORIGIN="https://site-tiers.example")
    assert "Access-Control-Allow-Origin" not in reponse


def test_sec05_erreur_neutre_sans_detail_technique(client_agent):
    reponse = client_agent(agent("gestionnaire")).get("/api/gestion/referentiel/espaces/999999")
    assert reponse.status_code == 404
    assert reponse.json() == {"code": "not_found", "message": "Élément introuvable."}


def test_sec09_secret_lu_dans_un_fichier(tmp_path, monkeypatch):
    fichier = tmp_path / "mon_secret"
    fichier.write_text("valeur-secrete\n", encoding="utf-8")
    monkeypatch.setenv("MON_SECRET_FICHIER", str(fichier))
    assert secrets.secret("mon_secret") == "valeur-secrete"


def test_sec09_secret_absent_en_production(monkeypatch, tmp_path):
    monkeypatch.setenv("ENVIRONNEMENT", "prod")
    monkeypatch.setattr(secrets, "DOSSIER_SECRETS", tmp_path)
    monkeypatch.setenv("SECRET_ABSENT", "ne-doit-pas-etre-lu")
    with pytest.raises(RuntimeError):
        secrets.secret("secret_absent")


def test_sec09_journaux_masquent_les_donnees_sensibles():
    assert masquer("connexion mot_de_passe=Azerty123 jeton: abc.def") == "connexion mot_de_passe=*** jeton: ***"
    enregistrement = logging.LogRecord("x", logging.INFO, "f", 1, "Authorization: Bearer abc", None, None)
    FiltreDonneesSensibles().filter(enregistrement)
    assert "abc" not in enregistrement.getMessage()


def test_montants_en_centimes():
    assert euros(123456) == "1 234,56 €"
    assert euros(-5) == "-0,05 €"
    assert centimes("12,345") == 1235
    assert centimes("1 000,10 €") == 100010
    assert appliquer_taux(1001, 5000) == 501
    assert proratiser(1000, 1, 3) == 333
    assert proratiser(1000, 1, 0) == 0
