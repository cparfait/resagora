"""ADM-01 calendrier (open data zone C, fériés), ADM-02 paramètres, REF-03 horaires, REF-06 fermetures, REF-08 documents."""

from __future__ import annotations

import json
from datetime import date

import httpx
import pytest
from django.core.files.uploadedfile import SimpleUploadedFile

from apps.referentiel.calendrier import ClientCalendrier, feries_calcules, importer_saison, paques, periodes_depuis_open_data
from apps.referentiel.models import Saison
from tests.fabriques import EspaceFabrique, SiteFabrique, agent

pytestmark = pytest.mark.django_db

# Extrait conforme au jeu national « fr-en-calendrier-scolaire » (dates publiées pour 2026-2027).
OPEN_DATA = {
    "results": [
        {
            "description": "Vacances de la Toussaint",
            "start_date": "2026-10-16T22:00:00+00:00",
            "end_date": "2026-11-01T23:00:00+00:00",
            "population": "-",
        },
        {
            "description": "Vacances de Noël",
            "start_date": "2026-12-18T23:00:00+00:00",
            "end_date": "2027-01-03T23:00:00+00:00",
            "population": "-",
        },
        {
            "description": "Pont de l'Ascension",
            "start_date": "2027-05-06T22:00:00+00:00",
            "end_date": "2027-05-06T22:00:00+00:00",
            "population": "-",
        },
        {
            "description": "Vacances d'Été",
            "start_date": "2027-07-02T22:00:00+00:00",
            "end_date": "2027-08-31T22:00:00+00:00",
            "population": "Enseignants",
        },
        {
            "description": "Vacances d'Été",
            "start_date": "2027-07-02T22:00:00+00:00",
            "end_date": "2027-09-01T22:00:00+00:00",
            "population": "Élèves",
        },
    ]
}


def test_adm01_paques_et_feries_calcules():
    assert paques(2027) == date(2027, 3, 28)
    feries = feries_calcules(2027)
    assert feries[date(2027, 5, 6)] == "Ascension" and feries[date(2027, 5, 17)] == "Lundi de Pentecôte" and len(feries) == 11


def test_adm01_conversion_open_data_dates_de_reprise_exclues():
    periodes = {p.libelle: p for p in periodes_depuis_open_data(OPEN_DATA["results"])}
    assert (periodes["Vacances de la Toussaint"].debut, periodes["Vacances de la Toussaint"].fin) == (
        date(2026, 10, 17),
        date(2026, 11, 1),
    )
    assert periodes["Pont de l'Ascension"].debut == periodes["Pont de l'Ascension"].fin == date(2027, 5, 7)
    assert periodes["Vacances d'Été"].fin == date(2027, 9, 1)


def test_adm01_import_de_la_saison_depuis_l_open_data_et_feries_en_secours():
    requetes = []

    def repondre(requete: httpx.Request) -> httpx.Response:
        requetes.append(requete)
        if "calendrier-scolaire" in str(requete.url):
            return httpx.Response(200, json=OPEN_DATA)
        return httpx.Response(503)

    saison = Saison.objects.create(nom="2026-2027", debut=date(2026, 9, 1), fin=date(2027, 6, 30))
    nombre = importer_saison(saison, client=ClientCalendrier(transport=httpx.MockTransport(repondre)), acteur="test")
    assert saison.periodes.filter(nature="vacances").count() == 3
    assert saison.periodes.filter(nature="ferie", debut=date(2026, 11, 11)).exists()
    assert nombre == saison.periodes.count()
    assert 'zones="Zone C"' in requetes[0].url.params["where"] and 'location="Versailles"' in requetes[0].url.params["where"]


def test_adm01_import_depuis_un_fichier(tmp_path):
    fichier = tmp_path / "calendrier.json"
    fichier.write_text(json.dumps(OPEN_DATA), encoding="utf-8")
    saison = Saison.objects.create(nom="2026-2027", debut=date(2026, 9, 1), fin=date(2027, 6, 30))
    importer_saison(
        saison,
        client=ClientCalendrier(transport=httpx.MockTransport(lambda r: httpx.Response(503))),
        fichier=fichier,
        acteur="test",
    )
    assert saison.periodes.filter(nature="vacances").count() == 3


def test_adm01_import_par_l_api_reserve_aux_parametres(client_agent):
    saison = Saison.objects.create(nom="2026-2027", debut=date(2026, 9, 1), fin=date(2027, 6, 30))
    assert (
        client_agent(agent("gestionnaire")).post(f"/api/gestion/referentiel/saisons/{saison.pk}/importer-calendrier").status_code
        == 403
    )


def test_adm01_import_d_un_fichier_depose_sans_acces_internet(client_agent, settings):

    settings.URL_JOURS_FERIES = "https://feries.test/{annee}.json"
    saison = Saison.objects.create(nom="2026-2027", debut=date(2026, 9, 1), fin=date(2027, 6, 30))
    administrateur = client_agent(agent("administrateur"))
    depot = SimpleUploadedFile("calendrier.json", json.dumps(OPEN_DATA).encode(), content_type="application/json")
    reponse = administrateur.post(
        f"/api/gestion/referentiel/saisons/{saison.pk}/importer-calendrier", {"fichier": depot}, format="multipart"
    )
    assert reponse.status_code == 200, reponse.content
    assert saison.periodes.filter(nature="vacances", source="import").count() == 3
    assert saison.periodes.filter(nature="ferie").exists()
    invalide = SimpleUploadedFile("calendrier.json", b"pas du json", content_type="application/json")
    refus = administrateur.post(
        f"/api/gestion/referentiel/saisons/{saison.pk}/importer-calendrier", {"fichier": invalide}, format="multipart"
    )
    assert refus.status_code == 400 and "export JSON" in refus.json()["message"]


def test_adm02_parametres_lus_et_modifies_avec_trace(client_agent):
    from apps.audit.models import JournalAudit

    lecture = client_agent(agent("accueil")).get("/api/gestion/parametres").json()
    assert any(p["cle"] == "options.duree_jours" and p["valeur"] == 7 for p in lecture)
    assert (
        client_agent(agent("gestionnaire"))
        .patch("/api/gestion/parametres", {"valeurs": {"options.duree_jours": 3}}, format="json")
        .status_code
        == 403
    )
    admin = client_agent(agent("administrateur"))
    assert admin.patch("/api/gestion/parametres", {"valeurs": {"options.duree_jours": "trois"}}, format="json").status_code == 400
    assert admin.patch("/api/gestion/parametres", {"valeurs": {"cle.inconnue": 1}}, format="json").status_code == 400
    reponse = admin.patch("/api/gestion/parametres", {"valeurs": {"options.duree_jours": 3}}, format="json")
    assert next(p for p in reponse.json() if p["cle"] == "options.duree_jours")["valeur"] == 3
    assert JournalAudit.objects.filter(action="modifier_parametre", objet_id="options.duree_jours").exists()


def test_ref03_horaires_par_l_api_et_perimetre(client_agent):
    site = SiteFabrique()
    espace, autre = EspaceFabrique(batiment__site=site), EspaceFabrique()
    client = client_agent(agent("gestionnaire", site))
    assert (
        client.post(
            "/api/gestion/referentiel/horaires",
            {"espace": espace.pk, "jour_semaine": 1, "debut": "08:00", "fin": "22:00"},
            format="json",
        ).status_code
        == 201
    )
    assert (
        client.post(
            "/api/gestion/referentiel/horaires",
            {"espace": autre.pk, "jour_semaine": 1, "debut": "08:00", "fin": "22:00"},
            format="json",
        ).status_code
        == 403
    )
    assert client.post(
        "/api/gestion/referentiel/horaires",
        {"espace": espace.pk, "jour_semaine": 1, "debut": "22:00", "fin": "08:00"},
        format="json",
    ).status_code in {400, 409}


def test_ref06_fermeture_par_l_api_signale_les_seances(client_agent):
    from apps.reservations.tests.outils import reserver, valider_systeme

    espace = EspaceFabrique()
    valider_systeme(reserver(espace, date(2026, 11, 10), "18:00", "20:00"))
    reponse = client_agent(agent("gestionnaire")).post(
        "/api/gestion/referentiel/fermetures",
        {
            "espace": espace.pk,
            "debut": "2026-11-09T00:00:00+01:00",
            "fin": "2026-11-12T00:00:00+01:00",
            "motif": "Dégât des eaux",
        },
        format="json",
    )
    assert reponse.status_code == 201 and reponse.json()["seances_touchees"] == 1
    assert (
        client_agent(agent("gestionnaire"))
        .post(
            "/api/gestion/referentiel/fermetures",
            {"debut": "2026-11-09T00:00:00+01:00", "fin": "2026-11-12T00:00:00+01:00", "motif": "x"},
            format="json",
        )
        .status_code
        == 400
    )


def test_ref08_document_d_espace_depose_et_telecharge(client_agent, monkeypatch):
    from apps.noyau import fichiers

    monkeypatch.setattr(fichiers, "analyser_clamav", lambda contenu: None)
    espace = EspaceFabrique()
    client = client_agent(agent("gestionnaire"))
    depot = client.post(
        "/api/gestion/referentiel/documents",
        {"espace": espace.pk, "titre": "Règlement intérieur", "fichier": SimpleUploadedFile("r.pdf", b"%PDF-1.4 x")},
        format="multipart",
    )
    assert depot.status_code == 201
    assert client.get(f"/api/gestion/referentiel/documents/{depot.json()['id']}/fichier").status_code == 200
    photo_sans_description = client.post(
        "/api/gestion/referentiel/photos",
        {"espace": espace.pk, "fichier": SimpleUploadedFile("p.png", b"\x89PNG\r\n\x1a\n" + b"0" * 20)},
        format="multipart",
    )
    assert photo_sans_description.status_code == 409
