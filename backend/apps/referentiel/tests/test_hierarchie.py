"""REF-05 (préparation au lot 1) : hiérarchie des espaces, feuilles, cohérence des déplacements ; REF-02 : familles."""

from __future__ import annotations

from datetime import UTC, datetime

import pytest

from apps.referentiel.models import FamilleEspace
from tests.fabriques import BatimentFabrique, EspaceFabrique, agent

pytestmark = pytest.mark.django_db


@pytest.fixture
def gymnase():
    gymnase = EspaceFabrique(nom="Gymnase")
    tiers = [EspaceFabrique(batiment=gymnase.batiment, parent=gymnase, nom=f"Tiers {i}") for i in (1, 2, 3)]
    return gymnase, tiers


def test_ref05_tiers_freres_independants(gymnase):
    entier, (t1, t2, t3) = gymnase
    assert t1.ids_lies() == {t1.pk, entier.pk}
    assert t2.pk not in t1.ids_lies()
    assert {e.pk for e in entier.feuilles()} == {t1.pk, t2.pk, t3.pk}
    assert t1.feuilles() == [t1]


def test_ref05_feuilles_d_une_hierarchie_a_deux_niveaux():
    terrain = EspaceFabrique(nom="Terrain")
    moitie = EspaceFabrique(batiment=terrain.batiment, parent=terrain, nom="Moitié A")
    quart_1 = EspaceFabrique(batiment=terrain.batiment, parent=moitie, nom="Quart 1")
    quart_2 = EspaceFabrique(batiment=terrain.batiment, parent=moitie, nom="Quart 2")
    moitie_b = EspaceFabrique(batiment=terrain.batiment, parent=terrain, nom="Moitié B")
    assert {e.pk for e in terrain.feuilles()} == {quart_1.pk, quart_2.pk, moitie_b.pk}
    assert {e.pk for e in moitie.feuilles()} == {quart_1.pk, quart_2.pk}


def test_ref05_parent_dans_le_meme_batiment(client_agent, gymnase):
    entier, _ = gymnase
    autre = BatimentFabrique(site=entier.batiment.site)
    reponse = client_agent(agent("gestionnaire")).post(
        "/api/gestion/referentiel/espaces",
        {"code": "x", "nom": "X", "batiment": autre.pk, "famille": entier.famille_id, "parent": entier.pk},
        format="json",
    )
    assert reponse.status_code == 400


def test_ref05_espace_divise_ne_change_pas_de_batiment(client_agent, gymnase):
    entier, _ = gymnase
    autre = BatimentFabrique(site=entier.batiment.site)
    reponse = client_agent(agent("gestionnaire")).patch(
        f"/api/gestion/referentiel/espaces/{entier.pk}", {"batiment": autre.pk}, format="json"
    )
    assert reponse.status_code == 400


def test_ref02_filtrer_les_espaces_par_famille(client_agent):
    EspaceFabrique(famille=FamilleEspace.objects.get(code="salle-fetes"))
    EspaceFabrique()
    reponse = client_agent(agent("accueil")).get(
        "/api/gestion/referentiel/espaces", {"famille": FamilleEspace.objects.get(code="salle-fetes").pk}
    )
    assert reponse.json()["count"] == 1


def test_ref02_ecriture_des_familles_autorisee_et_refusee(client_agent):
    assert (
        client_agent(agent("accueil"))
        .post("/api/gestion/referentiel/familles", {"code": "x", "libelle": "X"}, format="json")
        .status_code
        == 403
    )
    assert (
        client_agent(agent("gestionnaire"))
        .post("/api/gestion/referentiel/familles", {"code": "piscine", "libelle": "Piscine"}, format="json")
        .status_code
        == 201
    )


def test_ref04_gardiennage_elargi_des_temps_d_ouverture_et_de_fermeture():
    gymnase = EspaceFabrique(nom="Gymnase gardienné", gardiennage_requis=True, temps_ouverture_min=20, temps_fermeture_min=30)
    salle = EspaceFabrique(nom="Salle sans gardien", gardiennage_requis=False)
    debut, fin = datetime(2026, 11, 10, 17, 0, tzinfo=UTC), datetime(2026, 11, 10, 19, 0, tzinfo=UTC)
    assert gymnase.plage_gardiennage(debut, fin) == (
        datetime(2026, 11, 10, 16, 40, tzinfo=UTC),
        datetime(2026, 11, 10, 19, 30, tzinfo=UTC),
    )
    assert salle.plage_gardiennage(debut, fin) is None
