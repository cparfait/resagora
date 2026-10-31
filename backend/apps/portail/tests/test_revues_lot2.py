"""Corrections des revues du lot 2 côté portail : confidentialité (POR-02), verrous (SEC-04), invitations sans
énumération ni reprise de compte, accès refusés objet par objet (RG-14, règle 2), campagnes (PLA-05), annulations
(RG-08), SMS vérifié (COM-05), changement d'adresse."""

from __future__ import annotations

import re
from datetime import date

import pyotp
import pytest
from django.core import mail
from django.core.cache import cache
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import override_settings
from freezegun import freeze_time

from apps.communication.models import Notification, PreferenceNotification
from apps.comptes.models import CompteUsager
from apps.noyau.chiffrement import chiffrer
from apps.reservations.models import Campagne, Occurrence, TypeReservation
from apps.reservations.tests.outils import reserver, valider_systeme
from apps.usagers.models import Rattachement
from tests.fabriques import ContactFabrique, EspaceFabrique, SiteFabrique, agent, saison_2026

from .outils import MOT_DE_PASSE, client_contact, compte_actif

pytestmark = [pytest.mark.django_db, pytest.mark.urls("config.urls_portail")]
PDF = b"%PDF-1.7\n1 0 obj<<>>endobj\ntrailer<<>>\n%%EOF"


@pytest.fixture(autouse=True)
def maintenant():
    cache.clear()
    with freeze_time("2026-11-01 10:00"):
        yield


def _usager(compte: CompteUsager):
    return compte.contact.rattachements.first().usager


# --- POR-02 : aucun autre usager révélé ------------------------------------------------------------------


@override_settings(CANAL="portail")
def test_por02_signalement_interne_jamais_expose_au_portail():
    compte = compte_actif()
    reservation = valider_systeme(reserver(EspaceFabrique(), date(2026, 11, 10), "18:00", "20:00", usager=_usager(compte)))
    Occurrence.objects.filter(reservation=reservation).update(
        signalement="Conflit à traiter : Créneau déjà occupé (Jeanne Secret, dossier D1999-04242)."
    )
    reponse = client_contact(compte).get(f"/api/portail/dossiers/{reservation.dossier_id}")
    assert reponse.status_code == 200
    assert "Jeanne Secret" not in reponse.content.decode() and "D1999-04242" not in reponse.content.decode()
    assert "Séance à revoir" in reponse.content.decode()


# --- SEC-04 : verrou progressif sur toutes les vérifications de secret -----------------------------------------


@override_settings(CANAL="portail")
def test_sec04_codes_totp_faux_verrouillent_meme_avec_le_bon_mot_de_passe(client_api):
    compte = compte_actif()
    graine = pyotp.random_base32()
    CompteUsager.objects.filter(pk=compte.pk).update(totp_actif=True, totp_secret_chiffre=chiffrer(graine))
    statuts = []
    for _ in range(6):
        etape = client_api.post(
            "/api/portail/auth/connexion", {"identifiant": compte.identifiant, "mot_de_passe": MOT_DE_PASSE}, format="json"
        )
        if etape.status_code == 429:
            statuts.append(429)
            break
        defi = etape.json()["defi"]
        statuts.append(client_api.post("/api/portail/auth/totp", {"defi": defi, "code": "000000"}, format="json").status_code)
    assert 429 in statuts, statuts


@override_settings(CANAL="portail")
def test_sec04_mot_de_passe_actuel_faux_verrouille_le_compte():
    compte = compte_actif()
    client = client_contact(compte)
    codes = [
        client.post(
            "/api/portail/compte/mot-de-passe", {"actuel": f"faux-{i}", "nouveau": "Bonne-Raquette-2027!"}, format="json"
        ).status_code
        for i in range(6)
    ]
    assert codes[:4] == [400] * 4 and 429 in codes
    compte.refresh_from_db()
    assert compte.verrouille_jusqu_au is not None
    bloque = client.post(
        "/api/portail/compte/mot-de-passe", {"actuel": MOT_DE_PASSE, "nouveau": "Bonne-Raquette-2027!"}, format="json"
    )
    assert bloque.status_code == 429


@override_settings(CANAL="portail")
def test_sec04_activation_totp_exige_le_mot_de_passe():
    compte = compte_actif()
    client = client_contact(compte)
    client.get("/api/portail/compte/totp")
    from apps.noyau.chiffrement import dechiffrer

    graine = dechiffrer(CompteUsager.objects.get(pk=compte.pk).totp_en_attente_chiffre)
    sans = client.post("/api/portail/compte/totp", {"code": pyotp.TOTP(graine).now(), "mot_de_passe": "faux"}, format="json")
    assert sans.status_code == 400
    assert CompteUsager.objects.get(pk=compte.pk).totp_actif is False


# --- Invitations : ni énumération ni reprise de compte -------------------------------------------------------


@override_settings(CANAL="portail")
def test_sec04_invitation_sans_enumeration_des_comptes(django_capture_on_commit_callbacks):
    compte = compte_actif()
    autre = compte_actif()
    url = f"/api/portail/usagers/{_usager(compte).pk}/contacts"
    with django_capture_on_commit_callbacks(execute=True):
        connu = client_contact(compte).post(url, {"prenom": "A", "nom": "B", "courriel": autre.identifiant}, format="json")
        inconnu = client_contact(compte).post(url, {"prenom": "C", "nom": "D", "courriel": "nouveau@exemple.test"}, format="json")
    assert connu.status_code == inconnu.status_code == 201 and connu.json()["message"] == inconnu.json()["message"]
    assert any(autre.identifiant in m.to and "ajouté comme contact" in m.subject for m in mail.outbox)
    assert not CompteUsager.objects.filter(contact__courriel=autre.identifiant).exclude(pk=autre.pk).exists()


@pytest.mark.urls("config.urls_gestion")
def test_sec04_compte_ouvert_jamais_reinvite_ni_adresse_changee_par_un_agent(client_agent):
    compte = compte_actif()
    agent_usagers = client_agent(agent("gestionnaire"))
    reinvitation = agent_usagers.post("/api/gestion/usagers/comptes/inviter", {"contact": compte.contact_id}, format="json")
    assert reinvitation.status_code == 409 and reinvitation.json()["code"] == "compte_existant"
    detournement = agent_usagers.patch(
        f"/api/gestion/usagers/contacts/{compte.contact_id}", {"courriel": "agent.malveillant@exemple.test"}, format="json"
    )
    assert detournement.status_code == 400
    sans_compte = ContactFabrique()
    assert (
        agent_usagers.patch(
            f"/api/gestion/usagers/contacts/{sans_compte.pk}", {"courriel": "nouvelle@exemple.test"}, format="json"
        ).status_code
        == 200
    )


@override_settings(CANAL="portail")
def test_sec04_changement_d_adresse_confirme_par_la_nouvelle_et_signale_a_l_ancienne(
    client_api, django_capture_on_commit_callbacks
):
    compte = compte_actif()
    ancienne = compte.identifiant
    client = client_contact(compte)
    assert (
        client.post(
            "/api/portail/compte/courriel", {"nouveau": "nouvelle@exemple.test", "mot_de_passe": "faux"}, format="json"
        ).status_code
        == 400
    )
    with django_capture_on_commit_callbacks(execute=True):
        demande = client.post(
            "/api/portail/compte/courriel", {"nouveau": "nouvelle@exemple.test", "mot_de_passe": MOT_DE_PASSE}, format="json"
        )
    assert demande.status_code == 200
    lien = next(m.body for m in mail.outbox if "nouvelle@exemple.test" in m.to)
    jeton = re.search(r"/confirmer-adresse#jeton=([\w-]+)", lien).group(1)
    with django_capture_on_commit_callbacks(execute=True):
        assert (
            client_api.post("/api/portail/auth/confirmation-nouvelle-adresse", {"jeton": jeton}, format="json").status_code == 200
        )
    compte.refresh_from_db()
    assert compte.identifiant == "nouvelle@exemple.test" and compte.contact.courriel == "nouvelle@exemple.test"
    assert any(ancienne in m.to and "modifiée" in m.subject for m in mail.outbox)
    assert client.get("/api/portail/compte").status_code == 401, "sessions fermées"


# --- RG-14 / règle 2 : un autre usager n'accède à rien ----------------------------------------------------------


@override_settings(CANAL="portail")
def test_rg14_acces_refuses_aux_objets_d_un_autre_usager():
    proprietaire = compte_actif()
    usager = _usager(proprietaire)
    reservation = valider_systeme(reserver(EspaceFabrique(), date(2026, 11, 10), "18:00", "20:00", usager=usager))
    dossier = reservation.dossier
    seance = reservation.occurrences.first()
    notification = Notification.objects.create(destinataire="x@exemple.test", contact=proprietaire.contact, sujet="s", corps="c")
    intrus = client_contact(compte_actif())
    refus = [
        ("patch", f"/api/portail/usagers/{usager.pk}", {"commune": "Ailleurs"}),
        ("get", f"/api/portail/usagers/{usager.pk}/contacts", None),
        ("post", f"/api/portail/usagers/{usager.pk}/contacts", {"prenom": "A", "nom": "B", "courriel": "a@exemple.test"}),
        ("get", f"/api/portail/usagers/{usager.pk}/pieces", None),
        ("get", f"/api/portail/usagers/{usager.pk}/documents", None),
        ("patch", f"/api/portail/dossiers/{dossier.pk}", {"objet": "x"}),
        ("delete", f"/api/portail/dossiers/{dossier.pk}", None),
        ("post", f"/api/portail/dossiers/{dossier.pk}/envoyer", None),
        ("post", f"/api/portail/dossiers/{dossier.pk}/annuler", {"motif": "intrusion"}),
        ("post", f"/api/portail/dossiers/{dossier.pk}/occurrences/{seance.pk}/annuler", {"motif": "intrusion"}),
        ("get", f"/api/portail/dossiers/{dossier.pk}/documents", None),
        ("get", f"/api/portail/dossiers/{dossier.pk}/messages", None),
        ("post", f"/api/portail/notifications/{notification.pk}/lue", None),
    ]
    for methode, url, corps in refus:
        reponse = getattr(intrus, methode)(url, corps, format="json") if corps is not None else getattr(intrus, methode)(url)
        assert reponse.status_code == 404, (methode, url, reponse.status_code)
    depot = intrus.post(
        f"/api/portail/usagers/{usager.pk}/pieces",
        {"type_piece": 1, "fichier": SimpleUploadedFile("a.pdf", PDF)},
        format="multipart",
    )
    assert depot.status_code == 404
    type_ponctuel = TypeReservation.objects.get(code="ponctuelle")
    cree = intrus.post("/api/portail/dossiers", {"usager": usager.pk, "type_reservation": type_ponctuel.pk}, format="json")
    assert cree.status_code == 404
    assert intrus.get("/api/portail/types-demande", {"usager": usager.pk}).status_code == 404
    seance_autre = valider_systeme(reserver(EspaceFabrique(), date(2026, 11, 12), "18:00", "20:00")).occurrences.first()
    melange = client_contact(proprietaire).post(
        f"/api/portail/dossiers/{dossier.pk}/occurrences/{seance_autre.pk}/annuler", {"motif": "x"}, format="json"
    )
    assert melange.status_code == 404


@override_settings(CANAL="portail")
def test_por01_co_contact_ne_voit_ni_ne_modifie_les_coordonnees_des_autres():
    principal = compte_actif()
    usager = _usager(principal)
    secondaire = ContactFabrique()
    Rattachement.objects.create(usager=usager, contact=secondaire, role="referent")
    compte_secondaire = CompteUsager.objects.create(
        contact=secondaire, identifiant=secondaire.courriel, mot_de_passe=principal.mot_de_passe, statut="actif"
    )
    vue_secondaire = client_contact(compte_secondaire).get(f"/api/portail/usagers/{usager.pk}/contacts").json()
    fiche_principal = next(c for c in vue_secondaire if c["principal"])
    assert "courriel" not in fiche_principal and "telephone" not in fiche_principal
    url = f"/api/portail/usagers/{usager.pk}/contacts/{principal.contact_id}"
    assert client_contact(compte_secondaire).patch(url, {"peut_signer": False}, format="json").status_code == 403
    assert client_contact(compte_secondaire).delete(url).status_code == 403
    vue_principal = client_contact(principal).get(f"/api/portail/usagers/{usager.pk}/contacts").json()
    assert all("courriel" in c for c in vue_principal)
    retrait = client_contact(principal).delete(f"/api/portail/usagers/{usager.pk}/contacts/{secondaire.pk}")
    assert retrait.status_code == 204 and not usager.rattachements.filter(contact=secondaire).exists()
    assert (
        client_contact(principal).delete(f"/api/portail/usagers/{usager.pk}/contacts/{principal.contact_id}").status_code == 403
    )


# --- PLA-05 : la demande de campagne envoyée du portail suit les règles du guichet --------------------------------


@override_settings(CANAL="portail")
def test_pla05_portail_refuse_hors_sites_et_hors_saison():
    saison = saison_2026()
    site_campagne, autre_site = SiteFabrique(), SiteFabrique()
    campagne = Campagne.objects.create(
        saison=saison, nom="Créneaux 2026-2027", ouverture=date(2026, 10, 1), cloture=date(2026, 11, 30), statut="ouverte"
    )
    campagne.sites.add(site_campagne)
    compte = compte_actif()
    client = client_contact(compte)
    dossier = client.post(
        f"/api/portail/campagnes/{campagne.pk}/demandes", {"usager": _usager(compte).pk, "objet": "Basket"}, format="json"
    ).json()
    hors_site = EspaceFabrique(batiment__site=autre_site)
    hors_saison = EspaceFabrique(batiment__site=site_campagne)
    creneaux = [
        {
            "espace": hors_site.pk,
            "date_debut": "2026-11-10",
            "date_fin": "2026-11-10",
            "heure_debut": "18:00",
            "heure_fin": "20:00",
        },
        {
            "espace": hors_saison.pk,
            "date_debut": "2027-08-10",
            "date_fin": "2027-08-10",
            "heure_debut": "18:00",
            "heure_fin": "20:00",
        },
    ]
    assert (
        client.patch(
            f"/api/portail/dossiers/{dossier['id']}", {"creneaux": creneaux, "objet": "Basket"}, format="json"
        ).status_code
        == 200
    )
    envoi = client.post(f"/api/portail/dossiers/{dossier['id']}/envoyer")
    assert envoi.status_code == 400
    erreurs = " ".join(envoi.json()["details"]["erreurs"])
    assert "n'est pas proposé dans cette campagne" in erreurs and "comprises dans la saison" in erreurs


# --- RG-08 : une demande jamais accordée n'est pas annulée « tardivement » ---------------------------------------


@override_settings(CANAL="portail")
def test_rg08_annulation_d_une_demande_jamais_tardive_et_service_prevenu(django_capture_on_commit_callbacks):
    compte = compte_actif()
    demande = reserver(EspaceFabrique(), date(2026, 11, 2), "09:00", "11:00", usager=_usager(compte))
    seance = demande.occurrences.first()
    client = client_contact(compte)
    detail = client.get(f"/api/portail/dossiers/{demande.dossier_id}").json()
    assert detail["reservations"][0]["seances"][0]["annulation_tardive_si_annulee"] is False
    with django_capture_on_commit_callbacks(execute=True):
        reponse = client.post(
            f"/api/portail/dossiers/{demande.dossier_id}/occurrences/{seance.pk}/annuler", {"motif": "Plus besoin"}, format="json"
        )
    assert reponse.status_code == 200 and reponse.json()["annulation_tardive"] is False
    assert any("Annulation par" in m.subject for m in mail.outbox)
    accordee = valider_systeme(reserver(EspaceFabrique(), date(2026, 11, 2), "14:00", "16:00", usager=_usager(compte)))
    seance = accordee.occurrences.first()
    tardive = client.post(
        f"/api/portail/dossiers/{accordee.dossier_id}/occurrences/{seance.pk}/annuler", {"motif": "Imprévu"}, format="json"
    )
    assert tardive.json()["annulation_tardive"] is True


# --- COM-05 : un numéro de SMS est confirmé par un code ------------------------------------------------------------


@override_settings(CANAL="portail")
def test_com05_numero_sms_confirme_par_code_avant_tout_envoi(django_capture_on_commit_callbacks, monkeypatch):
    envoyes: list[tuple[str, str]] = []
    from apps.communication import services as communication

    monkeypatch.setattr(
        communication,
        "envoyer_sms",
        lambda numero, texte, reference: envoyes.append((numero, texte)) or type("R", (), {"envoye": True, "motif": ""})(),
    )
    compte = compte_actif()
    client = client_contact(compte)
    with django_capture_on_commit_callbacks(execute=True):
        reponse = client.patch("/api/portail/compte/preferences", {"sms": True, "telephone_sms": "06 12 34 56 78"}, format="json")
    assert reponse.status_code == 200 and reponse.json()["telephone_confirme"] is False
    code = re.search(r"\d{6}", envoyes[-1][1]).group(0)
    journal = Notification.objects.get(canal="sms")
    assert code not in journal.corps and journal.corps_secret == ""
    preferences = PreferenceNotification.objects.get(contact=compte.contact)
    assert preferences.sms_possible is False
    assert (
        client.post(
            "/api/portail/compte/preferences/telephone", {"code": "000000" if code != "000000" else "111111"}, format="json"
        ).status_code
        == 400
    )
    assert (
        client.post("/api/portail/compte/preferences/telephone", {"code": code}, format="json").json()["telephone_confirme"]
        is True
    )
    preferences.refresh_from_db()
    assert preferences.sms_possible is True
