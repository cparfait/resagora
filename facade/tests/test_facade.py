"""Façade DMZ : SEC-01, SEC-05, SEC-06, SEC-07, SEC-10, SIG-02, TAR-07."""

from __future__ import annotations

import json
from dataclasses import replace
from pathlib import Path

import httpx
import pytest
from starlette.testclient import TestClient

from facade.app import creer_application
from facade.config import Configuration
from facade.sessions import MagasinMemoire

ORIGINE = "https://equipements.chatillon.test"
PDF = b"%PDF-1.7\n1 0 obj<<>>endobj\ntrailer<<>>\n%%EOF"
PNG = b"\x89PNG\r\n\x1a\n" + b"\x00" * 32
EICAR = b"X5O!P%@AP[4\\PZX54(P^)7CC)7}$EICAR-STANDARD-ANTIVIRUS-TEST-FILE!$H+H*"


class AnalyseurFactice:
    def analyser(self, chemin: Path) -> str | None:
        return "Eicar-Signature" if b"EICAR" in chemin.read_bytes() else None


class ApiFactice:
    def __init__(self) -> None:
        self.requetes: list[httpx.Request] = []

    def __call__(self, requete: httpx.Request) -> httpx.Response:
        self.requetes.append(requete)
        chemin = requete.url.path
        if chemin == "/api/portail/auth/connexion":
            corps = json.loads(requete.content)
            if corps.get("mot_de_passe") == "bon":
                return httpx.Response(
                    200, json={"etape": "connecte", "jeton": "JETON-SECRET-API", "contact": {"id": 7, "nom": "Durand"}}
                )
            return httpx.Response(
                400, json={"code": "identifiants_invalides", "message": "Identifiant ou mot de passe incorrect."}
            )
        if chemin == "/api/portail/auth/deconnexion":
            return httpx.Response(204)
        return httpx.Response(200, json={"chemin": chemin, "autorisation": requete.headers.get("authorization")})


@pytest.fixture
def api() -> ApiFactice:
    return ApiFactice()


@pytest.fixture
def config(tmp_path) -> Configuration:
    return Configuration(
        api_url="https://api-portail:8443",
        origine=ORIGINE,
        dossier_quarantaine=tmp_path / "quarantaine",
        secret_webhook_docuseal="secret-webhook-test",
        taille_max_fichier=1024 * 1024,
        ips_payfip=["203.0.113.10"],
    )


def client(config: Configuration, api: ApiFactice, **autres) -> TestClient:
    application = creer_application(
        config, magasin=MagasinMemoire(), transport=httpx.MockTransport(api), analyseur=AnalyseurFactice(), **autres
    )
    return TestClient(application, base_url="https://equipements.chatillon.test", headers={"X-Forwarded-For": "198.51.100.7"})


def connecter(c: TestClient) -> str:
    csrf = c.get("/api/portail/session").json()["csrf"]
    reponse = c.post(
        "/api/portail/auth/connexion",
        json={"identifiant": "a@exemple.test", "mot_de_passe": "bon"},
        headers={"X-CSRF-Token": csrf, "Origin": ORIGINE},
    )
    assert reponse.status_code == 200
    return reponse.json()["csrf"]


def test_sec01_route_hors_liste_blanche_404(config, api):
    c = client(config, api)
    for chemin in [
        "/api/gestion/moi",
        "/admin/",
        "/api/portail/../gestion/moi",
        "/api/portail/dossiers/1;drop",
        "/api/schema/gestion",
    ]:
        assert c.get(chemin).status_code == 404, chemin
    assert c.delete("/api/portail/catalogue/espaces/1").status_code == 404
    assert api.requetes == []


def test_sec01_route_publique_relayee_sans_cookie_ni_autorisation_client(config, api):
    c = client(config, api)
    reponse = c.get("/api/portail/catalogue/espaces?famille=2", headers={"Authorization": "Bearer usurpe", "Cookie": "x=y"})
    assert reponse.status_code == 200
    requete = api.requetes[-1]
    assert requete.url.path == "/api/portail/catalogue/espaces" and requete.url.params["famille"] == "2"
    assert "authorization" not in requete.headers and "cookie" not in requete.headers
    assert requete.headers["x-forwarded-for"] == "198.51.100.7"


def test_sec05_entetes_de_securite(config, api):
    reponse = client(config, api).get("/api/portail/catalogue/sites")
    assert reponse.headers["strict-transport-security"].startswith("max-age=31536000")
    assert reponse.headers["x-content-type-options"] == "nosniff"
    assert "frame-ancestors 'none'" in reponse.headers["content-security-policy"]
    assert reponse.headers["cache-control"] == "no-store"


def test_sec04_connexion_jeton_api_jamais_expose(config, api):
    c = client(config, api)
    csrf = c.get("/api/portail/session").json()["csrf"]
    reponse = c.post(
        "/api/portail/auth/connexion",
        json={"identifiant": "a", "mot_de_passe": "bon"},
        headers={"X-CSRF-Token": csrf, "Origin": ORIGINE},
    )
    assert "JETON-SECRET-API" not in reponse.text
    assert "__Host-portail" in reponse.headers["set-cookie"] and "HttpOnly" in reponse.headers["set-cookie"]
    assert c.get("/api/portail/dossiers").json()["autorisation"] == "Portail JETON-SECRET-API"


def test_sec04_route_protegee_sans_session_401(config, api):
    assert client(config, api).get("/api/portail/dossiers").status_code == 401


def test_sec05_csrf_et_origine_imposes(config, api):
    c = client(config, api)
    nouveau_csrf = connecter(c)
    corps = {"objet": "Tournoi"}
    assert c.post("/api/portail/dossiers", json=corps, headers={"Origin": ORIGINE}).status_code == 403
    assert (
        c.post(
            "/api/portail/dossiers", json=corps, headers={"X-CSRF-Token": nouveau_csrf, "Origin": "https://pirate.example"}
        ).status_code
        == 403
    )
    assert (
        c.post("/api/portail/dossiers", json=corps, headers={"X-CSRF-Token": nouveau_csrf, "Origin": ORIGINE}).status_code == 200
    )


def test_sec04_deconnexion_detruit_la_session(config, api):
    c = client(config, api)
    csrf = connecter(c)
    assert c.post("/api/portail/auth/deconnexion", headers={"X-CSRF-Token": csrf, "Origin": ORIGINE}).status_code == 204
    assert c.get("/api/portail/dossiers").status_code == 401


def test_sec04_prolongation_de_session(config, api):
    c = client(config, api)
    csrf = connecter(c)
    reponse = c.post("/api/portail/session/prolonger", headers={"X-CSRF-Token": csrf, "Origin": ORIGINE})
    assert reponse.status_code == 200 and reponse.json()["expire_dans"] > 0


def test_sec06_limitation_de_debit_connexion(config, api):
    c = client(config, api)
    csrf = c.get("/api/portail/session").json()["csrf"]
    codes = [
        c.post(
            "/api/portail/auth/connexion",
            json={"identifiant": "a", "mot_de_passe": "faux"},
            headers={"X-CSRF-Token": csrf, "Origin": ORIGINE},
        ).status_code
        for _ in range(12)
    ]
    assert codes[:10] == [400] * 10 and codes[10:] == [429, 429]


def test_sec06_facteur_de_debit_de_recette(config, api):
    """FACTEUR_DEBIT élargit les seuils pour les parcours automatisés (1 par défaut en production)."""

    c = client(replace(config, facteur_debit=2, environnement="recette"), api)
    csrf = c.get("/api/portail/session").json()["csrf"]
    codes = [
        c.post(
            "/api/portail/auth/connexion",
            json={"identifiant": "a", "mot_de_passe": "faux"},
            headers={"X-CSRF-Token": csrf, "Origin": ORIGINE},
        ).status_code
        for _ in range(21)
    ]
    assert codes[:20] == [400] * 20 and codes[20] == 429
    assert Configuration().facteur_debit == 1


def test_sec06_corps_trop_volumineux(config, api):
    c = client(config, api)
    csrf = connecter(c)
    reponse = c.post(
        "/api/portail/dossiers",
        content=b"{" + b" " * 300_000 + b"}",
        headers={"X-CSRF-Token": csrf, "Origin": ORIGINE, "Content-Type": "application/json"},
    )
    assert reponse.status_code == 413


def televerser(c: TestClient, csrf: str, nom: str, contenu: bytes) -> httpx.Response:
    return c.post(
        "/api/portail/usagers/3/pieces",
        data={"type_piece": "assurance"},
        files={"fichier": (nom, contenu)},
        headers={"X-CSRF-Token": csrf, "Origin": ORIGINE},
    )


def test_sec07_fichier_pdf_controle_et_relaye_avec_empreinte(config, api):
    c = client(config, api)
    csrf = connecter(c)
    assert televerser(c, csrf, "attestation.pdf", PDF).status_code == 200
    requete = api.requetes[-1]
    assert requete.headers["x-fichier-controle"] == "clamav" and len(requete.headers["x-empreinte-sha256"]) == 64
    assert b"type_piece" in requete.content and b"%PDF-" in requete.content
    assert list((config.dossier_quarantaine).glob("*")) == []


def test_sec07_type_reel_et_extension_verifies(config, api):
    c = client(config, api)
    csrf = connecter(c)
    assert televerser(c, csrf, "photo.pdf", PNG).json()["code"] == "format_refuse"
    assert televerser(c, csrf, "script.exe", b"MZ\x90\x00").json()["code"] == "format_refuse"
    assert televerser(c, csrf, "faux.png", b"<?php echo 1; ?>").json()["code"] == "format_refuse"
    assert televerser(c, csrf, "plan.png", PNG).status_code == 200


def test_sec07_fichier_infecte_rejete(config, api):
    c = client(config, api)
    csrf = connecter(c)
    nombre = len(api.requetes)
    reponse = televerser(c, csrf, "virus.pdf", b"%PDF-1.4 " + EICAR)
    assert reponse.status_code == 422 and reponse.json()["code"] == "fichier_infecte"
    assert len(api.requetes) == nombre
    # Le fichier de test EICAR brut (sans en-tête PDF) est identifié comme infecté, pas seulement « format refusé ».
    brut = televerser(c, csrf, "attestation.pdf", EICAR)
    assert brut.status_code == 422 and brut.json()["code"] == "fichier_infecte"


def test_sec07_fichier_trop_gros(config, api):
    c = client(config, api)
    csrf = connecter(c)
    assert televerser(c, csrf, "gros.pdf", PDF + b"0" * (2 * 1024 * 1024)).status_code == 413


def test_sig02_webhook_docuseal_secret_verifie(config, api):
    c = client(config, api)
    assert c.post("/api/portail/webhooks/docuseal", json={"event_type": "form.completed"}).status_code == 401
    assert c.post("/api/portail/webhooks/docuseal", json={}, headers={"X-Docuseal-Secret": "faux"}).status_code == 401
    assert (
        c.post(
            "/api/portail/webhooks/docuseal",
            json={"event_type": "form.completed"},
            headers={"X-Docuseal-Secret": "secret-webhook-test"},
        ).status_code
        == 200
    )


def test_tar07_notification_payfip_filtree_par_adresse(config, api):
    c = client(config, api)
    assert c.post("/api/portail/payfip/notification", content=b"idop=ABC").status_code == 403
    autorise = c.post("/api/portail/payfip/notification", content=b"idop=ABC", headers={"X-Forwarded-For": "203.0.113.10"})
    assert autorise.status_code == 200 and api.requetes[-1].content == b"idop=ABC"


def test_sec10_api_mobile_absente_en_option_a(config, api):
    assert client(config, api).get("/api/mobile/paquet").status_code == 404


def test_sec10_option_b_exige_le_certificat_d_appareil(config, api):
    config.mobile_option = "B"
    c = client(config, api)
    assert c.get("/api/mobile/paquet").status_code == 403
    reponse = c.get(
        "/api/mobile/paquet",
        headers={"X-Forwarded-Tls-Client-Cert-Info": 'Subject="CN=appareil-12"', "Authorization": "Appareil abc"},
    )
    assert reponse.status_code == 200
    assert api.requetes[-1].headers["x-certificat-appareil"] == 'Subject="CN=appareil-12"'
    assert api.requetes[-1].headers["authorization"] == "Appareil abc"


def test_sec01_api_injoignable_message_neutre(config):
    def panne(requete: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("refus", request=requete)

    application = creer_application(
        config, magasin=MagasinMemoire(), transport=httpx.MockTransport(panne), analyseur=AnalyseurFactice()
    )
    reponse = TestClient(application).get("/api/portail/catalogue/sites")
    assert reponse.status_code == 503 and "momentanément" in reponse.json()["message"]


def appel_brut(application, methode: str, chemin_brut: bytes) -> int:
    """Appel ASGI direct avec un chemin non normalisé (le client HTTP de test normalise les « .. »)."""
    import asyncio

    statut = {}

    async def recevoir():
        return {"type": "http.request", "body": b"", "more_body": False}

    async def envoyer(message):
        if message["type"] == "http.response.start":
            statut["code"] = message["status"]

    from urllib.parse import unquote

    portee = {
        "type": "http",
        "asgi": {"version": "3.0"},
        "http_version": "1.1",
        "method": methode,
        "scheme": "https",
        "path": unquote(chemin_brut.decode("latin-1")),
        "raw_path": chemin_brut,
        "query_string": b"",
        "root_path": "",
        "headers": [(b"host", b"equipements.chatillon.test")],
        "client": ("198.51.100.7", 1234),
        "server": ("facade", 8080),
    }
    asyncio.run(application(portee, recevoir, envoyer))
    return statut["code"]


def test_sec01_chemins_encodes_et_methodes_hors_liste_refuses(config, api):
    application = creer_application(
        config, magasin=MagasinMemoire(), transport=httpx.MockTransport(api), analyseur=AnalyseurFactice()
    )
    for chemin in [
        b"/api/portail/%2e%2e/gestion/moi",
        b"/api/portail/..%2fgestion/moi",
        b"//api/portail/catalogue/sites",
        b"/api/portail/catalogue/sites%0A",
        "/api/portail/catalogue/espaces/١".encode(),
        b"/api/portail/catalogue/sites%3F",
    ]:
        assert appel_brut(application, "GET", chemin) == 404, chemin
    for methode in ["HEAD", "OPTIONS", "PUT", "TRACE"]:
        assert appel_brut(application, methode, b"/api/portail/catalogue/sites") == 404, methode
    assert api.requetes == []


def test_sec01_adresse_client_prise_au_dernier_proxy(config, api):
    c = client(config, api)
    c.get("/api/portail/catalogue/sites", headers={"X-Forwarded-For": "1.2.3.4, 5.6.7.8"})
    assert api.requetes[-1].headers["x-forwarded-for"] == "5.6.7.8"


def test_sec06_debit_compte_par_prefixe_ipv6(config, api):
    from facade.app import Facade

    assert Facade.cle_debit("2001:db8:1:2:aaaa::1") == Facade.cle_debit("2001:db8:1:2:bbbb::2") == "2001:db8:1:2::/64"
    assert Facade.cle_debit("198.51.100.7") == "198.51.100.7"


def test_sec05_identifiant_de_requete_genere_par_la_facade(config, api):
    client(config, api).get("/api/portail/catalogue/sites", headers={"X-Request-Id": "injecte\nfaux"})
    assert len(api.requetes[-1].headers["x-request-id"]) == 32 and "injecte" not in api.requetes[-1].headers["x-request-id"]


def test_sec05_longueur_de_contenu_invalide(config, api):
    application = creer_application(
        config, magasin=MagasinMemoire(), transport=httpx.MockTransport(api), analyseur=AnalyseurFactice()
    )
    reponse = TestClient(application).post("/api/portail/simulation-tarif", headers={"Content-Length": "abc"}, content=b"")
    assert reponse.status_code in {400, 413}


def test_tar07_notification_payfip_refusee_si_aucune_adresse_configuree(config, api):
    config.ips_payfip = []
    assert (
        client(config, api)
        .post("/api/portail/payfip/notification", content=b"idop=ABC", headers={"X-Forwarded-For": "203.0.113.10"})
        .status_code
        == 403
    )


def test_sec04_nouvelle_connexion_detruit_l_ancienne_session(config, api):
    c = client(config, api)
    connecter(c)
    ancien = c.cookies.get("__Host-portail")
    connecter(c)
    facade = c.app.state.facade
    assert facade.sessions.lire(ancien) is None


@pytest.mark.parametrize("reglage", [{"facteur_debit": 50}, {"payfip_sans_filtre_ip": True}, {"cookies_securises": False}])
def test_reglages_de_recette_refuses_en_production(config, reglage):
    """Revue sécurité du lot 2 (M9) : un réglage de recette arrivé en production empêche le démarrage."""
    with pytest.raises(RuntimeError, match="recette"):
        creer_application(replace(config, environnement="production", **reglage))
