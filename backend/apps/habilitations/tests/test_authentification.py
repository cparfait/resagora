"""SEC-02 (AD en LDAPS), ADM-06 (groupes → rôles), SEC-03 (double authentification), SEC-06 (limitation de débit)."""

from __future__ import annotations

import uuid
from pathlib import Path

import pyotp
import pytest
from rest_framework.test import APIClient

from apps.habilitations import ldap as module_ldap
from apps.habilitations import totp
from apps.habilitations.ldap import Annuaire, AnnuaireIndisponible, EntreeAnnuaire, echapper, synchroniser_utilisateur
from apps.habilitations.models import GroupeAD, Habilitation, Role, Utilisateur
from apps.noyau.chiffrement import chiffrer
from tests import faux_ldap
from tests.fabriques import SiteFabrique, UtilisateurFabrique, agent, perimetre_sites, ville_entiere

pytestmark = pytest.mark.django_db

BASE = "dc=chatillon,dc=test"
DN_SERVICE = f"cn=svc-equipements,ou=services,{BASE}"
DN_ALICE = f"uid=adupont,ou=agents,{BASE}"
DN_GROUPE_GEST = f"cn=GG-Equipements-Gestionnaires,ou=groupes,{BASE}"
GUID_ALICE = str(uuid.UUID(int=1))


@pytest.fixture
def conf(tmp_path: Path) -> dict[str, object]:
    ac = tmp_path / "ac.pem"
    ac.write_text("certificat de test", encoding="utf-8")
    return {
        "URI": "ldaps://annuaire-simule:636",
        "STARTTLS": False,
        "FICHIER_AC": str(ac),
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
        "ATTRIBUT_GUID": "entryUUID",
        "DELAI_SECONDES": 2,
    }


@pytest.fixture
def repertoire() -> faux_ldap.Repertoire:
    r = faux_ldap.Repertoire()
    r.ajouter(DN_SERVICE, "service-test", objectClass=["person"])
    r.ajouter(
        DN_ALICE,
        "Mot-de-passe-test-1",
        objectClass=["inetOrgPerson"],
        uid=["adupont"],
        givenName=["Alice"],
        sn=["Dupont"],
        mail=["alice.dupont@exemple.test"],
        memberOf=[DN_GROUPE_GEST],
        entryUUID=[GUID_ALICE],
    )
    r.ajouter(DN_GROUPE_GEST, objectClass=["groupOfNames"], member=[DN_ALICE])
    return r


@pytest.fixture
def annuaire_simule(conf, repertoire, monkeypatch) -> Annuaire:
    module = faux_ldap.ModuleLdap(repertoire)
    monkeypatch.setattr(module_ldap, "_ldap", lambda: module)
    instance = Annuaire(configuration=conf)
    monkeypatch.setattr(module_ldap, "annuaire", lambda: instance)
    return instance


@pytest.fixture
def groupe_gestionnaires() -> GroupeAD:
    return GroupeAD.objects.create(
        dn=DN_GROUPE_GEST, role=Role.objects.get(code="gestionnaire"), perimetre=perimetre_sites(SiteFabrique())
    )


def test_sec02_authentification_reussie_et_tls_verifie(annuaire_simule, repertoire):
    entree = annuaire_simule.authentifier("adupont", "Mot-de-passe-test-1")
    assert entree is not None
    assert (entree.dn, entree.prenom, entree.nom, entree.courriel, entree.guid) == (
        DN_ALICE,
        "Alice",
        "Dupont",
        "alice.dupont@exemple.test",
        GUID_ALICE,
    )
    assert entree.groupes == [DN_GROUPE_GEST]
    module = faux_ldap.ModuleLdap
    assert repertoire.options[module.OPT_X_TLS_REQUIRE_CERT] == module.OPT_X_TLS_DEMAND
    assert repertoire.options[module.OPT_REFERRALS] == 0


def test_sec02_mot_de_passe_faux_ou_compte_inconnu(annuaire_simule):
    assert annuaire_simule.authentifier("adupont", "mauvais") is None
    assert annuaire_simule.authentifier("inconnu", "Mot-de-passe-test-1") is None
    assert annuaire_simule.authentifier("adupont", "") is None


def test_sec02_injection_ldap_neutralisee(annuaire_simule, repertoire):
    assert annuaire_simule.authentifier("*", "Mot-de-passe-test-1") is None
    assert annuaire_simule.authentifier("adupont)(uid=*", "Mot-de-passe-test-1") is None
    assert echapper("a*b(c)\\") == "a\\2ab\\28c\\29\\5c"
    assert all("*" not in f.split("objectClass")[1] for f in repertoire.filtres if "uid=" in f)


def test_sec02_certificat_de_l_annuaire_obligatoire(conf, annuaire_simule):
    conf["FICHIER_AC"] = "/inexistant/ac.pem"
    with pytest.raises(AnnuaireIndisponible):
        annuaire_simule.authentifier("adupont", "Mot-de-passe-test-1")


def test_sec02_mode_recherche_des_groupes(conf, annuaire_simule):
    conf["MODE_GROUPES"] = "recherche"
    entree = annuaire_simule.authentifier("adupont", "Mot-de-passe-test-1")
    assert entree is not None and DN_GROUPE_GEST in entree.groupes


def test_sec02_mode_ad_imbriques_utilise_la_regle_de_chaine(conf, annuaire_simule, repertoire):
    conf["MODE_GROUPES"] = "ad_imbriques"
    annuaire_simule.authentifier("adupont", "Mot-de-passe-test-1")
    assert f"(member:1.2.840.113556.1.4.1941:={DN_ALICE})" in repertoire.filtres


def test_sec02_annuaire_en_panne(annuaire_simule, repertoire):
    repertoire.panne = True
    with pytest.raises(AnnuaireIndisponible):
        annuaire_simule.authentifier("adupont", "Mot-de-passe-test-1")


def test_adm06_groupes_ad_donnent_les_roles(annuaire_simule, groupe_gestionnaires):
    utilisateur = synchroniser_utilisateur(annuaire_simule.authentifier("adupont", "Mot-de-passe-test-1"))
    assert utilisateur is not None and utilisateur.username == "adupont" and utilisateur.identifiant_annuaire == GUID_ALICE
    assert [(h.role.code, h.source) for h in utilisateur.habilitations.all()] == [("gestionnaire", "ad")]


def test_adm06_retrait_du_groupe_retire_le_role(annuaire_simule, groupe_gestionnaires):
    entree = annuaire_simule.authentifier("adupont", "Mot-de-passe-test-1")
    utilisateur = synchroniser_utilisateur(entree)
    Habilitation.objects.create(utilisateur=utilisateur, role=Role.objects.get(code="accueil"), perimetre=ville_entiere())
    entree.groupes = []
    synchroniser_utilisateur(entree)
    assert list(utilisateur.habilitations.values_list("role__code", "source")) == [("accueil", "manuel")]


def test_adm06_modifier_le_groupe_s_applique_tout_de_suite(annuaire_simule, groupe_gestionnaires):
    utilisateur = synchroniser_utilisateur(annuaire_simule.authentifier("adupont", "Mot-de-passe-test-1"))
    groupe_gestionnaires.role = Role.objects.get(code="accueil")
    groupe_gestionnaires.save()
    assert list(utilisateur.habilitations.values_list("role__code", flat=True)) == ["accueil"]
    groupe_gestionnaires.actif = False
    groupe_gestionnaires.save()
    assert not utilisateur.habilitations.exists()


def test_adm06_cumul_incompatible_par_groupes_refuse(annuaire_simule):
    GroupeAD.objects.create(dn=DN_GROUPE_GEST, role=Role.objects.get(code="regisseur"), perimetre=ville_entiere())
    GroupeAD.objects.create(
        dn="cn=autre,ou=groupes,dc=chatillon,dc=test", role=Role.objects.get(code="gestionnaire"), perimetre=ville_entiere()
    )
    entree = annuaire_simule.authentifier("adupont", "Mot-de-passe-test-1")
    entree.groupes = [DN_GROUPE_GEST, "cn=autre,ou=groupes,dc=chatillon,dc=test"]
    utilisateur = synchroniser_utilisateur(entree)
    assert utilisateur is not None and utilisateur.habilitations.count() == 1


def test_sec02_agent_sans_groupe_correspondant_refuse(annuaire_simule):
    assert synchroniser_utilisateur(annuaire_simule.authentifier("adupont", "Mot-de-passe-test-1")) is None


def test_sec02_nom_de_compte_reattribue_ne_recupere_pas_les_droits(groupe_gestionnaires):
    ancien = agent("administrateur", username="jdupont", identifiant_annuaire=str(uuid.UUID(int=99)))
    nouveau = EntreeAnnuaire(
        dn="uid=jdupont,ou=agents,dc=x", identifiant="jdupont", guid=str(uuid.UUID(int=100)), groupes=[DN_GROUPE_GEST]
    )
    assert synchroniser_utilisateur(nouveau) is None
    assert ancien.habilitations.get().role.code == "administrateur"


def test_sec02_compte_local_jamais_fusionne_avec_l_annuaire(groupe_gestionnaires):
    UtilisateurFabrique(username="technique", source="local")
    entree = EntreeAnnuaire(
        dn="uid=technique,dc=x", identifiant="technique", guid=str(uuid.UUID(int=7)), groupes=[DN_GROUPE_GEST]
    )
    assert synchroniser_utilisateur(entree) is None


def test_sec02_entree_sans_identifiant_immuable_refusee(groupe_gestionnaires):
    assert synchroniser_utilisateur(EntreeAnnuaire(dn="uid=x,dc=x", identifiant="x", guid="", groupes=[DN_GROUPE_GEST])) is None


def test_sec02_api_connexion_par_annuaire(annuaire_simule, groupe_gestionnaires, client_api):
    reponse = client_api.post(
        "/api/gestion/auth/connexion", {"identifiant": "adupont", "mot_de_passe": "Mot-de-passe-test-1"}, format="json"
    )
    assert reponse.status_code == 200 and reponse.json()["etape"] == "connecte"
    assert client_api.get("/api/gestion/moi").json()["identifiant"] == "adupont"


def test_sec02_api_message_identique_et_saisie_non_conservee(annuaire_simule, groupe_gestionnaires, client_api):
    from apps.audit.models import JournalAudit

    faux = client_api.post("/api/gestion/auth/connexion", {"identifiant": "adupont", "mot_de_passe": "x"}, format="json")
    inconnu = client_api.post(
        "/api/gestion/auth/connexion", {"identifiant": "MonMotDePasse!", "mot_de_passe": "x"}, format="json"
    )
    assert faux.status_code == inconnu.status_code == 400 and faux.json() == inconnu.json()
    assert "MonMotDePasse" not in str(list(JournalAudit.objects.values_list("apres", flat=True)))


def test_sec02_connexion_exige_le_jeton_csrf(annuaire_simule, groupe_gestionnaires):
    client = APIClient(enforce_csrf_checks=True)
    reponse = client.post(
        "/api/gestion/auth/connexion", {"identifiant": "adupont", "mot_de_passe": "Mot-de-passe-test-1"}, format="json"
    )
    assert reponse.status_code == 403
    client.get("/api/gestion/auth/csrf")
    jeton = client.cookies["__Host-csrf-agent"].value
    reponse = client.post(
        "/api/gestion/auth/connexion",
        {"identifiant": "adupont", "mot_de_passe": "Mot-de-passe-test-1"},
        format="json",
        HTTP_X_CSRFTOKEN=jeton,
    )
    assert reponse.status_code == 200


def test_sec02_annuaire_indisponible_refuse_sans_erreur(monkeypatch, client_api):
    class AnnuaireEnPanne:
        def authentifier(self, identifiant, mot_de_passe):
            raise module_ldap.AnnuaireIndisponible("délai dépassé")

    monkeypatch.setattr(module_ldap, "annuaire", AnnuaireEnPanne)
    assert (
        client_api.post("/api/gestion/auth/connexion", {"identifiant": "a", "mot_de_passe": "b"}, format="json").status_code
        == 400
    )


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
    client = client_agent(agent("administrateur"), totp_valide=False)
    reponse = client.get("/api/gestion/admin/roles")
    assert reponse.status_code == 403 and reponse.json()["code"] == "double_authentification_requise"
    assert client.get("/api/gestion/moi").json()["double_authentification_exigee"] is True


def test_sec03_enrolement_puis_acces(client_agent):
    admin = agent("administrateur")
    client = client_agent(admin, totp_valide=False)
    enrolement = client.get("/api/gestion/auth/totp/enrolement").json()
    assert enrolement["uri"].startswith("otpauth://totp/") and "<svg" in enrolement["qr_svg"]
    assert enrolement["graine"] not in str(dict(client.session))
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


def test_sec03_verrouillage_apres_echecs_repetes(client_agent, settings):
    settings.TOTP_ECHECS_MAX = 3
    graine = pyotp.random_base32()
    regisseur = agent("regisseur", totp_actif=True, totp_secret_chiffre=chiffrer(graine))
    client = client_agent(regisseur, totp_valide=False)
    codes = [client.post("/api/gestion/auth/totp", {"code": "000000"}, format="json").status_code for _ in range(3)]
    assert codes == [400, 400, 403]
    assert client.get("/api/gestion/moi").status_code == 401
    assert totp.secondes_verrou(regisseur) > 0
    autre = client_agent(regisseur, totp_valide=False)
    reponse = autre.post("/api/gestion/auth/totp", {"code": pyotp.TOTP(graine).now()}, format="json")
    assert reponse.status_code == 403 and reponse.json()["code"] == "compte_verrouille"


def test_sec03_role_non_sensible_sans_double_authentification(client_agent):
    assert client_agent(agent("accueil"), totp_valide=False).get("/api/gestion/referentiel/sites").status_code == 200


def test_sec03_un_role_sensible_ne_peut_pas_renoncer_a_la_double_authentification(client_agent):
    client = client_agent(agent("administrateur"))
    regisseur = Role.objects.get(code="regisseur")
    reponse = client.patch(f"/api/gestion/admin/roles/{regisseur.pk}", {"double_authentification": False}, format="json")
    assert reponse.status_code == 400
    creation = client.post(
        "/api/gestion/admin/roles", {"code": "caisse", "libelle": "Caisse", "actions": ["encaisser"]}, format="json"
    )
    assert creation.status_code == 201 and Role.objects.get(code="caisse").double_authentification is True


def test_sec03_connexion_annonce_l_etape_totp(annuaire_simule, client_api):
    GroupeAD.objects.create(dn=DN_GROUPE_GEST, role=Role.objects.get(code="regisseur"), perimetre=ville_entiere())
    reponse = client_api.post(
        "/api/gestion/auth/connexion", {"identifiant": "adupont", "mot_de_passe": "Mot-de-passe-test-1"}, format="json"
    )
    assert reponse.json() == {"etape": "enrolement_totp"}
    assert Utilisateur.objects.get(username="adupont").exige_double_authentification()


def test_sec03_reinitialisation_exige_le_code_remis_par_l_administrateur(client_agent):
    graine = pyotp.random_base32()
    cible = agent("regisseur", totp_actif=True, totp_secret_chiffre=chiffrer(graine))
    session_cible = client_agent(cible)
    reponse = client_agent(agent("administrateur")).post(f"/api/gestion/admin/agents/{cible.pk}/reinitialiser-totp")
    assert reponse.status_code == 200
    jeton = reponse.json()["jeton_enrolement"]
    assert len(jeton) == 8
    assert session_cible.get("/api/gestion/moi").status_code == 401
    client = client_agent(cible, totp_valide=False)
    assert client.get("/api/gestion/auth/totp/enrolement").json()["code"] == "jeton_requis"
    mauvais = "12345678" if jeton != "12345678" else "87654321"
    assert client.post("/api/gestion/auth/totp/jeton", {"jeton": mauvais}, format="json").status_code == 400
    assert client.post("/api/gestion/auth/totp/jeton", {"jeton": jeton}, format="json").json() == {"etape": "enrolement_totp"}
    enrolement = client.get("/api/gestion/auth/totp/enrolement").json()
    assert (
        client.post(
            "/api/gestion/auth/totp/enrolement", {"code": pyotp.TOTP(enrolement["graine"]).now()}, format="json"
        ).status_code
        == 200
    )
    cible.refresh_from_db()
    assert cible.totp_actif and not cible.totp_reinitialise and cible.jeton_enrolement_empreinte == ""


def test_sec03_deconnexion_apres_inactivite(client_agent, settings):
    import time

    settings.SESSION_INACTIVITE_SENSIBLE_MINUTES = 1
    client = client_agent(agent("regisseur"))
    assert client.get("/api/gestion/moi").status_code == 200
    session = client.session
    session["derniere_activite"] = time.time() - 120
    session.save()
    assert client.get("/api/gestion/moi").status_code == 401


def test_sec02_deconnexion(client_agent):
    client = client_agent(agent("gestionnaire"))
    assert client.post("/api/gestion/auth/deconnexion").status_code == 204
    assert client.get("/api/gestion/moi").status_code == 401


def test_adm03_agent_desactive_perd_ses_sessions(client_agent):
    cible = agent("gestionnaire")
    session_cible = client_agent(cible)
    client = client_agent(agent("administrateur"))
    assert client.patch(f"/api/gestion/admin/agents/{cible.pk}", {"is_active": False}, format="json").status_code == 200
    assert session_cible.get("/api/gestion/moi").status_code == 401


def test_adm03_creation_d_agent_par_l_api_refusee(client_agent):
    assert (
        client_agent(agent("administrateur")).post("/api/gestion/admin/agents", {"username": "x"}, format="json").status_code
        == 405
    )
