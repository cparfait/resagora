"""Lot 4 — personnel : habilitations (PER-01), besoins fusionnés (PER-02), trames (PER-03), affectation et remplaçant
(PER-04), règles de temps de travail et forçage (PER-05), absences (PER-06), compteurs et export paie (PER-07), iCal
(PER-08), incidents (PER-09), recalcul et notification (RG-09), pas de chevauchement (RG-10)."""

from __future__ import annotations

import csv
import io
from datetime import date, datetime, time

import pytest
from django.core import mail
from django.db import DatabaseError, transaction
from freezegun import freeze_time

from apps.personnel import services
from apps.personnel.models import Absence, Agent, Besoin, HabilitationAgent, LigneTrame, Trame, TypeHabilitation, Vacation
from apps.referentiel.models import Saison
from apps.reservations import services as reservations
from apps.reservations.recurrence import PARIS
from tests.fabriques import SiteFabrique, agent

from .outils import gardien, seance, site_gardienne

pytestmark = pytest.mark.django_db


@pytest.fixture(autouse=True)
def maintenant():
    with freeze_time("2026-11-02 10:00"):
        yield


def paris(jour: date, heure: int, minute: int = 0) -> datetime:
    return datetime.combine(jour, time(heure, minute), tzinfo=PARIS)


JOUR = date(2026, 11, 10)


# --- PER-02, RG-09 ---------------------------------------------------------------------------------------


def test_per02_deux_creneaux_contigus_forment_un_seul_besoin():
    site, espace = site_gardienne()
    seance(espace, JOUR, "18:00", "20:00")
    seance(espace, JOUR, "20:00", "22:00")
    bilan = services.recalculer_besoins(site.pk, JOUR)
    besoins = list(Besoin.objects.exclude(statut="supprime"))
    assert bilan["crees"] == 1 and len(besoins) == 1
    assert besoins[0].debut == paris(JOUR, 17, 45) and besoins[0].fin == paris(JOUR, 22, 15)
    assert besoins[0].occurrences.count() == 2 and besoins[0].statut == "a_couvrir"


def test_rg09_annuler_un_creneau_gardienne_met_la_vacation_a_revoir_et_previent_l_agent(django_capture_on_commit_callbacks):
    site, espace = site_gardienne()
    occurrence = seance(espace, JOUR)
    services.recalculer_besoins(site.pk, JOUR)
    besoin = Besoin.objects.get()
    vacation = services.creer_vacation_pour_besoin(besoin, acteur="système")
    martin = gardien(site)
    with django_capture_on_commit_callbacks(execute=True):
        services.affecter(vacation, martin, acteur="système")
    besoin.refresh_from_db()
    assert besoin.statut == "couvert"
    with django_capture_on_commit_callbacks(execute=True):
        reservations.annuler_occurrence(occurrence, acteur="système", motif="Club absent")
    vacation.refresh_from_db()
    assert vacation.statut == "a_revoir" and "annulées" in vacation.signalement
    assert any(martin.courriel in m.to and "modifiée" in m.subject for m in mail.outbox)


# --- PER-01, PER-04, PER-05, RG-10 ----------------------------------------------------------------------


def _vacation(site, debut: datetime, fin: datetime) -> Vacation:
    return Vacation.objects.create(site=site, debut=debut, fin=fin)


def test_per01_habilitation_expiree_exclut_l_agent_des_propositions():
    site, _espace = site_gardienne()
    valide = gardien(site, nom="Durand")
    expire = gardien(site, nom="Petit", habilite=False)
    HabilitationAgent.objects.create(
        agent=expire,
        type=TypeHabilitation.objects.get(code="ssiap1"),
        obtenue_le=date(2020, 1, 1),
        valide_jusqu_au=date(2026, 6, 30),
    )
    vacation = _vacation(site, paris(JOUR, 8), paris(JOUR, 12))
    assert [c["agent"] for c in services.candidats(vacation)] == [valide]
    with pytest.raises(Exception) as refus:
        services.affecter(vacation, expire, acteur="système")
    assert "habilitation" in str(refus.value)


def test_rg10_deux_vacations_simultanees_pour_un_agent_refusees():
    site, _espace = site_gardienne()
    martin = gardien(site)
    premiere = _vacation(site, paris(JOUR, 8), paris(JOUR, 12))
    seconde = _vacation(site, paris(JOUR, 10), paris(JOUR, 14))
    services.affecter(premiere, martin, acteur="système")
    with pytest.raises(Exception) as refus:
        services.affecter(seconde, martin, acteur="système")
    assert "RG-10" in str(refus.value)
    with pytest.raises(DatabaseError), transaction.atomic():
        Vacation.objects.create(site=site, agent=martin, debut=paris(JOUR, 11), fin=paris(JOUR, 13), statut="planifiee")


def test_per05_vacation_de_plus_de_10_heures_signalee_et_forcage_motive_trace(client_agent):
    site, _espace = site_gardienne()
    martin = gardien(site)
    vacation = _vacation(site, paris(JOUR, 7), paris(JOUR, 18))
    planificateur = client_agent(agent("planificateur"))
    refus = planificateur.post(f"/api/gestion/personnel/vacations/{vacation.pk}/affecter", {"agent": martin.pk}, format="json")
    assert refus.status_code == 409 and refus.json()["code"] == "regles_temps_de_travail"
    assert any(v["code"] == "duree_quotidienne" for v in refus.json()["details"]["violations"])
    sans_motif = planificateur.post(
        f"/api/gestion/personnel/vacations/{vacation.pk}/affecter", {"agent": martin.pk, "forcer": True}, format="json"
    )
    assert sans_motif.status_code == 400
    force = planificateur.post(
        f"/api/gestion/personnel/vacations/{vacation.pk}/affecter",
        {"agent": martin.pk, "forcer": True, "motif": "Tournoi régional, aucun remplaçant disponible"},
        format="json",
    )
    assert force.status_code == 200 and force.json()["forcee"] is True and force.json()["motif_forcage"]
    from apps.audit.models import JournalAudit

    assert JournalAudit.objects.filter(action="affecter_vacation", objet_id=str(vacation.pk)).exists()


def test_per04_proposer_un_remplacant_a_un_gardien_absent():
    site, _espace = site_gardienne()
    martin, durand = gardien(site, nom="Martin"), gardien(site, nom="Durand")
    vacation = _vacation(site, paris(JOUR, 17), paris(JOUR, 22))
    services.affecter(vacation, martin, acteur="système")
    _absence, liberees = services.saisir_absence(
        martin, acteur="système", debut=paris(JOUR, 0), fin=paris(JOUR, 23, 59), nature="maladie"
    )
    vacation.refresh_from_db()
    assert liberees == [vacation] and vacation.agent is None and vacation.statut == "a_pourvoir"
    propositions = services.candidats(vacation)
    assert [c["agent"] for c in propositions] == [durand]
    assert services.affecter(vacation, durand, acteur="système").agent == durand


def test_per06_absence_rend_la_vacation_non_couverte(client_agent):
    site, espace = site_gardienne()
    seance(espace, JOUR)
    services.recalculer_besoins(site.pk, JOUR)
    besoin = Besoin.objects.get()
    martin = gardien(site)
    services.affecter(services.creer_vacation_pour_besoin(besoin, acteur="système"), martin, acteur="système")
    besoin.refresh_from_db()
    assert besoin.statut == "couvert"
    reponse = client_agent(agent("planificateur")).post(
        "/api/gestion/personnel/absences",
        {"agent": martin.pk, "debut": "2026-11-10T00:00:00+01:00", "fin": "2026-11-11T00:00:00+01:00", "nature": "conge"},
        format="json",
    )
    assert reponse.status_code == 201 and len(reponse.json()["vacations_liberees"]) == 1
    besoin.refresh_from_db()
    assert besoin.statut == "a_couvrir"
    assert client_agent(agent("accueil")).post("/api/gestion/personnel/absences", {}, format="json").status_code == 403


# --- PER-03 ------------------------------------------------------------------------------------------------


def test_per03_appliquer_une_trame_sur_la_saison():
    site, _espace = site_gardienne()
    martin = gardien(site)
    saison = Saison.objects.create(nom="Essai", debut=date(2026, 11, 2), fin=date(2026, 11, 15))
    trame = Trame.objects.create(nom="Semaine type", saison=saison, site=site)
    LigneTrame.objects.create(trame=trame, jour=1, heure_debut=time(17), heure_fin=time(22), agent=martin)
    LigneTrame.objects.create(trame=trame, jour=3, heure_debut=time(17), heure_fin=time(22))
    bilan = services.appliquer_trame(trame, acteur="système")
    assert bilan["creees"] == 4 and bilan["conflits"] == []
    assert Vacation.objects.filter(trame=trame, agent=martin, statut="planifiee").count() == 2
    assert Vacation.objects.filter(trame=trame, agent__isnull=True, statut="a_pourvoir").count() == 2
    assert services.appliquer_trame(trame, acteur="système")["creees"] == 0, "rejouable sans doublon"


# --- PER-07 ------------------------------------------------------------------------------------------------


def test_per07_compteurs_du_mois_et_export_paie(client_agent):
    site, _espace = site_gardienne()
    martin = gardien(site)
    nuit = _vacation(site, paris(date(2026, 11, 7), 20), paris(date(2026, 11, 8), 1))  # samedi soir → dimanche
    services.affecter(nuit, martin, acteur="système")
    Vacation.objects.filter(pk=nuit.pk).update(
        arrivee_reelle=paris(date(2026, 11, 7), 20, 5), depart_reel=paris(date(2026, 11, 8), 1)
    )
    sup = Vacation.objects.create(
        site=site, debut=paris(date(2026, 11, 11), 9), fin=paris(date(2026, 11, 11), 12), type="supplementaire"
    )
    services.affecter(sup, martin, acteur="système")
    ligne = services.compteurs([martin], date(2026, 11, 1), date(2026, 11, 30))[0]
    assert ligne["planifiees"] == 8 * 60 and ligne["realisees"] == 4 * 60 + 55 and ligne["supplementaires"] == 180
    assert ligne["nuit"] == 4 * 60 and ligne["dimanches_feries"] == 60 + 180  # dimanche 0 h–1 h, 11 novembre férié
    export = client_agent(agent("planificateur")).get(
        "/api/gestion/personnel/compteurs", {"du": "2026-11-01", "au": "2026-11-30", "export": "csv"}
    )
    lignes = list(csv.reader(io.StringIO(export.content.decode("utf-8-sig")), delimiter=";"))
    assert lignes[1][0] == martin.matricule and lignes[1][5] == "8,00"
    assert (
        client_agent(agent("accueil"))
        .get("/api/gestion/personnel/compteurs", {"du": "2026-11-01", "au": "2026-11-30"})
        .status_code
        == 403
    )


# --- PER-08 ------------------------------------------------------------------------------------------------


def test_per08_abonnement_ical_puis_revocation(client_agent, client_api):
    site, _espace = site_gardienne()
    martin = gardien(site)
    services.affecter(_vacation(site, paris(JOUR, 17), paris(JOUR, 22)), martin, acteur="système")
    planificateur = client_agent(agent("planificateur"))
    url = planificateur.post(f"/api/gestion/personnel/agents/{martin.pk}/ical").json()["url"]
    chemin = url.split("testserver")[-1]
    flux = client_api.get(chemin)
    assert flux.status_code == 200 and b"BEGIN:VEVENT" in flux.content and b"DTSTART:20261110T160000Z" in flux.content
    planificateur.post(f"/api/gestion/personnel/agents/{martin.pk}/revoquer-ical")
    assert client_api.get(chemin).status_code == 404


# --- PER-09 ------------------------------------------------------------------------------------------------


def test_per09_incident_rattache_a_la_seance_et_a_l_usager(client_agent, django_capture_on_commit_callbacks):
    site, espace = site_gardienne()
    occurrence = seance(espace, JOUR)
    with django_capture_on_commit_callbacks(execute=True):
        reponse = client_agent(agent("planificateur")).post(
            "/api/gestion/personnel/incidents",
            {
                "site": site.pk,
                "occurrence": occurrence.pk,
                "nature": "degradation",
                "gravite": "majeur",
                "description": "Panier de basket arraché",
                "constate_le": "2026-11-10T21:00:00+01:00",
            },
            format="json",
        )
    assert reponse.status_code == 201 and reponse.json()["usager_nom"] == occurrence.reservation.dossier.usager.nom
    assert any("Incident" in m.subject for m in mail.outbox)
    autre = SiteFabrique()
    hors = client_agent(agent("planificateur", autre)).post(
        "/api/gestion/personnel/incidents",
        {"site": site.pk, "nature": "autre", "description": "Hors périmètre", "constate_le": "2026-11-10T21:00:00+01:00"},
        format="json",
    )
    assert hors.status_code == 403


# --- Droits (RG-14) -----------------------------------------------------------------------------------------


def test_rg14_agents_et_vacations_lus_dans_le_perimetre(client_agent):
    site, _espace = site_gardienne()
    martin = gardien(site)
    vacation = _vacation(site, paris(JOUR, 17), paris(JOUR, 22))
    dans = client_agent(agent("planificateur", site))
    assert dans.get(f"/api/gestion/personnel/agents/{martin.pk}").status_code == 200
    assert dans.get(f"/api/gestion/personnel/vacations/{vacation.pk}").status_code == 200
    hors = client_agent(agent("planificateur", SiteFabrique()))
    assert hors.get(f"/api/gestion/personnel/agents/{martin.pk}").status_code == 404
    assert (
        hors.post(f"/api/gestion/personnel/vacations/{vacation.pk}/affecter", {"agent": martin.pk}, format="json").status_code
        == 404
    )
    assert client_agent(agent("gardien")).get("/api/gestion/personnel/vacations").status_code == 403
    assert Agent.objects.count() == 1 and Absence.objects.count() == 0
