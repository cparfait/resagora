"""RG-14 : droits = rôle × périmètre, vérifiés côté serveur sur chaque objet. ADM-03 : administration des droits."""

from __future__ import annotations

import datetime

import pytest

from apps.habilitations.models import Habilitation, Role
from apps.habilitations.services import filtrer_par_perimetre, peut, sites_autorises
from apps.referentiel.models import Espace
from tests.fabriques import EspaceFabrique, SiteFabrique, UtilisateurFabrique, agent, perimetre_sites

pytestmark = pytest.mark.django_db


@pytest.fixture
def deux_sites():
    site_a, site_b = SiteFabrique(nom="Site A"), SiteFabrique(nom="Site B")
    return site_a, site_b, EspaceFabrique(batiment__site=site_a), EspaceFabrique(batiment__site=site_b)


def test_rg14_peut_selon_role_et_perimetre(deux_sites):
    site_a, _site_b, espace_a, espace_b = deux_sites
    gestionnaire = agent("gestionnaire", site_a)
    assert peut(gestionnaire, "valider_reservation")
    assert peut(gestionnaire, "gerer_referentiel", espace_a)
    assert not peut(gestionnaire, "gerer_referentiel", espace_b)
    assert not peut(gestionnaire, "administrer")
    assert sites_autorises(gestionnaire, "lire_referentiel") == {site_a.pk}


def test_rg14_perimetre_ville_entiere_couvre_tous_les_sites(deux_sites):
    _a, _b, espace_a, espace_b = deux_sites
    direction = agent("direction")
    assert peut(direction, "lire_referentiel", espace_a) and peut(direction, "lire_referentiel", espace_b)
    assert not peut(direction, "gerer_referentiel", espace_a)
    assert sites_autorises(direction, "lire_referentiel") is None


def test_rg14_habilitation_expiree_ou_future_ignoree(deux_sites):
    site_a, _b, espace_a, _ = deux_sites
    utilisateur = UtilisateurFabrique()
    aujourd_hui = datetime.date.today()
    Habilitation.objects.create(
        utilisateur=utilisateur,
        role=Role.objects.get(code="gestionnaire"),
        perimetre=perimetre_sites(site_a),
        debut=aujourd_hui - datetime.timedelta(days=30),
        fin=aujourd_hui - datetime.timedelta(days=1),
    )
    assert not peut(utilisateur, "lire_referentiel", espace_a)


def test_rg14_agent_inactif_ou_anonyme_refuse(deux_sites):
    site_a, _b, espace_a, _ = deux_sites
    gestionnaire = agent("gestionnaire", site_a)
    gestionnaire.is_active = False
    assert not peut(gestionnaire, "lire_referentiel", espace_a)
    assert not peut(None, "lire_referentiel")


def test_rg14_action_inconnue_leve_une_erreur():
    with pytest.raises(ValueError):
        peut(UtilisateurFabrique(), "action_qui_n_existe_pas")


def test_rg14_filtrer_par_perimetre(deux_sites):
    site_a, _b, espace_a, _espace_b = deux_sites
    gestionnaire = agent("gestionnaire", site_a)
    visibles = filtrer_par_perimetre(Espace.objects.all(), gestionnaire, "lire_referentiel", "batiment__site")
    assert list(visibles) == [espace_a]
    assert not filtrer_par_perimetre(Espace.objects.all(), gestionnaire, "administrer", "batiment__site").exists()


def test_rg14_api_liste_limitee_au_perimetre(deux_sites, client_agent):
    site_a, _b, espace_a, _espace_b = deux_sites
    reponse = client_agent(agent("gestionnaire", site_a)).get("/api/gestion/referentiel/espaces")
    assert reponse.status_code == 200
    assert [e["id"] for e in reponse.json()["results"]] == [espace_a.pk]


def test_rg14_api_objet_hors_perimetre_introuvable(deux_sites, client_agent):
    site_a, _b, _a, espace_b = deux_sites
    client = client_agent(agent("gestionnaire", site_a))
    assert client.get(f"/api/gestion/referentiel/espaces/{espace_b.pk}").status_code == 404
    assert client.patch(f"/api/gestion/referentiel/espaces/{espace_b.pk}", {"nom": "Piraté"}, format="json").status_code == 404
    espace_b.refresh_from_db()
    assert espace_b.nom != "Piraté"


def test_rg14_api_creation_hors_perimetre_refusee(deux_sites, client_agent):
    site_a, _site_b, espace_a, espace_b = deux_sites
    client = client_agent(agent("gestionnaire", site_a))
    corps = {"code": "nouvel-espace", "nom": "Nouvel espace", "batiment": espace_b.batiment_id, "famille": espace_b.famille_id}
    reponse = client.post("/api/gestion/referentiel/espaces", corps, format="json")
    assert reponse.status_code == 403
    assert not Espace.objects.filter(code="nouvel-espace").exists()
    corps["batiment"] = espace_a.batiment_id
    assert client.post("/api/gestion/referentiel/espaces", corps, format="json").status_code == 201


def test_rg14_api_action_absente_du_role_refusee(deux_sites, client_agent):
    site_a, _b, espace_a, _ = deux_sites
    client = client_agent(agent("accueil", site_a))
    assert client.get("/api/gestion/referentiel/espaces").status_code == 200
    assert client.patch(f"/api/gestion/referentiel/espaces/{espace_a.pk}", {"nom": "X"}, format="json").status_code == 403


def test_rg14_api_non_authentifie(client_api):
    assert client_api.get("/api/gestion/referentiel/espaces").status_code == 401
    assert client_api.get("/api/gestion/moi").status_code == 401


def test_adm03_administrateur_attribue_un_role_limite_a_un_site(deux_sites, client_agent):
    site_a, _b, _a, _b2 = deux_sites
    admin = agent("administrateur")
    cible = UtilisateurFabrique()
    client = client_agent(admin)
    perimetre = client.post("/api/gestion/admin/perimetres", {"nom": "Site A seul", "sites": [site_a.pk]}, format="json")
    assert perimetre.status_code == 201
    role = Role.objects.get(code="gestionnaire")
    reponse = client.post(
        "/api/gestion/admin/habilitations",
        {"utilisateur": cible.pk, "role": role.pk, "perimetre": perimetre.json()["id"]},
        format="json",
    )
    assert reponse.status_code == 201
    cible.vider_cache_habilitations()
    assert sites_autorises(cible, "valider_reservation") == {site_a.pk}


def test_adm03_gestionnaire_ne_peut_pas_administrer(client_agent):
    client = client_agent(agent("gestionnaire"))
    assert client.get("/api/gestion/admin/habilitations").status_code == 403
    assert client.post("/api/gestion/admin/roles", {"code": "x", "libelle": "X", "actions": []}, format="json").status_code == 403


def test_adm03_role_avec_action_inconnue_refuse(client_agent):
    client = client_agent(agent("administrateur"))
    reponse = client.post("/api/gestion/admin/roles", {"code": "x", "libelle": "X", "actions": ["voler"]}, format="json")
    assert reponse.status_code == 400


def test_adm03_habilitation_ad_non_supprimable_a_la_main(client_agent):
    from apps.habilitations.models import GroupeAD
    from tests.fabriques import ville_entiere

    admin = agent("administrateur")
    cible = UtilisateurFabrique()
    groupe = GroupeAD.objects.create(dn="CN=G,DC=test", role=Role.objects.get(code="accueil"), perimetre=ville_entiere())
    habilitation = Habilitation.objects.create(
        utilisateur=cible, role=groupe.role, perimetre=groupe.perimetre, source="ad", groupe_ad=groupe
    )
    reponse = client_agent(admin).delete(f"/api/gestion/admin/habilitations/{habilitation.pk}")
    assert reponse.status_code == 400
    assert Habilitation.objects.filter(pk=habilitation.pk).exists()


def test_rg14_moi_renvoie_les_actions_par_perimetre(deux_sites, client_agent):
    site_a, *_ = deux_sites
    reponse = client_agent(agent("gestionnaire", site_a)).get("/api/gestion/moi")
    assert reponse.status_code == 200
    habilitation = reponse.json()["habilitations"][0]
    assert habilitation["role"] == "gestionnaire" and habilitation["sites"] == [site_a.pk]
    assert "valider_reservation" in habilitation["actions"]
