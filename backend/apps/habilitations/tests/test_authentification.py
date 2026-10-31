"""SEC-02 (AD en LDAPS), ADM-06 (groupes → rôles), SEC-03 (double authentification), SEC-06 (limitation de débit)."""

from __future__ import annotations

import pyotp
import pytest
from ldap3 import MOCK_SYNC, Server

from apps.habilitations import ldap as module_ldap
from apps.habilitations.ldap import Annuaire, synchroniser_utilisateur
from apps.habilitations.models import GroupeAD, Habilitation, Role, Utilisateur
from apps.noyau.chiffrement import chiffrer
from tests.fabriques import SiteFabrique, agent, perimetre_sites, ville_entiere

pytestmark = pytest.mark.django_db

BASE = "dc=chatillon,dc=test"
DN_SERVICE = f"cn=svc-equipements,ou=services,{BASE}"
DN_ALICE = f"uid=adupont,ou=agents,{BASE}"
DN_GROUPE_GEST = f"cn=GG-Equipements-Gestionnaires,ou=groupes,{BASE}"
DN_GROUPE_ADMIN = f"cn=GG-Equipements-Admins,ou=groupes,{BASE}"

CONF = {
    "URI": "ldaps://annuaire-simule:636",
    "STARTTLS": False,
    "FICHIER_AC": "",
    "VERIFIER_CERTIFICAT": True,
    "COMPTE_SERVICE_DN": DN_SERVICE,
    "COMPTE_SERVICE_MOT_DE_PASSE": "service-test",
    "BASE_UTILISATEURS": f"ou=agents,{BASE}",
    "FILTRE_UTILISATEUR": "(&(objectClass=inetOrgPerson)(uid={identifiant}))",
    "BASE_GROUPES": f"ou=groupes,{BASE}",
    "MODE_GROUPES": "memberof",
    "ATTRIBUT_IDENTIFIANT": "uid",
    "ATTRIBUT_PRENOM": "givenName",
    "ATTRIBUT_NOM": "sn",
    "ATTRIBUT_COURRIEL": "mail",
    "ATTRIBUT_GROUPES": "memberOf",
    "DELAI_SECONDES": 2,
}


@pytest.fixture
def serveur_simule():
    serveur = Server("annuaire-simule")
    from ldap3 import Connection

    connexion = Connection(serveur, user=DN_SERVICE, password="service-test", client_strategy=MOCK_SYNC)
    connexion.strategy.add_entry(DN_SERVICE, {"objectClass": ["person"], "sn": "svc", "userPassword": "service-test"})
    connexion.strategy.add_entry(
        DN_ALICE,
        {
            "objectClass": ["inetOrgPerson"],
            "uid": "adupont",
            "givenName": "Alice",
            "sn": "Dupont",
            "mail": "alice.dupont@exemple.test",
            "userPassword": "Mot-de-passe-test-1",
            "memberOf": [DN_GROUPE_GEST],
        },
    )
    connexion.strategy.add_entry(DN_GROUPE_GEST, {"objectClass": ["groupOfNames"], "member": [DN_ALICE]})
    connexion.strategy.add_entry(DN_GROUPE_ADMIN, {"objectClass": ["groupOfNames"], "member": [DN_SERVICE]})
    return serveur


@pytest.fixture
def annuaire_simule(serveur_simule, monkeypatch):
    instance = Annuaire(configuration=CONF, serveur=serveur_simule, strategie=MOCK_SYNC)
    monkeypatch.setattr(module_ldap, "annuaire", lambda: instance)
    return instance


@pytest.fixture
def groupe_gestionnaires():
    site = SiteFabrique()
    return GroupeAD.objects.create(dn=DN_GROUPE_GEST, role=Role.objects.get(code="gestionnaire"), perimetre=perimetre_sites(site))


def test_sec02_authentification_reussie(annuaire_simule):
    entree = annuaire_simule.authentifier("adupont", "Mot-de-passe-test-1")
    assert entree is not None
    assert (entree.dn, entree.prenom, entree.nom, entree.courriel) == (DN_ALICE, "Alice", "Dupont", "alice.dupont@exemple.test")
    assert entree.groupes == [DN_GROUPE_GEST]


def test_sec02_mot_de_passe_faux_ou_compte_inconnu(annuaire_simule):
    assert annuaire_simule.authentifier("adupont", "mauvais") is None
    assert annuaire_simule.authentifier("inconnu", "Mot-de-passe-test-1") is None
    assert annuaire_simule.authentifier("adupont", "") is None


def test_sec02_injection_ldap_neutralisee(annuaire_simule):
    assert annuaire_simule.authentifier("*", "Mot-de-passe-test-1") is None
    assert annuaire_simule.authentifier("adupont)(uid=*", "Mot-de-passe-test-1") is None


def test_sec02_mode_recherche_des_groupes(serveur_simule):
    conf = {**CONF, "MODE_GROUPES": "recherche"}
    entree = Annuaire(configuration=conf, serveur=serveur_simule, strategie=MOCK_SYNC).authentifier(
        "adupont", "Mot-de-passe-test-1"
    )
    assert entree is not None and DN_GROUPE_GEST in entree.groupes


def test_sec02_mode_ad_imbriques_utilise_la_regle_de_chaine(serveur_simule):
    filtres: list[str] = []

    class ConnexionEspion:
        entries: list = []

        def search(self, base, filtre, **kwargs):
            filtres.append(filtre)

    conf = {**CONF, "MODE_GROUPES": "ad_imbriques"}
    Annuaire(configuration=conf).groupes(ConnexionEspion(), "CN=Dupont\\, Alice,OU=Agents,DC=x", [])  # type: ignore[arg-type]
    assert filtres == ["(member:1.2.840.113556.1.4.1941:=CN=Dupont\\5c, Alice,OU=Agents,DC=x)"]


def test_adm06_groupes_ad_donnent_les_roles(annuaire_simule, groupe_gestionnaires):
    utilisateur = synchroniser_utilisateur(annuaire_simule.authentifier("adupont", "Mot-de-passe-test-1"))
    assert utilisateur is not None and utilisateur.username == "adupont"
    assert [(h.role.code, h.source) for h in utilisateur.habilitations.all()] == [("gestionnaire", "ad")]


def test_adm06_retrait_du_groupe_retire_le_role(annuaire_simule, groupe_gestionnaires):
    entree = annuaire_simule.authentifier("adupont", "Mot-de-passe-test-1")
    utilisateur = synchroniser_utilisateur(entree)
    Habilitation.objects.create(utilisateur=utilisateur, role=Role.objects.get(code="accueil"), perimetre=ville_entiere())
    entree.groupes = []
    synchroniser_utilisateur(entree)
    assert list(utilisateur.habilitations.values_list("role__code", "source")) == [("accueil", "manuel")]


def test_sec02_agent_sans_groupe_correspondant_refuse(annuaire_simule):
    assert synchroniser_utilisateur(annuaire_simule.authentifier("adupont", "Mot-de-passe-test-1")) is None


def test_sec02_api_connexion_par_annuaire(annuaire_simule, groupe_gestionnaires, client_api):
    reponse = client_api.post(
        "/api/gestion/auth/connexion", {"identifiant": "adupont", "mot_de_passe": "Mot-de-passe-test-1"}, format="json"
    )
    assert reponse.status_code == 200
    assert reponse.json()["etape"] == "connecte"
    assert client_api.get("/api/gestion/moi").json()["identifiant"] == "adupont"


def test_sec02_api_message_identique_compte_inconnu_ou_mot_de_passe_faux(annuaire_simule, groupe_gestionnaires, client_api):
    faux = client_api.post("/api/gestion/auth/connexion", {"identifiant": "adupont", "mot_de_passe": "x"}, format="json")
    inconnu = client_api.post("/api/gestion/auth/connexion", {"identifiant": "personne", "mot_de_passe": "x"}, format="json")
    assert faux.status_code == inconnu.status_code == 400
    assert faux.json() == inconnu.json()


def test_sec02_annuaire_indisponible_refuse_sans_erreur(monkeypatch, client_api):
    class AnnuaireEnPanne:
        def authentifier(self, identifiant, mot_de_passe):
            raise module_ldap.AnnuaireIndisponible("délai dépassé")

    monkeypatch.setattr(module_ldap, "annuaire", AnnuaireEnPanne)
    reponse = client_api.post("/api/gestion/auth/connexion", {"identifiant": "a", "mot_de_passe": "b"}, format="json")
    assert reponse.status_code == 400


def test_sec06_limitation_de_debit_connexion(annuaire_simule, client_api, settings):
    taux = {**settings.REST_FRAMEWORK["DEFAULT_THROTTLE_RATES"], "connexion": "3/min"}
    settings.REST_FRAMEWORK = {**settings.REST_FRAMEWORK, "DEFAULT_THROTTLE_RATES": taux}
    codes = [
        client_api.post("/api/gestion/auth/connexion", {"identifiant": "adupont", "mot_de_passe": "x"}, format="json").status_code
        for _ in range(5)
    ]
    assert codes == [400, 400, 400, 429, 429]


# --- SEC-03 : double authentification ---------------------------------------------------------


def test_sec03_role_sensible_exige_l_enrolement(client_agent):
    admin = agent("administrateur")
    client = client_agent(admin, totp_valide=False)
    reponse = client.get("/api/gestion/admin/roles")
    assert reponse.status_code == 403
    assert reponse.json()["code"] == "double_authentification_requise"
    assert client.get("/api/gestion/moi").json()["double_authentification_exigee"] is True


def test_sec03_enrolement_puis_acces(client_agent):
    admin = agent("administrateur")
    client = client_agent(admin, totp_valide=False)
    enrolement = client.get("/api/gestion/auth/totp/enrolement").json()
    assert enrolement["uri"].startswith("otpauth://totp/") and "<svg" in enrolement["qr_svg"]
    code = pyotp.TOTP(enrolement["graine"]).now()
    assert client.post("/api/gestion/auth/totp/enrolement", {"code": code}, format="json").status_code == 200
    assert client.get("/api/gestion/admin/roles").status_code == 200
    admin.refresh_from_db()
    assert admin.totp_actif and enrolement["graine"] not in admin.totp_secret_chiffre


def test_sec03_code_faux_puis_juste_et_rejeu_refuse(client_agent):
    graine = pyotp.random_base32()
    regisseur = agent("regisseur", totp_actif=True, totp_secret_chiffre=chiffrer(graine))
    client = client_agent(regisseur, totp_valide=False)
    assert client.post("/api/gestion/auth/totp", {"code": "000000"}, format="json").status_code == 400
    code = pyotp.TOTP(graine).now()
    assert client.post("/api/gestion/auth/totp", {"code": code}, format="json").status_code == 200
    autre = client_agent(regisseur, totp_valide=False)
    assert autre.post("/api/gestion/auth/totp", {"code": code}, format="json").status_code == 400


def test_sec03_role_non_sensible_sans_double_authentification(client_agent):
    client = client_agent(agent("gestionnaire"), totp_valide=False)
    assert client.get("/api/gestion/referentiel/sites").status_code == 200


def test_sec03_connexion_annonce_l_etape_totp(annuaire_simule, client_api):
    GroupeAD.objects.create(dn=DN_GROUPE_GEST, role=Role.objects.get(code="regisseur"), perimetre=ville_entiere())
    reponse = client_api.post(
        "/api/gestion/auth/connexion", {"identifiant": "adupont", "mot_de_passe": "Mot-de-passe-test-1"}, format="json"
    )
    assert reponse.json() == {"etape": "enrolement_totp"}
    assert Utilisateur.objects.get(username="adupont").exige_double_authentification()


def test_sec03_administrateur_reinitialise_le_totp_d_un_agent(client_agent):
    cible = agent("regisseur", totp_actif=True, totp_secret_chiffre=chiffrer(pyotp.random_base32()))
    reponse = client_agent(agent("administrateur")).post(f"/api/gestion/admin/agents/{cible.pk}/reinitialiser-totp")
    assert reponse.status_code == 204
    cible.refresh_from_db()
    assert not cible.totp_actif and cible.totp_secret_chiffre == ""


def test_sec02_deconnexion(client_agent):
    client = client_agent(agent("gestionnaire"))
    assert client.post("/api/gestion/auth/deconnexion").status_code == 204
    assert client.get("/api/gestion/moi").status_code == 401
