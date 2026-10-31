"""Lot 6 — pilotage : statistiques (STA-01 à STA-05) et export tableur, tableau de bord « à traiter » et alertes
(DSH-01 à DSH-03), périmètre (DSH-05), compteurs cliquables (DSH-06), tableau de la direction (DSH-04), éditions du
planning (IMP-01, IMP-03) et envoi programmé (IMP-04)."""

from __future__ import annotations

import io
from datetime import date, datetime, time, timedelta

import pytest
from django.core import mail
from freezegun import freeze_time
from openpyxl import load_workbook

from apps.documents import gotenberg
from apps.pilotage import impressions, services
from apps.pilotage.models import EnvoiProgramme
from apps.referentiel.models import HoraireOuverture
from apps.reservations.recurrence import PARIS
from apps.reservations.tests.outils import reserver
from tests.fabriques import EspaceFabrique, SiteFabrique, agent, usager_avec_contact

pytestmark = pytest.mark.django_db
LUNDI = date(2026, 11, 9)
PDF = b"%PDF-1.7 planning"


@pytest.fixture(autouse=True)
def environnement(monkeypatch):
    convertis: list[bytes] = []

    def convertir(nom, docx, transport=None):
        convertis.append(docx)
        return PDF

    monkeypatch.setattr(gotenberg, "convertir_en_pdfa", convertir)
    with freeze_time("2026-11-16 09:00") as horloge:
        yield {"horloge": horloge, "convertis": convertis}


@pytest.fixture
def gymnase():
    espace = EspaceFabrique(nom="Gymnase A")
    for jour in range(7):
        HoraireOuverture.objects.create(espace=espace, jour_semaine=jour, debut=time(8), fin=time(22))
    return espace


def test_sta01_taux_d_occupation_du_mois(gymnase, client_agent):
    association = usager_avec_contact(nom="Club de volley")
    for decalage in range(5):  # 5 séances de 2 h sur la semaine du 9 novembre
        reserver(gymnase, LUNDI + timedelta(days=decalage), "18:00", "20:00", usager=association, statut="validee")
    reponse = client_agent(agent("direction")).get(
        "/api/gestion/pilotage/statistiques/occupation", {"du": "2026-11-09", "au": "2026-11-15"}
    )
    assert reponse.status_code == 200
    ligne = reponse.json()["espaces"][0]
    # 10 h réservées ; 7 jours × 14 h ouvertes moins le 11 novembre férié (84 h), plus les 2 h tenues ce jour-là.
    assert (
        ligne["minutes_reservees"] == 600
        and ligne["minutes_ouverture"] == 86 * 60
        and ligne["taux"] == round(10000 * 600 / (86 * 60))
    )
    assert reponse.json()["sites"][0]["minutes_reservees"] == 600


def test_sta02_repartition_des_heures_par_type_d_usager(gymnase, client_agent):
    reserver(gymnase, LUNDI, "18:00", "20:00", usager=usager_avec_contact(nom="Club"), statut="validee")
    reserver(gymnase, LUNDI, "09:00", "10:00", usager=usager_avec_contact(nom="École", type="ecole"), statut="validee")
    donnees = (
        client_agent(agent("direction"))
        .get("/api/gestion/pilotage/statistiques/repartition", {"du": "2026-11-09", "au": "2026-11-15"})
        .json()
    )
    parts = {p["cle"]: p for p in donnees["types_usager"]}
    assert parts["association"]["minutes"] == 120 and parts["ecole"]["minutes"] == 60 and parts["association"]["part"] == 6667


def test_sta03_recettes_et_gratuites_de_l_annee(client_agent, modeles_documents, monkeypatch):
    from apps.documents import services as documents
    from apps.finances import facturation
    from apps.finances.tests.outils import grille_votee, location

    monkeypatch.setattr(documents, "convertir_en_pdfa", lambda nom, docx, transport=None: PDF)
    salle = EspaceFabrique(nom="Salle des fêtes")
    grille_votee(salle)
    with freeze_time("2026-11-02 10:00"):
        facture = facturation.facturer(location(espace=salle).dossier, acteur=agent("gestionnaire"))
    donnees = (
        client_agent(agent("financier"))
        .get("/api/gestion/pilotage/statistiques/recettes", {"du": "2026-01-01", "au": "2026-12-31"})
        .json()
    )
    assert donnees["factures"] == 1 and donnees["emis"] == facture.total_du and donnees["net"] == facture.total_du
    assert (
        client_agent(agent("accueil"))
        .get("/api/gestion/pilotage/statistiques/recettes", {"du": "2026-01-01", "au": "2026-12-31"})
        .status_code
        == 403
    )


def test_sta04_export_tableur_neutralise(gymnase, client_agent):
    reserver(gymnase, LUNDI, "18:00", "20:00", usager=usager_avec_contact(nom='=HYPERLINK("x")'), statut="validee")
    reponse = client_agent(agent("direction")).get(
        "/api/gestion/pilotage/statistiques/occupation", {"du": "2026-11-09", "au": "2026-11-15", "export": "xlsx"}
    )
    assert reponse.status_code == 200
    classeur = load_workbook(io.BytesIO(reponse.content))
    assert classeur.sheetnames == ["Occupation par espace", "Occupation par site"]
    assert classeur["Occupation par espace"]["B2"].value == "Gymnase A"


def test_sta05_indicateurs_de_personnel(client_agent):
    from apps.personnel import services as personnel
    from apps.personnel.models import Vacation
    from apps.personnel.tests.outils import gardien, site_gardienne

    site, _espace = site_gardienne()
    martin = gardien(site)
    vacation = Vacation.objects.create(
        site=site, debut=datetime(2026, 10, 6, 17, tzinfo=PARIS), fin=datetime(2026, 10, 6, 21, tzinfo=PARIS)
    )
    personnel.affecter(vacation, martin, acteur="système")
    donnees = (
        client_agent(agent("planificateur"))
        .get("/api/gestion/pilotage/statistiques/personnel", {"du": "2026-10-01", "au": "2026-12-31"})
        .json()
    )
    assert donnees["agents"] == 1 and donnees["planifiees"] == 240


def test_dsh01_le_tableau_de_bord_liste_les_demandes_a_instruire(gymnase, client_agent):
    reserver(gymnase, LUNDI + timedelta(days=14), "18:00", "20:00")
    compteurs = {
        c["code"]: c for c in client_agent(agent("gestionnaire")).get("/api/gestion/pilotage/a-traiter").json()["compteurs"]
    }
    assert compteurs["demandes"]["nombre"] == 1
    # DSH-06 : le compteur ouvre la liste filtrée.
    assert compteurs["demandes"]["lien"] == "/reservations/dossiers?statut=demande,en_instruction"


def test_dsh02_besoin_non_couvert_au_tableau_de_bord(client_agent):
    from apps.personnel import services as personnel
    from apps.personnel.tests.outils import seance, site_gardienne

    site, espace = site_gardienne()
    seance(espace, date(2026, 11, 20))
    personnel.recalculer_besoins(site.pk, date(2026, 11, 20))
    compteurs = {
        c["code"]: c for c in client_agent(agent("planificateur")).get("/api/gestion/pilotage/a-traiter").json()["compteurs"]
    }
    assert compteurs["besoins"]["nombre"] == 1 and compteurs["besoins"]["lien"] == "/personnel/vacations?besoins_jours=14"


def test_dsh03_alertes_du_jour(client_agent):
    from apps.materiel import services as materiel
    from apps.materiel.models import Materiel

    espace = EspaceFabrique(nom="Gymnase B")
    but = Materiel.objects.create(
        code="but", libelle="But", nature="fixe", periodicite_controle_jours=365, valeur_journaliere_centimes=100
    )
    stock = materiel.entrer(but, espace.batiment.site, 2, acteur="système", espace=espace)
    materiel.enregistrer_controle(stock, acteur="système", realise_le=date(2025, 10, 1))
    compteurs = {
        c["code"]: c for c in client_agent(agent("gestionnaire")).get("/api/gestion/pilotage/a-traiter").json()["compteurs"]
    }
    assert compteurs["controles"]["nombre"] == 1 and compteurs["controles"]["groupe"] == "alertes"
    assert {"factures", "cautions", "pieces"} <= set(compteurs)


def test_dsh05_un_agent_d_un_site_ne_voit_que_son_site(gymnase, client_agent):
    autre = EspaceFabrique(nom="Gymnase du centre")
    reserver(gymnase, LUNDI + timedelta(days=14), "18:00", "20:00")
    reserver(autre, LUNDI + timedelta(days=14), "18:00", "20:00")
    local = client_agent(agent("gestionnaire", autre.batiment.site))
    compteurs = {c["code"]: c for c in local.get("/api/gestion/pilotage/a-traiter").json()["compteurs"]}
    assert compteurs["demandes"]["nombre"] == 1
    occupation = local.get("/api/gestion/pilotage/statistiques/occupation", {"du": "2026-11-09", "au": "2026-11-30"}).json()
    assert {e["espace"] for e in occupation["espaces"]} == {autre.pk}, "statistiques limitées au site de l'agent"
    accueil = client_agent(agent("accueil")).get("/api/gestion/pilotage/a-traiter").json()["compteurs"]
    assert "demandes" not in {c["code"] for c in accueil}, "seuls les compteurs des écrans permis"


def test_dsh04_tableau_de_bord_direction(gymnase, client_agent):
    reserver(gymnase, LUNDI, "18:00", "20:00", usager=usager_avec_contact(), statut="validee")
    reserver(gymnase, date(2025, 11, 10), "18:00", "21:00", usager=usager_avec_contact(), statut="validee")
    donnees = client_agent(agent("direction")).get("/api/gestion/pilotage/direction", {"annee": 2026}).json()
    assert donnees["courant"]["heures_reservees"] == 2 and donnees["precedent"]["heures_reservees"] == 3
    assert donnees["mois"][10]["heures"] == 2
    assert client_agent(agent("gestionnaire")).get("/api/gestion/pilotage/direction").status_code == 403


def test_imp01_planning_hebdomadaire_d_un_gymnase(gymnase, client_agent, environnement):
    reserver(
        gymnase, LUNDI + timedelta(days=7), "18:00", "20:00", usager=usager_avec_contact(nom="Club de hand"), statut="validee"
    )
    reponse = client_agent(agent("accueil")).get(
        "/api/gestion/pilotage/planning.pdf", {"espace": gymnase.pk, "du": "2026-11-16", "au": "2026-11-22", "papier": "A3"}
    )
    assert reponse.status_code == 200 and reponse.content == PDF
    from docx import Document as DocumentWord

    texte = "\n".join(
        c.text for t in DocumentWord(io.BytesIO(environnement["convertis"][0])).tables for r in t.rows for c in r.cells
    )
    assert "Club de hand" in texte and "18:00 – 20:00" in texte
    hors = client_agent(agent("accueil", SiteFabrique()))
    assert hors.get("/api/gestion/pilotage/planning.pdf", {"espace": gymnase.pk}).status_code == 403


def test_imp03_feuille_de_salle_sans_nom_de_particulier(gymnase, client_agent, environnement):
    reserver(
        gymnase,
        LUNDI + timedelta(days=7),
        "14:00",
        "18:00",
        usager=usager_avec_contact(nom="Dupont", type="particulier"),
        statut="validee",
    )
    reponse = client_agent(agent("accueil")).get(
        "/api/gestion/pilotage/feuille-de-salle.pdf", {"espace": gymnase.pk, "jour": "2026-11-17"}
    )
    assert reponse.status_code == 200
    from docx import Document as DocumentWord

    document = DocumentWord(io.BytesIO(environnement["convertis"][0]))
    texte = "\n".join([p.text for p in document.paragraphs] + [c.text for t in document.tables for r in t.rows for c in r.cells])
    assert "Réservation privée" in texte and "Dupont" not in texte and "/equipements/" in texte


def test_imp04_envoi_programme_du_planning(gymnase, client_agent, environnement, django_capture_on_commit_callbacks):
    accueil = client_agent(agent("gestionnaire"))
    reponse = accueil.post(
        "/api/gestion/pilotage/envois-planning",
        {
            "libelle": "Planning du gymnase A",
            "espace": gymnase.pk,
            "destinataires": ["gardiens@chatillon92.fr"],
            "jour_semaine": 4,
            "heure": "16:00",
        },
        format="json",
    )
    assert reponse.status_code == 201 and reponse.json()["prochain_envoi_le"].startswith("2026-11-20T16:00")
    environnement["horloge"].move_to("2026-11-20 16:30")
    with django_capture_on_commit_callbacks(execute=True):
        assert impressions.envoyer_plannings_dus() == 1
    assert impressions.envoyer_plannings_dus() == 0, "idempotent"
    message = next(m for m in mail.outbox if "semaine du 23/11/2026" in m.subject)
    assert message.attachments and message.attachments[0][0] == "planning-20261123.pdf"
    envoi = EnvoiProgramme.objects.get()
    assert envoi.prochain_envoi_le.astimezone(PARIS).date() == date(2026, 11, 27)
    assert client_agent(agent("accueil")).post("/api/gestion/pilotage/envois-planning", {}, format="json").status_code == 403


def test_sta01_fermeture_et_jour_ferie_hors_ouverture(gymnase):
    from apps.referentiel.models import Fermeture

    Fermeture.objects.create(
        espace=gymnase, debut=datetime(2026, 11, 9, 8, tzinfo=PARIS), fin=datetime(2026, 11, 9, 22, tzinfo=PARIS), motif="Travaux"
    )
    assert services.minutes_ouverture(gymnase, LUNDI, LUNDI + timedelta(days=2)) == 14 * 60  # lundi fermé, mercredi 11 férié


def test_imp04_destinataires_saisis_une_adresse_par_ligne(gymnase, client_agent):
    gestion = client_agent(agent("gestionnaire"))
    base = {"libelle": "Planning B", "espace": gymnase.pk, "jour_semaine": 4, "heure": "16:00"}
    reponse = gestion.post(
        "/api/gestion/pilotage/envois-planning",
        {**base, "destinataires_texte": "Gardiens@chatillon92.fr\nsport@chatillon92.fr; gardiens@chatillon92.fr"},
        format="json",
    )
    assert reponse.status_code == 201
    assert reponse.json()["destinataires"] == ["gardiens@chatillon92.fr", "sport@chatillon92.fr"]
    refus = gestion.post(
        "/api/gestion/pilotage/envois-planning", {**base, "destinataires_texte": "pas-une-adresse"}, format="json"
    )
    assert refus.status_code == 400 and "destinataires_texte" in refus.json()["champs"]
