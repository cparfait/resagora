"""POR-03 : catalogue public ; SEC-01 : servi seulement par le canal portail."""

from __future__ import annotations

import pytest
from django.test import override_settings

from tests.fabriques import EspaceFabrique

pytestmark = [pytest.mark.django_db, pytest.mark.urls("config.urls_portail")]


@override_settings(CANAL="portail")
def test_por03_catalogue_ne_montre_que_les_espaces_publics(client_api):
    visible = EspaceFabrique(nom="Gymnase Nord", activites="basket, handball")
    EspaceFabrique(nom="Local technique", reservable_portail=False)
    EspaceFabrique(nom="Salle fermée", actif=False)
    reponse = client_api.get("/api/portail/catalogue/espaces")
    assert reponse.status_code == 200
    assert [e["nom"] for e in reponse.json()["results"]] == ["Gymnase Nord"]
    fiche = client_api.get(f"/api/portail/catalogue/espaces/{visible.pk}").json()
    assert "gardiennage_requis" not in fiche and "code" not in fiche
    assert fiche["site_nom"] == visible.batiment.site.nom


@override_settings(CANAL="portail")
def test_por03_recherche_sans_accent_et_capacite(client_api):
    EspaceFabrique(nom="Salle Élégance", capacite=40)
    EspaceFabrique(nom="Dojo", capacite=20, activites="judo, karaté")
    assert [e["nom"] for e in client_api.get("/api/portail/catalogue/espaces", {"recherche": "elegance"}).json()["results"]] == [
        "Salle Élégance"
    ]
    assert [e["nom"] for e in client_api.get("/api/portail/catalogue/espaces", {"recherche": "karate"}).json()["results"]] == [
        "Dojo"
    ]
    assert len(client_api.get("/api/portail/catalogue/espaces", {"capacite_min": "30"}).json()["results"]) == 1


@override_settings(CANAL="portail")
def test_por03_sites_et_familles_publics(client_api):
    espace = EspaceFabrique()
    EspaceFabrique(reservable_portail=False)
    assert [s["id"] for s in client_api.get("/api/portail/catalogue/sites").json()] == [espace.batiment.site_id]
    assert [f["code"] for f in client_api.get("/api/portail/catalogue/familles").json()] == ["gymnase"]


@override_settings(CANAL="gestion")
def test_sec01_vue_portail_refusee_hors_canal_portail(client_api):
    assert client_api.get("/api/portail/catalogue/sites").status_code in {403, 404}
