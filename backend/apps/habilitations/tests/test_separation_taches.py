"""ADM-03 / RG-14 : séparation des tâches, objets transversaux et multi-sites, administration des droits (ADR 0005)."""

from __future__ import annotations

import pytest

from apps.habilitations.actions import INCOMPATIBILITES, ROLES_INITIAUX
from apps.habilitations.models import GroupeAD, Habilitation, Role
from apps.habilitations.services import peut
from apps.referentiel.models import Batiment, Espace, FamilleEspace
from tests.fabriques import (
    BatimentFabrique,
    EspaceFabrique,
    SiteFabrique,
    UtilisateurFabrique,
    agent,
    perimetre_sites,
    ville_entiere,
)

pytestmark = pytest.mark.django_db


def test_adm03_roles_initiaux_respectent_la_separation_des_taches():
    for code, definition in ROLES_INITIAUX.items():
        actions = set(definition["actions"])  # type: ignore[arg-type]
        for premiere, seconde in INCOMPATIBILITES:
            assert not {premiere, seconde} <= actions, f"{code} cumule {premiere} et {seconde}"
    assert "encaisser" not in ROLES_INITIAUX["financier"]["actions"]  # type: ignore[operator]
    assert "emettre_facture" not in ROLES_INITIAUX["regisseur"]["actions"]  # type: ignore[operator]
    assert not {"encaisser", "emettre_avoir", "valider_retenue", "arbitrer_campagne"} & set(
        ROLES_INITIAUX["administrateur"]["actions"]
    )  # type: ignore[arg-type]
    assert "lire_audit" not in ROLES_INITIAUX["gestionnaire"]["actions"]  # type: ignore[operator]


def test_adm03_cumul_incompatible_refuse_par_l_api(client_agent):
    cible = agent("regisseur")
    reponse = client_agent(agent("administrateur")).post(
        "/api/gestion/admin/habilitations",
        {"utilisateur": cible.pk, "role": Role.objects.get(code="financier").pk, "perimetre": ville_entiere().pk},
        format="json",
    )
    assert reponse.status_code == 400 and reponse.json()["code"] == "cumul_incompatible"


def test_adm03_habilitation_ad_non_modifiable_a_la_main(client_agent):
    cible = UtilisateurFabrique()
    groupe = GroupeAD.objects.create(dn="CN=G,DC=test", role=Role.objects.get(code="accueil"), perimetre=ville_entiere())
    habilitation = Habilitation.objects.create(
        utilisateur=cible, role=groupe.role, perimetre=groupe.perimetre, source="ad", groupe_ad=groupe
    )
    reponse = client_agent(agent("administrateur")).patch(
        f"/api/gestion/admin/habilitations/{habilitation.pk}", {"role": Role.objects.get(code="administrateur").pk}, format="json"
    )
    assert reponse.status_code == 400
    habilitation.refresh_from_db()
    assert habilitation.role.code == "accueil"


def test_adm03_administrateur_limite_a_un_site_ne_gere_pas_les_droits(client_agent):
    admin_local = agent("administrateur", SiteFabrique())
    client = client_agent(admin_local)
    cible = UtilisateurFabrique()
    reponse = client.post(
        "/api/gestion/admin/habilitations",
        {"utilisateur": cible.pk, "role": Role.objects.get(code="gestionnaire").pk, "perimetre": ville_entiere().pk},
        format="json",
    )
    assert reponse.status_code == 403
    assert client.patch(
        f"/api/gestion/admin/roles/{Role.objects.get(code='accueil').pk}", {"libelle": "X"}, format="json"
    ).status_code in {403, 404}


@pytest.mark.parametrize(
    "chemin", ["admin/roles", "admin/perimetres", "admin/groupes-ad", "admin/agents", "admin/habilitations", "admin/actions"]
)
def test_adm03_administration_refusee_sans_droit(client_agent, chemin):
    assert client_agent(agent("gestionnaire")).get(f"/api/gestion/{chemin}").status_code == 403


def test_adm06_ajouter_groupe_ad_et_son_role_par_l_api(client_agent):
    client = client_agent(agent("administrateur"))
    corps = {
        "dn": "CN=GG-Sports,OU=Groupes,DC=ville,DC=local",
        "role": Role.objects.get(code="accueil").pk,
        "perimetre": ville_entiere().pk,
    }
    assert client.post("/api/gestion/admin/groupes-ad", corps, format="json").status_code == 201
    doublon = {**corps, "dn": corps["dn"].lower()}
    assert client.post("/api/gestion/admin/groupes-ad", doublon, format="json").status_code in {400, 409}


def test_rg14_famille_non_modifiable_par_agent_limite_a_un_site(client_agent):
    famille = FamilleEspace.objects.get(code="dojo")
    local = client_agent(agent("gestionnaire", SiteFabrique()))
    assert local.get(f"/api/gestion/referentiel/familles/{famille.pk}").status_code == 200
    assert (
        local.patch(f"/api/gestion/referentiel/familles/{famille.pk}", {"libelle": "Renommée"}, format="json").status_code == 403
    )
    assert (
        local.post("/api/gestion/referentiel/familles", {"code": "piscine", "libelle": "Piscine"}, format="json").status_code
        == 403
    )
    ville = client_agent(agent("gestionnaire"))
    assert (
        ville.patch(f"/api/gestion/referentiel/familles/{famille.pk}", {"libelle": "Dojo municipal"}, format="json").status_code
        == 200
    )


def test_rg14_api_deplacement_vers_autre_site_refuse(client_agent):
    site_a, site_b = SiteFabrique(), SiteFabrique()
    espace = EspaceFabrique(batiment__site=site_a)
    batiment_b = BatimentFabrique(site=site_b)
    batiment_a = espace.batiment
    client = client_agent(agent("gestionnaire", site_a))
    assert (
        client.patch(f"/api/gestion/referentiel/espaces/{espace.pk}", {"batiment": batiment_b.pk}, format="json").status_code
        == 403
    )
    assert Espace.objects.get(pk=espace.pk).batiment_id == batiment_a.pk
    assert (
        client.patch(f"/api/gestion/referentiel/batiments/{batiment_a.pk}", {"site": site_b.pk}, format="json").status_code == 403
    )
    assert Batiment.objects.get(pk=batiment_a.pk).site_id == site_a.pk


def test_rg14_creation_de_site_par_agent_limite_refusee(client_agent):
    client = client_agent(agent("gestionnaire", SiteFabrique()))
    assert client.post("/api/gestion/referentiel/sites", {"code": "nouveau", "nom": "Nouveau"}, format="json").status_code == 403


def test_rg14_objet_multi_sites_lecture_si_un_site_ecriture_si_tous():
    site_a, site_b = SiteFabrique(), SiteFabrique()

    class ObjetMultiSites:
        def sites_concernes(self) -> set[int]:
            return {site_a.pk, site_b.pk}

    local = agent("gestionnaire", site_a)
    assert peut(local, "lire_reservation", ObjetMultiSites())
    assert not peut(local, "valider_reservation", ObjetMultiSites())
    deux_sites = agent("gestionnaire")
    Habilitation.objects.filter(utilisateur=deux_sites).update(perimetre=perimetre_sites(site_a, site_b))
    deux_sites.vider_cache_habilitations()
    assert peut(deux_sites, "valider_reservation", ObjetMultiSites())
