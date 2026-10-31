"""Lot 4 — API de l'application mobile (MOB-01 à MOB-08, SEC-10) : connexion en option A (VPN) et B (DMZ, certificat
d'appareil et second facteur), paquet minimal, saisies idempotentes, conflits conservés et signalés, photos."""

from __future__ import annotations

import base64
import hashlib
import uuid
from datetime import date, datetime, time

import pyotp
import pytest
from django.core import mail
from django.core.cache import cache
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import override_settings
from freezegun import freeze_time
from rest_framework.test import APIClient

from apps.finances.tests.outils import grille_votee
from apps.noyau import fichiers
from apps.noyau.chiffrement import chiffrer
from apps.personnel import mobile, services
from apps.personnel.models import Appareil, Incident, SaisieMobile, Vacation
from apps.reservations import services as reservations
from apps.reservations.recurrence import PARIS

from .outils import gardien, seance, site_gardienne

pytestmark = pytest.mark.django_db
MOT_DE_PASSE = "Mot-De-Passe-Annuaire-1"
CERTIFICAT = base64.b64encode(b"certificat-de-recette-du-smartphone").decode()
JPEG = b"\xff\xd8\xff\xe0" + b"photo" * 50


@pytest.fixture(autouse=True)
def environnement(monkeypatch):
    cache.clear()
    monkeypatch.setattr(fichiers, "analyser_clamav", lambda contenu: None)

    def annuaire(request, username, password):
        from apps.habilitations.models import Utilisateur

        return Utilisateur.objects.filter(username=username).first() if password == MOT_DE_PASSE else None

    monkeypatch.setattr(mobile, "authenticate", annuaire)
    with freeze_time("2026-11-10 16:00") as horloge:
        yield horloge


def paris(jour: date, heure: int) -> datetime:
    return datetime.combine(jour, time(heure), tzinfo=PARIS)


JOUR = date(2026, 11, 10)


@pytest.fixture
def terrain():
    site, espace = site_gardienne()
    martin = gardien(site)
    occurrence = seance(espace, JOUR, "18:00", "20:00")
    vacation = Vacation.objects.create(site=site, debut=paris(JOUR, 17), fin=paris(JOUR, 21))
    services.affecter(vacation, martin, acteur="système")
    return {"site": site, "espace": espace, "agent": martin, "seance": occurrence, "vacation": vacation}


def appareil_de(agent) -> uuid.UUID:
    """Identifiant d'appareil tiré par l'application à sa première connexion (stable pour un même agent)."""
    return uuid.uuid5(uuid.NAMESPACE_URL, f"appareil-{agent.pk}")


def _connecter(client: APIClient, agent, **entetes) -> str:
    reponse = client.post(
        "/api/mobile/auth/connexion",
        {
            "identifiant": agent.utilisateur.username,
            "mot_de_passe": MOT_DE_PASSE,
            "appareil": "Smartphone 12",
            "appareil_id": str(appareil_de(agent)),
        },
        format="json",
        **entetes,
    )
    assert reponse.status_code == 200, reponse.json()
    return reponse.json()["jeton"]


def _client_mobile(jeton: str, **entetes) -> APIClient:
    client = APIClient()
    client.credentials(HTTP_AUTHORIZATION=f"Appareil {jeton}", **entetes)
    return client


# --- Option A ----------------------------------------------------------------------------------------------


@override_settings(CANAL="gestion", MOBILE_OPTION="A")
def test_mob07_paquet_minimal_sans_montant_ni_piece_ni_autre_site(terrain, client_api):
    _autre_site, autre_espace = site_gardienne()
    seance(autre_espace, JOUR, "18:00", "20:00")
    grille_votee(terrain["espace"])
    jeton = _connecter(client_api, terrain["agent"])
    paquet = _client_mobile(jeton).get("/api/mobile/paquet")
    assert paquet.status_code == 200
    donnees = paquet.json()
    assert [v["id"] for v in donnees["vacations"]] == [terrain["vacation"].pk]
    assert [s["id"] for s in donnees["seances"]] == [terrain["seance"].pk]
    texte = paquet.content.decode()
    assert "prix" not in texte and "montant" not in texte and "centimes" not in texte and "piece" not in texte
    assert donnees["genere_le"] and donnees["parametres"]["purge_jours"] == 7 and "commune" in donnees["grilles"]
    assert Appareil.objects.get(agent=terrain["agent"]).derniere_synchronisation is not None


@override_settings(CANAL="gestion", MOBILE_OPTION="A")
def test_mob05_saisie_hors_ligne_recue_une_seule_fois(terrain, client_api):
    jeton = _connecter(client_api, terrain["agent"])
    client = _client_mobile(jeton)
    saisie = {
        "uuid": str(uuid.uuid4()),
        "type": "pointage",
        "horodatage": "2026-11-10T17:02:00+01:00",
        "donnees": {"vacation": terrain["vacation"].pk, "moment": "arrivee", "instant": "2026-11-10T17:02:00+01:00"},
    }
    premiere = client.post("/api/mobile/saisies", {"saisies": [saisie]}, format="json").json()["accuses"]
    seconde = client.post("/api/mobile/saisies", {"saisies": [saisie]}, format="json").json()["accuses"]
    assert premiere[0]["statut"] == "acceptee" and seconde[0]["statut"] == "acceptee"
    assert SaisieMobile.objects.count() == 1
    terrain["vacation"].refresh_from_db()
    assert terrain["vacation"].arrivee_reelle == paris(JOUR, 17).replace(minute=2)


@override_settings(CANAL="gestion", MOBILE_OPTION="A")
def test_mob06_saisie_sur_une_seance_annulee_conservee_et_signalee(
    terrain, client_api, environnement, django_capture_on_commit_callbacks
):
    jeton = _connecter(client_api, terrain["agent"])
    reservations.annuler_occurrence(terrain["seance"], acteur="système", motif="Club absent")
    environnement.move_to("2026-11-10 20:30")
    with django_capture_on_commit_callbacks(execute=True):
        accuses = (
            _client_mobile(jeton)
            .post(
                "/api/mobile/saisies",
                {
                    "saisies": [
                        {
                            "uuid": str(uuid.uuid4()),
                            "type": "etat_des_lieux",
                            "horodatage": "2026-11-10T20:10:00+01:00",
                            "donnees": {"occurrence": terrain["seance"].pk, "moment": "sortie", "constat": "conforme"},
                        }
                    ]
                },
                format="json",
            )
            .json()["accuses"]
        )
    assert accuses[0]["statut"] == "conflit" and "signalé" in accuses[0]["message"]
    saisie = SaisieMobile.objects.get()
    assert saisie.statut == "conflit" and saisie.donnees["occurrence"] == terrain["seance"].pk
    assert any("à vérifier" in m.subject for m in mail.outbox)


@override_settings(CANAL="gestion", MOBILE_OPTION="A")
def test_mob03_etat_des_lieux_de_sortie_avec_photo_et_signature(terrain, client_api, environnement):
    from apps.finances.models import EtatDesLieux

    jeton = _connecter(client_api, terrain["agent"])
    client = _client_mobile(jeton)
    photo, signature = uuid.uuid4(), uuid.uuid4()
    assert (
        client.post(
            "/api/mobile/photos", {"uuid": str(photo), "fichier": SimpleUploadedFile("p.jpg", JPEG)}, format="multipart"
        ).status_code
        == 201
    )
    assert (
        client.post(
            "/api/mobile/photos", {"uuid": str(photo), "fichier": SimpleUploadedFile("p.jpg", JPEG)}, format="multipart"
        ).json()["deja_recue"]
        is True
    )
    png = b"\x89PNG\r\n\x1a\n" + b"signature" * 20
    client.post(
        "/api/mobile/photos", {"uuid": str(signature), "fichier": SimpleUploadedFile("signature.png", png)}, format="multipart"
    )
    environnement.move_to("2026-11-10 20:15")
    accuses = client.post(
        "/api/mobile/saisies",
        {
            "saisies": [
                {
                    "uuid": str(uuid.uuid4()),
                    "type": "etat_des_lieux",
                    "horodatage": "2026-11-10T20:10:00+01:00",
                    "donnees": {
                        "occurrence": terrain["seance"].pk,
                        "moment": "sortie",
                        "constat": "degats",
                        "observations": "Filet de but déchiré",
                        "controles": {"Matériel et équipements": False, "Propreté générale": True},
                        "photos": [str(photo)],
                        "signature": str(signature),
                        "signataire": "C. Responsable",
                        "instant": "2026-11-10T20:10:00+01:00",
                    },
                }
            ]
        },
        format="json",
    ).json()["accuses"]
    assert accuses[0]["statut"] == "acceptee", accuses
    etat = EtatDesLieux.objects.get(occurrence=terrain["seance"], moment="sortie")
    assert etat.source == "mobile" and etat.photos.count() == 1 and etat.signature_usager is not None
    assert "Signé par C. Responsable" in etat.observations and "Matériel et équipements" in etat.observations


@override_settings(CANAL="gestion", MOBILE_OPTION="A")
def test_mob04_incident_saisi_hors_ligne(terrain, client_api, environnement):
    jeton = _connecter(client_api, terrain["agent"])
    environnement.move_to("2026-11-10 19:00")
    accuses = (
        _client_mobile(jeton)
        .post(
            "/api/mobile/saisies",
            {
                "saisies": [
                    {
                        "uuid": str(uuid.uuid4()),
                        "type": "incident",
                        "horodatage": "2026-11-10T18:30:00+01:00",
                        "donnees": {
                            "occurrence": terrain["seance"].pk,
                            "nature": "accident",
                            "gravite": "securite",
                            "description": "Cheville foulée, pompiers prévenus",
                        },
                    }
                ]
            },
            format="json",
        )
        .json()["accuses"]
    )
    assert accuses[0]["statut"] == "acceptee"
    incident = Incident.objects.get()
    assert (
        incident.source == "mobile"
        and incident.usager_id == terrain["seance"].reservation.dossier.usager_id
        and incident.signale_par == terrain["agent"]
    )


@override_settings(CANAL="gestion", MOBILE_OPTION="A")
def test_mob_acces_refuses(terrain, client_api):
    assert client_api.get("/api/mobile/paquet").status_code in (401, 403)
    assert _client_mobile("jeton-invente").get("/api/mobile/paquet").status_code == 401
    mauvais = client_api.post(
        "/api/mobile/auth/connexion",
        {"identifiant": terrain["agent"].utilisateur.username, "mot_de_passe": "faux"},
        format="json",
    )
    assert mauvais.status_code == 400
    jeton = _connecter(client_api, terrain["agent"])
    appareil = Appareil.objects.get(agent=terrain["agent"])
    appareil.actif = False
    appareil.save()
    assert _client_mobile(jeton).get("/api/mobile/paquet").status_code == 401
    _autre_site, autre_espace = site_gardienne()
    etrangere = seance(autre_espace, JOUR)
    appareil.actif = True
    appareil.save()
    accuses = (
        _client_mobile(jeton)
        .post(
            "/api/mobile/saisies",
            {
                "saisies": [
                    {
                        "uuid": str(uuid.uuid4()),
                        "type": "incident",
                        "horodatage": "2026-11-10T18:30:00+01:00",
                        "donnees": {"occurrence": etrangere.pk, "description": "Hors de mes sites"},
                    }
                ]
            },
            format="json",
        )
        .json()["accuses"]
    )
    assert accuses[0]["statut"] == "rejetee"


@override_settings(CANAL="gestion", MOBILE_OPTION="A")
def test_per01_fiche_rattachee_au_compte_de_l_annuaire_a_la_premiere_connexion(terrain, client_api):
    from tests.fabriques import agent as compte

    utilisateur = compte("gardien", username="gardien.leroy")
    fiche = gardien(terrain["site"], nom="Leroy", avec_compte=False)
    fiche.identifiant_ad = "Gardien.Leroy"
    fiche.save()
    identifiants = {"identifiant": "gardien.leroy", "mot_de_passe": MOT_DE_PASSE, "appareil_id": str(uuid.uuid4())}
    assert client_api.post("/api/mobile/auth/connexion", identifiants, format="json").status_code == 200
    fiche.refresh_from_db()
    assert fiche.utilisateur == utilisateur
    sans_fiche = compte("gardien", username="gardien.inconnu")
    refus = client_api.post(
        "/api/mobile/auth/connexion", {"identifiant": sans_fiche.username, "mot_de_passe": MOT_DE_PASSE}, format="json"
    )
    assert refus.status_code == 400


@override_settings(CANAL="portail", MOBILE_OPTION="A")
@pytest.mark.urls("config.urls_portail")
def test_sec10_option_a_api_mobile_absente_de_la_dmz(terrain, client_api):
    assert (
        client_api.post("/api/mobile/auth/connexion", {"identifiant": "x", "mot_de_passe": "y"}, format="json").status_code == 404
    )


# --- Option B ----------------------------------------------------------------------------------------------


@override_settings(CANAL="portail", MOBILE_OPTION="B")
@pytest.mark.urls("config.urls_portail")
def test_sec10_option_b_certificat_d_appareil_et_second_facteur(terrain, client_api):
    utilisateur = terrain["agent"].utilisateur
    graine = pyotp.random_base32()
    utilisateur.totp_actif, utilisateur.totp_secret_chiffre = True, chiffrer(graine)
    utilisateur.save()
    empreinte = hashlib.sha256(base64.b64decode(CERTIFICAT)).hexdigest()
    Appareil.objects.create(agent=terrain["agent"], libelle="Smartphone géré", empreinte_certificat=empreinte)
    identifiants = {"identifiant": utilisateur.username, "mot_de_passe": MOT_DE_PASSE}
    # Sans certificat, refus neutre (aucun indice sur le mot de passe).
    assert client_api.post("/api/mobile/auth/connexion", identifiants, format="json").status_code == 400
    etape = client_api.post(
        "/api/mobile/auth/connexion", identifiants, format="json", HTTP_X_CERTIFICAT_APPAREIL=CERTIFICAT
    ).json()
    assert etape["etape"] == "totp"
    session = client_api.post(
        "/api/mobile/auth/totp",
        {"defi": etape["defi"], "code": pyotp.TOTP(graine).now()},
        format="json",
        HTTP_X_CERTIFICAT_APPAREIL=CERTIFICAT,
    ).json()
    assert session["etape"] == "connecte"
    assert _client_mobile(session["jeton"], HTTP_X_CERTIFICAT_APPAREIL=CERTIFICAT).get("/api/mobile/paquet").status_code == 200
    autre = base64.b64encode(b"un-autre-telephone").decode()
    assert _client_mobile(session["jeton"], HTTP_X_CERTIFICAT_APPAREIL=autre).get("/api/mobile/paquet").status_code == 401
    assert _client_mobile(session["jeton"]).get("/api/mobile/paquet").status_code == 401
