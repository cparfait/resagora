"""IMP-01 : semaine type d'un espace ou d'un site (créneaux réguliers de la saison par jour de la semaine) et
impressions au format calendrier (grille de la semaine, une colonne par jour, une ligne par demi-heure)."""

from __future__ import annotations

import io
from datetime import date, time

import pytest
from docx import Document as DocumentWord
from freezegun import freeze_time

from apps.documents import gotenberg, impression
from apps.referentiel.models import HoraireOuverture
from apps.reservations.tests.outils import reserver
from tests.fabriques import EspaceFabrique, SiteFabrique, agent, saison_2026, usager_avec_contact

pytestmark = pytest.mark.django_db
PDF = b"%PDF-1.7 semaine type"


@pytest.fixture(autouse=True)
def environnement(monkeypatch):
    convertis: list[bytes] = []

    def convertir(nom, docx, transport=None):
        convertis.append(docx)
        return PDF

    monkeypatch.setattr(gotenberg, "convertir_en_pdfa", convertir)
    with freeze_time("2026-11-16 09:00"):
        yield {"convertis": convertis}


def _ouvert(espace):
    for jour in range(7):
        HoraireOuverture.objects.create(espace=espace, jour_semaine=jour, debut=time(8), fin=time(23))
    return espace


@pytest.fixture
def saison():
    return saison_2026()


@pytest.fixture
def gymnase(saison):
    return _ouvert(EspaceFabrique(nom="Gymnase A"))


@pytest.fixture
def moitie(gymnase):
    return _ouvert(EspaceFabrique(nom="Gymnase A — moitié nord", batiment=gymnase.batiment, parent=gymnase))


def _annuel(espace, jour, debut, fin, regle, **champs):
    return reserver(espace, jour, debut, fin, recurrence=regle, date_fin=date(2027, 6, 26), type_code="creneau_annuel", **champs)


def _cellules(docx: bytes) -> list[str]:
    return [c.text for t in DocumentWord(io.BytesIO(docx)).tables for r in t.rows for c in r.cells]


def test_imp01_semaine_type_creneaux_reguliers_par_jour(gymnase, moitie, client_agent):
    _annuel(
        gymnase,
        date(2026, 9, 1),
        "18:00",
        "20:00",
        "FREQ=WEEKLY;BYDAY=TU,TH",
        usager=usager_avec_contact(nom="Club de hand"),
        statut="validee",
    )
    _annuel(moitie, date(2026, 9, 2), "14:00", "16:00", "FREQ=WEEKLY;INTERVAL=2", usager=usager_avec_contact(nom="Amicale yoga"))
    _annuel(
        moitie,
        date(2026, 9, 5),
        "10:00",
        "11:00",
        "FREQ=WEEKLY;BYDAY=SA",
        usager=usager_avec_contact(nom="Dupont", type="particulier"),
        statut="validee",
    )
    reserver(moitie, date(2026, 11, 20), "09:00", "10:00", usager=usager_avec_contact(nom="Ponctuel"), statut="validee")

    reponse = client_agent(agent("accueil", gymnase.batiment.site)).get(
        "/api/gestion/pilotage/semaine-type", {"espace": moitie.pk}
    )

    assert reponse.status_code == 200
    donnees = reponse.json()
    assert donnees["saison"]["nom"] == "2026-2027" and donnees["jours"][0] == "Lundi"
    vus = [(c["jour_libelle"], c["debut"], c["occupant"], c["provisoire"]) for c in donnees["creneaux"]]
    # Le gymnase entier occupe sa moitié (REF-05) ; une demande reste provisoire ; la réservation ponctuelle n'y est pas.
    assert vus == [
        ("Mardi", "18:00", "Club de hand", False),
        ("Mercredi", "14:00", "Amicale yoga", True),
        ("Jeudi", "18:00", "Club de hand", False),
        ("Samedi", "10:00", "Réservation privée", False),
    ]
    assert "Dupont" not in reponse.content.decode()
    assert donnees["creneaux"][1]["frequence"] == "une semaine sur 2" and not donnees["creneaux"][1]["pendant_vacances"]


def test_imp01_semaine_type_refusee_hors_perimetre(gymnase, client_agent):
    autre = client_agent(agent("accueil", SiteFabrique()))
    assert autre.get("/api/gestion/pilotage/semaine-type", {"espace": gymnase.pk}).status_code == 403
    assert autre.get("/api/gestion/pilotage/semaine-type.pdf", {"espace": gymnase.pk}).status_code == 403
    assert client_agent(agent("accueil")).get("/api/gestion/pilotage/semaine-type").status_code == 400


def test_imp01_semaine_type_imprimee_en_calendrier(gymnase, client_agent, environnement):
    _annuel(
        gymnase,
        date(2026, 9, 1),
        "18:00",
        "20:00",
        "FREQ=WEEKLY;BYDAY=TU",
        usager=usager_avec_contact(nom="Club de hand"),
        statut="validee",
    )
    client = client_agent(agent("gestionnaire"))

    reponse = client.get("/api/gestion/pilotage/semaine-type.pdf", {"espace": gymnase.pk, "papier": "A3"})

    assert reponse.status_code == 200 and reponse.content == PDF
    cellules = _cellules(environnement["convertis"][0])
    assert {"Lundi", "Mardi", "Dimanche", "18:00"} <= set(cellules)
    assert "18:00 – 20:00\nClub de hand" in cellules, "un bloc par créneau, horaires puis occupant"
    liste = client.get("/api/gestion/pilotage/semaine-type.pdf", {"espace": gymnase.pk, "mise_en_page": "liste"})
    assert liste.status_code == 200 and "Club de hand" in _cellules(environnement["convertis"][1])
    assert "Lundi" not in _cellules(environnement["convertis"][1]), "la liste ne montre que les jours occupés"
    invalide = client.get("/api/gestion/pilotage/semaine-type.pdf", {"espace": gymnase.pk, "mise_en_page": "affiche"})
    assert invalide.status_code == 400


def test_imp01_planning_d_un_site_imprime_en_calendrier(gymnase, moitie, client_agent, environnement):
    reserver(gymnase, date(2026, 11, 17), "18:00", "20:00", usager=usager_avec_contact(nom="Club de hand"), statut="validee")
    reserver(moitie, date(2026, 11, 19), "17:30", "19:30", usager=usager_avec_contact(nom="Club de judo"), statut="validee")
    site = gymnase.batiment.site

    reponse = client_agent(agent("accueil", site)).get(
        "/api/gestion/pilotage/planning.pdf", {"site": site.pk, "du": "2026-11-16"}
    )

    assert reponse.status_code == 200
    cellules = _cellules(environnement["convertis"][0])
    assert "Mar. 17/11" in cellules and "18:00 – 20:00\nClub de hand\nGymnase A" in cellules
    assert "17:30 – 19:30\nClub de judo\nGymnase A — moitié nord" in cellules


def test_imp01_calendrier_seances_simultanees_cote_a_cote():
    """Deux séances qui se chevauchent le même jour : deux sous-colonnes sous un seul en-tête de jour ; chaque bloc
    couvre ses demi-heures (cellules fusionnées verticalement)."""
    grille = impression.Grille(
        intitule="",
        jours=impression.JOURS_COURTS,
        blocs=[
            impression.Bloc(0, time(18), time(20), ["18:00 – 20:00", "Club A"]),
            impression.Bloc(0, time(19), time(21), ["19:00 – 21:00", "Club B"], provisoire=True),
            impression.Bloc(6, time(22), time(0), ["22:00 – 00:00", "Soirée"]),
        ],
    )
    edition = impression.Edition(titre="t", sous_titre="s", entetes=[], lignes=[], grilles=[grille])
    table = DocumentWord(io.BytesIO(impression.construire_docx(edition))).tables[-1]  # la première est l'en-tête

    assert len(table.columns) == 1 + 8, "lundi en deux sous-colonnes, les autres jours en une"
    entete = table.rows[0]._tr.tc_lst
    assert entete[1].grid_span == 2 and entete[1].xpath("string(.)") == "Lun."
    assert len(table.rows) == 1 + 2 * (24 - 8), "de 8 h à minuit, une ligne par demi-heure"
    fusions = [tc for tr in table._tbl.tr_lst for tc in tr.tc_lst if tc.vMerge == "restart"]
    assert len(fusions) == 3
    assert any(tc.xpath("string(.//w:shd/@w:fill)") == impression.GRIS_CLAIR for tc in fusions)
