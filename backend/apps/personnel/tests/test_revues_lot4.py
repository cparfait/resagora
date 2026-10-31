"""Corrections des revues du lot 4 : besoins (RG-09), trames et règles (PER-01, PER-03, PER-05, PER-06), compteurs
(PER-07), saisies du terrain (MOB-02, MOB-03, MOB-05, MOB-06), appareils et connexion (SEC-10), photos (SEC-07),
cautions (RG-11), incidents (PER-09, RG-14)."""

from __future__ import annotations

import uuid
from datetime import date, datetime, time, timedelta

import pytest
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import override_settings
from freezegun import freeze_time
from rest_framework.test import APIClient

from apps.finances.models import Caution, EtatDesLieux
from apps.noyau import fichiers
from apps.personnel import services
from apps.personnel.models import Absence, Agent, Appareil, Besoin, LigneTrame, SaisieMobile, Trame, Vacation
from apps.referentiel.models import Saison
from apps.reservations import services as reservations
from apps.reservations.models import Occurrence
from apps.reservations.recurrence import PARIS
from tests.fabriques import SiteFabrique, agent

from .outils import gardien, seance, site_gardienne

pytestmark = pytest.mark.django_db
JOUR = date(2026, 11, 10)  # mardi
MOT_DE_PASSE = "Mot-De-Passe-Annuaire-1"


@pytest.fixture(autouse=True)
def environnement(monkeypatch):
    from apps.habilitations.models import Utilisateur

    def authentifier(request=None, username=None, password=None, **_):
        return Utilisateur.objects.filter(username=username).first() if password == MOT_DE_PASSE else None

    monkeypatch.setattr("apps.personnel.mobile.authenticate", authentifier)
    monkeypatch.setattr(fichiers, "analyser_clamav", lambda contenu: None)
    with freeze_time("2026-11-02 10:00") as horloge:
        yield horloge


def paris(jour: date, heure: int, minute: int = 0) -> datetime:
    return datetime.combine(jour, time(heure, minute), tzinfo=PARIS)


def _vacation(site, debut: datetime, fin: datetime, **champs) -> Vacation:
    return Vacation.objects.create(site=site, debut=debut, fin=fin, **champs)


# --- RG-09 : besoins -------------------------------------------------------------------------------------------


def test_rg09_seance_realisee_ne_met_pas_la_vacation_a_revoir():
    site, espace = site_gardienne()
    occurrence = seance(espace, JOUR)
    services.recalculer_besoins(site.pk, JOUR)
    martin = gardien(site)
    vacation = services.affecter(
        services.creer_vacation_pour_besoin(Besoin.objects.get(), acteur="système"), martin, acteur="système"
    )
    Occurrence.objects.filter(pk=occurrence.pk).update(statut="realisee")
    bilan = services.recalculer_besoins(site.pk, JOUR)
    vacation.refresh_from_db()
    assert bilan["supprimes"] == 0 and vacation.statut == "planifiee"
    assert Besoin.objects.get().statut == "couvert"


def test_rg09_vacation_de_trame_rattachee_au_besoin_cree_ensuite(django_capture_on_commit_callbacks):
    site, espace = site_gardienne()
    martin = gardien(site)
    vacation = services.affecter(_vacation(site, paris(JOUR, 17), paris(JOUR, 22)), martin, acteur="système")
    occurrence = seance(espace, JOUR)
    services.recalculer_besoins(site.pk, JOUR)
    besoin = Besoin.objects.get()
    assert besoin.statut == "couvert" and vacation in besoin.vacations.all()
    with django_capture_on_commit_callbacks(execute=True):
        reservations.annuler_occurrence(occurrence, acteur="système", motif="Club absent")
    vacation.refresh_from_db()
    assert vacation.statut == "a_revoir"


def test_rg09_recalcul_du_lendemain_garde_le_besoin_du_soir():
    site, espace = site_gardienne()
    seance(espace, JOUR - timedelta(days=1), "21:30", "23:00")  # lundi soir : besoin 21:15 – 23:15
    services.recalculer_besoins(site.pk, JOUR - timedelta(days=1))
    seance(espace, JOUR, "18:00", "20:00")
    services.recalculer_besoins(site.pk, JOUR)
    assert Besoin.objects.exclude(statut="supprime").count() == 2
    assert set(Besoin.objects.values_list("jour", flat=True)) == {JOUR - timedelta(days=1), JOUR}


# --- PER-03, PER-01, PER-06 : trames ---------------------------------------------------------------------------


def test_per03_trame_n_affecte_pas_un_agent_non_habilite_ou_absent():
    site, _espace = site_gardienne()
    habilite = gardien(site, nom="Martin")
    sans_ssiap = gardien(site, nom="Petit", habilite=False)
    saison = Saison.objects.create(nom="Essai", debut=date(2026, 11, 2), fin=date(2026, 11, 15))
    trame = Trame.objects.create(nom="Semaine type", saison=saison, site=site)
    LigneTrame.objects.create(trame=trame, jour=1, heure_debut=time(17), heure_fin=time(22), agent=habilite)
    LigneTrame.objects.create(trame=trame, jour=3, heure_debut=time(17), heure_fin=time(22), agent=sans_ssiap)
    Absence.objects.create(agent=habilite, debut=paris(JOUR, 0), fin=paris(JOUR, 23, 59), nature="conge")
    bilan = services.appliquer_trame(trame, acteur="système")
    assert bilan["creees"] == 4
    assert Vacation.objects.filter(agent=sans_ssiap).count() == 0
    assert Vacation.objects.filter(agent=habilite).count() == 1, "absent le 10 novembre : la vacation reste à pourvoir"
    assert len(bilan["conflits"]) == 3 and any("absent" in c for c in bilan["conflits"])
    assert any("habilitation" in c for c in bilan["conflits"])


def test_per03_trame_ne_cree_rien_dans_le_passe():
    site, _espace = site_gardienne()
    saison = Saison.objects.create(nom="Essai", debut=date(2026, 10, 19), fin=date(2026, 11, 8))
    trame = Trame.objects.create(nom="Semaine type", saison=saison, site=site)
    LigneTrame.objects.create(trame=trame, jour=1, heure_debut=time(17), heure_fin=time(22))
    services.appliquer_trame(trame, acteur="système")
    assert Vacation.objects.filter(trame=trame).count() == 1  # mardi 3 novembre seulement


def test_per06_absence_ne_libere_pas_une_vacation_pointee_ni_hors_perimetre():
    site, _espace = site_gardienne()
    autre = SiteFabrique()
    martin = gardien(site)
    martin.sites.add(autre)
    pointee = services.affecter(_vacation(site, paris(JOUR, 8), paris(JOUR, 12)), martin, acteur="système")
    Vacation.objects.filter(pk=pointee.pk).update(arrivee_reelle=paris(JOUR, 8, 2))
    ailleurs = services.affecter(_vacation(autre, paris(JOUR, 14), paris(JOUR, 18)), martin, acteur="système")
    martin.sites.remove(autre)  # affecté ailleurs puis rattaché à son seul site : la vacation reste hors périmètre
    planificateur = agent("planificateur", site)
    _absence, liberees = services.saisir_absence(
        martin, acteur=planificateur, debut=paris(JOUR, 0), fin=paris(JOUR, 23, 59), nature="maladie"
    )
    assert liberees == []
    pointee.refresh_from_db()
    ailleurs.refresh_from_db()
    assert pointee.agent == martin and ailleurs.agent == martin and ailleurs.statut == "a_revoir"


# --- PER-05 : modification des horaires ------------------------------------------------------------------------


def test_per05_modifier_les_horaires_exige_le_forcage_motive(client_agent):
    site, _espace = site_gardienne()
    martin = gardien(site)
    vacation = services.affecter(_vacation(site, paris(JOUR, 9), paris(JOUR, 17)), martin, acteur="système")
    client = client_agent(agent("planificateur"))
    url = f"/api/gestion/personnel/vacations/{vacation.pk}"
    longue = {"debut": "2026-11-10T07:00:00+01:00", "fin": "2026-11-10T19:00:00+01:00"}
    refus = client.patch(url, longue, format="json")
    assert refus.status_code == 409 and refus.json()["code"] == "regles_temps_de_travail"
    sans_motif = client.patch(url, {**longue, "forcer": True}, format="json")
    assert sans_motif.status_code == 400 and sans_motif.json()["code"] == "motif_requis"
    force = client.patch(url, {**longue, "forcer": True, "motif": "Tournoi régional, renfort impossible"}, format="json")
    assert force.status_code == 200 and force.json()["forcee"] is True
    Absence.objects.create(
        agent=martin, debut=paris(JOUR + timedelta(days=1), 0), fin=paris(JOUR + timedelta(days=1), 23), nature="conge"
    )
    deplacement = client.patch(url, {"debut": "2026-11-11T09:00:00+01:00", "fin": "2026-11-11T12:00:00+01:00"}, format="json")
    assert deplacement.status_code == 409 and deplacement.json()["code"] == "agent_absent"


# --- PER-07 : compteurs ----------------------------------------------------------------------------------------


def test_per07_vacation_a_cheval_sur_deux_mois_comptee_au_prorata():
    site, _espace = site_gardienne()
    martin = gardien(site)
    nuit = services.affecter(
        _vacation(site, paris(date(2026, 11, 30), 20), paris(date(2026, 12, 1), 2)), martin, acteur="système"
    )
    Vacation.objects.filter(pk=nuit.pk).update(arrivee_reelle=nuit.debut, depart_reel=nuit.fin)
    novembre = services.compteurs([martin], date(2026, 11, 1), date(2026, 11, 30))[0]
    decembre = services.compteurs([martin], date(2026, 12, 1), date(2026, 12, 31))[0]
    assert novembre["planifiees"] == 4 * 60 and decembre["planifiees"] == 2 * 60
    assert novembre["realisees"] + decembre["realisees"] == 6 * 60
    assert novembre["nuit"] + decembre["nuit"] == 5 * 60  # 21 h – 2 h


def test_per07_heures_pointees_comptees_meme_vacation_annulee():
    site, _espace = site_gardienne()
    martin = gardien(site)
    vacation = services.affecter(_vacation(site, paris(JOUR, 17), paris(JOUR, 21)), martin, acteur="système")
    Vacation.objects.filter(pk=vacation.pk).update(arrivee_reelle=paris(JOUR, 17), depart_reel=paris(JOUR, 19))
    services.annuler_vacation(vacation, acteur="système", motif="Séance annulée en cours")
    ligne = services.compteurs([martin], date(2026, 11, 1), date(2026, 11, 30))[0]
    assert ligne["realisees"] == 120 and ligne["planifiees"] == 0


def test_per07_depassement_hebdomadaire_et_astreintes_hors_temps_de_travail():
    site, _espace = site_gardienne()
    martin = gardien(site)
    Agent.objects.filter(pk=martin.pk).update(duree_hebdo_minutes=10 * 60)
    martin.refresh_from_db()
    lundi = date(2026, 11, 9)
    for decalage in range(3):  # 3 × 4 h = 12 h, soit 2 h au-delà de la durée de référence
        services.affecter(
            _vacation(site, paris(lundi + timedelta(days=decalage), 8), paris(lundi + timedelta(days=decalage), 12)),
            martin,
            acteur="système",
        )
    astreinte = _vacation(site, paris(lundi + timedelta(days=5), 0), paris(lundi + timedelta(days=6), 0), type="astreinte")
    services.affecter(astreinte, martin, acteur="système")
    ligne = services.compteurs([martin], date(2026, 11, 1), date(2026, 11, 30))[0]
    assert ligne["planifiees"] == 12 * 60 and ligne["supplementaires"] == 2 * 60 and ligne["astreintes"] == 24 * 60


def test_per07_agent_desactive_reste_dans_l_export(client_agent):
    site, _espace = site_gardienne()
    martin = gardien(site)
    services.affecter(_vacation(site, paris(JOUR, 8), paris(JOUR, 12)), martin, acteur="système")
    Agent.objects.filter(pk=martin.pk).update(actif=False)
    lignes = (
        client_agent(agent("planificateur"))
        .get("/api/gestion/personnel/compteurs", {"du": "2026-11-01", "au": "2026-11-30"})
        .json()
    )
    assert [ligne["agent"] for ligne in lignes] == [martin.pk]


def test_per07_nuit_de_changement_d_heure():
    site, _espace = site_gardienne()
    martin = gardien(site)
    services.affecter(
        _vacation(site, datetime(2026, 10, 24, 21, tzinfo=PARIS), datetime(2026, 10, 25, 7, tzinfo=PARIS)),
        martin,
        acteur="système",
        forcer=True,
        motif="Veille du tournoi, salle occupée la nuit",
    )
    ligne = services.compteurs([martin], date(2026, 10, 1), date(2026, 10, 31))[0]
    assert ligne["planifiees"] == 11 * 60 and ligne["nuit"] == 10 * 60  # 21 h – 6 h : 10 heures réelles


# --- PER-09, RG-14 : incidents -------------------------------------------------------------------------------


def test_per09_incident_sur_une_seance_d_un_autre_site_refuse(client_agent):
    site, _espace = site_gardienne()
    _autre, espace_autre = site_gardienne()
    etrangere = seance(espace_autre, JOUR)
    client = client_agent(agent("planificateur", site))
    reponse = client.post(
        "/api/gestion/personnel/incidents",
        {
            "site": site.pk,
            "occurrence": etrangere.pk,
            "nature": "degradation",
            "description": "Séance d'un autre site",
            "constate_le": "2026-11-10T21:00:00+01:00",
        },
        format="json",
    )
    assert reponse.status_code == 403
    tout_site = client_agent(agent("planificateur")).post(
        "/api/gestion/personnel/incidents",
        {
            "site": site.pk,
            "occurrence": etrangere.pk,
            "nature": "degradation",
            "description": "Séance d'un autre site",
            "constate_le": "2026-11-10T21:00:00+01:00",
        },
        format="json",
    )
    assert tout_site.status_code == 400 and tout_site.json()["code"] == "seance_autre_site"


def test_per09_le_traitement_ne_change_pas_la_seance(client_agent):
    site, espace = site_gardienne()
    occurrence, autre = seance(espace, JOUR), seance(espace, JOUR + timedelta(days=1))
    incident = services.signaler_incident(
        acteur="système",
        source="backoffice",
        site=site,
        nature="degradation",
        gravite="mineur",
        description="Vitre fendue",
        constate_le=paris(JOUR, 21),
        occurrence=occurrence,
    )
    reponse = client_agent(agent("planificateur")).patch(
        f"/api/gestion/personnel/incidents/{incident.pk}",
        {"occurrence": autre.pk, "traite": True, "suite_donnee": "Vitrier commandé"},
        format="json",
    )
    assert reponse.status_code == 200 and reponse.json()["occurrence"] == occurrence.pk and reponse.json()["traite"] is True


# --- Mobile : connexion et appareils (SEC-10) -------------------------------------------------------------------


def _connexion(client: APIClient, martin, appareil_id: uuid.UUID, mot_de_passe: str = MOT_DE_PASSE):
    return client.post(
        "/api/mobile/auth/connexion",
        {"identifiant": martin.utilisateur.username, "mot_de_passe": mot_de_passe, "appareil_id": str(appareil_id)},
        format="json",
    )


@override_settings(CANAL="gestion", MOBILE_OPTION="A")
def test_sec10_appareil_retire_puis_reconnexion_refusee_jusqu_a_autorisation(client_agent):
    site, _espace = site_gardienne()
    martin = gardien(site)
    telephone = uuid.uuid4()
    assert _connexion(APIClient(), martin, telephone).status_code == 200
    appareil = Appareil.objects.get(agent=martin)
    planificateur = client_agent(agent("planificateur"))
    assert planificateur.post(f"/api/gestion/personnel/appareils/{appareil.pk}/retirer").status_code == 200
    assert _connexion(APIClient(), martin, telephone).status_code == 400
    nouveau = uuid.uuid4()
    refus = _connexion(APIClient(), martin, nouveau)
    assert refus.status_code == 400 and refus.json()["code"] == "connexion_refusee"
    en_attente = Appareil.objects.get(agent=martin, identifiant=nouveau)
    assert en_attente.a_autoriser and not en_attente.actif
    assert client_agent(agent("accueil")).post(f"/api/gestion/personnel/appareils/{en_attente.pk}/autoriser").status_code == 403
    assert planificateur.post(f"/api/gestion/personnel/appareils/{en_attente.pk}/autoriser").status_code == 200
    assert _connexion(APIClient(), martin, nouveau).status_code == 200
    assert planificateur.post(f"/api/gestion/personnel/appareils/{appareil.pk}/autoriser").status_code == 409


@override_settings(CANAL="gestion", MOBILE_OPTION="A")
def test_sec10_refus_identiques_avant_le_code_et_limite_par_compte():
    site, _espace = site_gardienne()
    martin = gardien(site)
    faux = _connexion(APIClient(), martin, uuid.uuid4(), mot_de_passe="faux").json()
    Appareil.objects.create(
        agent=martin, identifiant=uuid.uuid4(), libelle="Retiré", actif=False, revoque_le=datetime(2026, 11, 1, tzinfo=PARIS)
    )
    retire = _connexion(APIClient(), martin, uuid.uuid4()).json()
    assert faux == retire
    from django.core.cache import cache

    from apps.personnel.mobile import ECHECS_MAX, _cle_echecs

    sain = gardien(site, nom="Durand")
    _connexion(APIClient(), sain, uuid.uuid4(), mot_de_passe="faux")
    assert cache.get(_cle_echecs(sain.utilisateur.username)) == 1
    cache.set(_cle_echecs(sain.utilisateur.username), ECHECS_MAX)
    assert _connexion(APIClient(), sain, uuid.uuid4()).status_code == 400, "compte bloqué après trop d'échecs"


@override_settings(CANAL="gestion", MOBILE_OPTION="A")
def test_sec10_session_glissante_de_sept_jours(environnement):
    from apps.personnel.models import JetonMobile

    site, _espace = site_gardienne()
    martin = gardien(site)
    jeton = _connexion(APIClient(), martin, uuid.uuid4()).json()["jeton"]
    session = JetonMobile.objects.get()
    assert session.expire_le - session.cree_le <= timedelta(days=7, seconds=1)
    environnement.tick(timedelta(days=6))
    client = APIClient()
    client.credentials(HTTP_AUTHORIZATION=f"Appareil {jeton}")
    assert client.get("/api/mobile/paquet").status_code == 200
    environnement.tick(timedelta(days=6))
    assert client.get("/api/mobile/paquet").status_code == 200, "prolongée par la synchronisation"
    environnement.tick(timedelta(days=8))
    assert client.get("/api/mobile/paquet").status_code == 401


# --- Mobile : saisies terrain -----------------------------------------------------------------------------------


@pytest.fixture
def terrain():
    site, espace = site_gardienne()
    martin = gardien(site)
    occurrence = seance(espace, JOUR, "18:00", "20:00")
    vacation = services.affecter(_vacation(site, paris(JOUR, 17), paris(JOUR, 21)), martin, acteur="système")
    return {"site": site, "espace": espace, "agent": martin, "seance": occurrence, "vacation": vacation}


def _client(terrain) -> APIClient:
    """Session ouverte au moment de la saisie (elle glisse sur 7 jours)."""
    if "client" not in terrain:
        jeton = _connexion(APIClient(), terrain["agent"], uuid.uuid4()).json()["jeton"]
        terrain["client"] = APIClient()
        terrain["client"].credentials(HTTP_AUTHORIZATION=f"Appareil {jeton}")
    return terrain["client"]


def _envoyer(terrain, type_saisie: str, donnees: dict, horodatage: str = "2026-11-10T20:10:00+01:00") -> dict:
    return (
        _client(terrain)
        .post(
            "/api/mobile/saisies",
            {"saisies": [{"uuid": str(uuid.uuid4()), "type": type_saisie, "horodatage": horodatage, "donnees": donnees}]},
            format="json",
        )
        .json()["accuses"][0]
    )


@override_settings(CANAL="gestion", MOBILE_OPTION="A")
def test_mob02_pointage_borne_a_la_vacation_et_premier_pointage_conserve(terrain, environnement):
    environnement.move_to("2026-11-10 22:00")
    v = terrain["vacation"].pk
    assert (
        _envoyer(terrain, "pointage", {"vacation": v, "moment": "arrivee", "instant": "2026-11-10T06:00:00+01:00"})["statut"]
        == "rejetee"
    )
    assert (
        _envoyer(terrain, "pointage", {"vacation": v, "moment": "arrivee", "instant": "2026-11-10T16:55:00+01:00"})["statut"]
        == "acceptee"
    )
    assert (
        _envoyer(terrain, "pointage", {"vacation": v, "moment": "depart", "instant": "2026-11-10T21:05:00+01:00"})["statut"]
        == "acceptee"
    )
    reecrit = _envoyer(terrain, "pointage", {"vacation": v, "moment": "depart", "instant": "2026-11-10T23:30:00+01:00"})
    assert reecrit["statut"] in ("conflit", "rejetee")
    futur = _envoyer(terrain, "pointage", {"vacation": v, "moment": "depart", "instant": "2026-11-10T23:55:00+01:00"})
    assert futur["statut"] == "rejetee"
    terrain["vacation"].refresh_from_db()
    assert terrain["vacation"].depart_reel == paris(JOUR, 21, 5)


@override_settings(CANAL="gestion", MOBILE_OPTION="A")
def test_mob06_pointage_sur_une_seance_annulee_conserve_et_signale(terrain, environnement, django_capture_on_commit_callbacks):
    with django_capture_on_commit_callbacks(execute=True):
        reservations.annuler_occurrence(terrain["seance"], acteur="système", motif="Club absent")
    environnement.move_to("2026-11-10 18:00")
    accuse = _envoyer(
        terrain, "pointage", {"vacation": terrain["vacation"].pk, "moment": "arrivee", "instant": "2026-11-10T17:00:00+01:00"}
    )
    assert accuse["statut"] == "conflit"
    terrain["vacation"].refresh_from_db()
    assert terrain["vacation"].arrivee_reelle == paris(JOUR, 17)


@override_settings(CANAL="gestion", MOBILE_OPTION="A")
def test_mob03_sortie_avant_la_fin_de_seance_refusee_et_grille_non_conforme_vaut_degats(terrain, environnement):
    environnement.move_to("2026-11-10 21:00")
    occurrence = terrain["seance"].pk
    tot = _envoyer(
        terrain,
        "etat_des_lieux",
        {"occurrence": occurrence, "moment": "sortie", "constat": "conforme", "instant": "2026-11-10T18:05:00+01:00"},
    )
    assert tot["statut"] == "rejetee"
    accuse = _envoyer(
        terrain,
        "etat_des_lieux",
        {
            "occurrence": occurrence,
            "moment": "sortie",
            "constat": "conforme",
            "controles": {"Sol et revêtement": False},
            "instant": "2026-11-10T20:10:00+01:00",
        },
    )
    assert accuse["statut"] == "acceptee"
    assert EtatDesLieux.objects.get(occurrence_id=occurrence, moment="sortie").constat == "degats"


@override_settings(CANAL="gestion", MOBILE_OPTION="A")
def test_mob03_etat_des_lieux_hors_de_ses_vacations_refuse(terrain, environnement):
    lendemain = seance(terrain["espace"], JOUR + timedelta(days=1))
    environnement.move_to("2026-11-11 21:00")
    accuse = _envoyer(
        terrain,
        "etat_des_lieux",
        {"occurrence": lendemain.pk, "moment": "sortie", "constat": "conforme", "instant": "2026-11-11T20:05:00+01:00"},
        horodatage="2026-11-11T20:05:00+01:00",
    )
    assert accuse["statut"] == "rejetee" and "vacations" in accuse["message"]


@override_settings(CANAL="gestion", MOBILE_OPTION="A")
def test_mob05_saisie_malformee_rejetee_seule(terrain, environnement):
    environnement.move_to("2026-11-10 21:00")
    reponse = _client(terrain).post(
        "/api/mobile/saisies",
        {
            "saisies": [
                {"uuid": str(uuid.uuid4()), "type": "etat_des_lieux", "donnees": {"occurrence": ["abc"], "moment": "sortie"}},
                {
                    "uuid": str(uuid.uuid4()),
                    "type": "pointage",
                    "horodatage": "2026-11-10T17:00:00+01:00",
                    "donnees": {"vacation": terrain["vacation"].pk, "moment": "arrivee", "instant": "2026-11-10T17:00:00+01:00"},
                },
            ]
        },
        format="json",
    )
    assert reponse.status_code == 200
    assert [a["statut"] for a in reponse.json()["accuses"]] == ["rejetee", "acceptee"]
    assert SaisieMobile.objects.count() == 2


@override_settings(CANAL="gestion", MOBILE_OPTION="A")
def test_sec07_photo_mobile_toujours_analysee_et_sans_metadonnees(terrain, monkeypatch):
    analyses: list[bytes] = []
    monkeypatch.setattr(fichiers, "analyser_clamav", analyses.append)
    png = b"\x89PNG\r\n\x1a\n" + (13).to_bytes(4, "big") + b"IHDR" + b"\x00" * 13 + b"\x00" * 4
    png += (
        (9).to_bytes(4, "big")
        + b"tEXt"
        + b"Author\x00X"
        + b"\x00" * 2
        + b"\x00" * 4
        + (0).to_bytes(4, "big")
        + b"IEND"
        + b"\x00" * 4
    )
    reponse = _client(terrain).post(
        "/api/mobile/photos",
        {"uuid": str(uuid.uuid4()), "fichier": SimpleUploadedFile("signature.png", png)},
        format="multipart",
        HTTP_X_FICHIER_CONTROLE="clamav",
        HTTP_X_EMPREINTE_SHA256="0" * 64,
    )
    assert reponse.status_code == 201
    assert len(analyses) == 1 and b"tEXt" not in analyses[0]


# --- RG-11 : cautions -----------------------------------------------------------------------------------------


def test_rg11_degats_sur_une_seance_intermediaire_bloquent_la_restitution(environnement, modeles_documents):
    from apps.documents import services as documents
    from apps.finances import cautions
    from apps.finances.tests.outils import PDF, grille_votee
    from apps.reservations.tests.outils import reserver
    from tests.fabriques import EspaceFabrique, usager_avec_contact

    environnement_pdf = pytest.MonkeyPatch()
    environnement_pdf.setattr(documents, "convertir_en_pdfa", lambda nom, docx, transport=None: PDF)
    espace = EspaceFabrique(nom="Salle des fêtes")
    grille_votee(espace)
    usager = usager_avec_contact(type="particulier", nom="Particulier de test", commune="Châtillon")
    reservation = reserver(
        espace,
        JOUR,
        "14:00",
        "18:00",
        usager=usager,
        type_code="location",
        recurrence="FREQ=WEEKLY",
        exclure_vacances=False,
        date_fin=JOUR + timedelta(days=7),
    )
    reservations.valider(reservation, acteur=agent("gestionnaire"))
    caution = Caution.objects.get(reservation=reservation)
    premiere, derniere = list(reservation.occurrences.order_by("debut"))
    regie = agent("regisseur")
    environnement.move_to("2026-11-10 18:30")
    cautions.constater_sortie(premiere, acteur=regie, constat="degats", observations="Parquet rayé")
    cautions.recevoir(caution, acteur=regie, mode="cheque", reference="CHQ-001")
    environnement.move_to("2026-11-17 18:30")
    cautions.constater_sortie(derniere, acteur=regie, constat="conforme")
    caution.refresh_from_db()
    assert caution.statut == "recue"
    with pytest.raises(Exception, match="dégâts"):
        cautions.restituer(caution, acteur=regie)
    environnement_pdf.undo()


# --- PER-08 : iCal ---------------------------------------------------------------------------------------------


def test_per08_flux_ical_ferme_pour_un_agent_desactive(client_api):
    site, _espace = site_gardienne()
    martin = gardien(site)
    jeton = services.emettre_jeton_ical(martin, acteur="système")
    assert client_api.get(f"/api/gestion/personnel/ical/{jeton}.ics").status_code == 200
    Agent.objects.filter(pk=martin.pk).update(actif=False)
    assert client_api.get(f"/api/gestion/personnel/ical/{jeton}.ics").status_code == 404
