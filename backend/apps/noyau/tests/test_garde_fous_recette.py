"""Revue sécurité du lot 2 (M9) : un réglage de recette arrivé en production est détecté avant la mise en service."""

from __future__ import annotations

import pytest

from apps.communication import sms
from apps.noyau.management.commands.verifier_deploiement import controles_production


@pytest.fixture
def production(settings):
    settings.RECETTE = False
    settings.SIGNATURE_MODE = "docuseal"
    settings.DOCUSEAL_URL = "https://signature-interne.chatillon.local"
    settings.DOCUSEAL_URL_PUBLIQUE = "https://signature.chatillon.fr"
    settings.DOCUSEAL_VERIFIER_TLS = True
    settings.PORTAIL_URL = "https://equipements.chatillon.fr"
    settings.REST_FRAMEWORK = {**settings.REST_FRAMEWORK, "DEFAULT_THROTTLE_RATES": dict(settings.DEBITS_PAR_DEFAUT)}
    return settings


def test_sec06_configuration_de_production_conforme(production, monkeypatch):
    monkeypatch.setenv("SMS_ADAPTATEUR", "desactive")
    assert controles_production() == []


def test_sec06_reglages_de_recette_refuses_en_production(production, monkeypatch):
    production.REST_FRAMEWORK = {
        **production.REST_FRAMEWORK,
        "DEFAULT_THROTTLE_RATES": {**production.DEBITS_PAR_DEFAUT, "connexion": "500/min"},
    }
    production.DOCUSEAL_URL = "http://simulateurs:8090"
    production.DOCUSEAL_VERIFIER_TLS = False
    monkeypatch.setenv("SMS_ADAPTATEUR", "http")
    monkeypatch.setenv("SMS_URL", "http://simulateurs:8090/sms/messages")
    erreurs = " ".join(controles_production())
    assert "connexion" in erreurs and "DOCUSEAL_URL" in erreurs and "DOCUSEAL_VERIFIER_TLS" in erreurs and "SMS_URL" in erreurs


def test_sec06_recette_admet_les_simulateurs(settings):
    settings.RECETTE = True
    settings.DOCUSEAL_URL = "http://simulateurs:8090"
    assert controles_production() == []


def test_com05_jeton_sms_jamais_en_clair_hors_recette(settings, monkeypatch):
    settings.RECETTE = False
    monkeypatch.setenv("SMS_ADAPTATEUR", "http")
    monkeypatch.setenv("SMS_URL", "http://operateur.exemple.test/messages")
    with pytest.raises(sms.SmsIndisponible, match="HTTPS"):
        sms.envoyer_sms("0612345678", "Test", "N1")


def test_tar07_payfip_de_recette_refuse_en_production(production):
    production.PAYFIP_ACTIF = True
    production.PAYFIP_URL_SERVICE = "http://simulateurs:8090/payfip/services/securite"
    production.PAYFIP_URL_PAIEMENT = "http://localhost:53010/payfip/paiementws.web"
    production.PAYFIP_URL_NOTIFICATION = "https://equipements.chatillon.fr/api/portail/payfip/notification"
    production.PAYFIP_SAISIE = "T"
    production.PAYFIP_NUMCLI = ""
    production.PAYFIP_SECRET = ""
    erreurs = " ".join(controles_production())
    for attendu in ("PAYFIP_URL_SERVICE", "PAYFIP_URL_PAIEMENT", "PAYFIP_SAISIE", "PAYFIP_NUMCLI", "payfip_secret"):
        assert attendu in erreurs, attendu
    assert "PAYFIP_URL_NOTIFICATION" not in erreurs


def test_tar07_payfip_de_production_conforme(production, monkeypatch):
    monkeypatch.setenv("SMS_ADAPTATEUR", "desactive")
    production.PAYFIP_ACTIF = True
    production.PAYFIP_URL_SERVICE = "https://www.payfip.gouv.fr/tpa/services/securite"
    production.PAYFIP_URL_PAIEMENT = "https://www.payfip.gouv.fr/tpa/paiementws.web"
    production.PAYFIP_URL_NOTIFICATION = "https://equipements.chatillon.fr/api/portail/payfip/notification"
    production.PAYFIP_SAISIE = "W"
    production.PAYFIP_NUMCLI = "012345"
    production.PAYFIP_SECRET = "s" * 32
    production.PAYFIP_VERIFIER_TLS = True
    assert controles_production() == []
