"""REF-01 (sites, bâtiments, espaces), REF-02 (familles)."""

from __future__ import annotations

import pytest

from apps.referentiel.models import Espace, FamilleEspace
from tests.fabriques import BatimentFabrique, EspaceFabrique, SiteFabrique, agent

pytestmark = pytest.mark.django_db


def test_ref02_familles_initiales_presentes():
    codes = set(FamilleEspace.objects.values_list("code", flat=True))
    assert {"gymnase", "salle-fetes", "salle-reunion", "terrain-exterieur", "dojo"} <= codes


def test_ref01_creation_site_batiment_espace_par_api(client_agent):
    client = client_agent(agent("gestionnaire"))
    site = client.post("/api/gestion/referentiel/sites", {"code": "stade-nord", "nom": "Stade Nord"}, format="json")
    assert site.status_code == 201
    batiment = client.post("/api/gestion/referentiel/batiments", {"site": site.json()["id"], "nom": "Tribune"}, format="json")
    assert batiment.status_code == 201
    famille = FamilleEspace.objects.get(code="gymnase")
    espace = client.post(
        "/api/gestion/referentiel/espaces",
        {
            "code": "gymnase-nord",
            "nom": "Gymnase Nord",
            "batiment": batiment.json()["id"],
            "famille": famille.pk,
            "capacite": 300,
            "surface_m2": 1200,
            "accessible_pmr": True,
            "gardiennage_requis": True,
        },
        format="json",
    )
    assert espace.status_code == 201, espace.json()
    assert espace.json()["site_nom"] == "Stade Nord" and espace.json()["famille_libelle"] == "Gymnase"


def test_ref01_filtrer_les_espaces_par_famille(client_agent):
    EspaceFabrique(famille=FamilleEspace.objects.get(code="salle-fetes"))
    EspaceFabrique()
    reponse = client_agent(agent("accueil")).get(
        "/api/gestion/referentiel/espaces", {"famille": FamilleEspace.objects.get(code="salle-fetes").pk}
    )
    assert reponse.json()["count"] == 1


def test_ref01_sous_espace_sur_le_meme_site(client_agent):
    gymnase = EspaceFabrique()
    autre_batiment = BatimentFabrique(site=SiteFabrique())
    client = client_agent(agent("gestionnaire"))
    reponse = client.post(
        "/api/gestion/referentiel/espaces",
        {"code": "tiers-1", "nom": "Tiers 1", "batiment": autre_batiment.pk, "famille": gymnase.famille_id, "parent": gymnase.pk},
        format="json",
    )
    assert reponse.status_code == 400


def test_ref01_espace_ne_peut_pas_etre_son_propre_descendant(client_agent):
    gymnase = EspaceFabrique()
    tiers = EspaceFabrique(batiment=gymnase.batiment, parent=gymnase)
    reponse = client_agent(agent("gestionnaire")).patch(
        f"/api/gestion/referentiel/espaces/{gymnase.pk}", {"parent": tiers.pk}, format="json"
    )
    assert reponse.status_code == 400


def test_ref01_hierarchie_ancetres_et_descendants():
    gymnase = EspaceFabrique()
    moitie = EspaceFabrique(batiment=gymnase.batiment, parent=gymnase)
    tiers = EspaceFabrique(batiment=gymnase.batiment, parent=moitie)
    assert tiers.ancetres() == [moitie, gymnase]
    assert set(gymnase.descendants()) == {moitie, tiers}
    assert moitie.ids_lies() == {gymnase.pk, moitie.pk, tiers.pk}


def test_ref01_capacite_simultanee_reservee_aux_espaces_partageables(client_agent):
    espace = EspaceFabrique()
    client = client_agent(agent("gestionnaire"))
    assert (
        client.patch(f"/api/gestion/referentiel/espaces/{espace.pk}", {"capacite_simultanee": 3}, format="json").status_code
        == 400
    )
    assert (
        client.patch(
            f"/api/gestion/referentiel/espaces/{espace.pk}", {"partageable": True, "capacite_simultanee": 3}, format="json"
        ).status_code
        == 200
    )
    assert Espace.objects.get(pk=espace.pk).capacite_simultanee == 3
