"""POR-05 : abonnement iCal aux séances d'une structure ; SEC-01 : flux lu sans session, par le seul jeton."""

from __future__ import annotations

import re
from datetime import date

import pytest
from django.test import override_settings
from freezegun import freeze_time

from apps.reservations.tests.outils import reserver, valider_systeme
from apps.usagers.models import AbonnementAgenda, Rattachement
from tests.fabriques import EspaceFabrique, usager_avec_contact

from .outils import client_contact, compte_actif

pytestmark = [pytest.mark.django_db, pytest.mark.urls("config.urls_portail")]


@pytest.fixture(autouse=True)
def maintenant():
    with freeze_time("2026-11-01 10:00"), override_settings(CANAL="portail", PORTAIL_URL="https://portail.test"):
        yield


@pytest.fixture
def structure():
    usager = usager_avec_contact(nom="Club de Volley du Parc")
    espace = EspaceFabrique(nom="Gymnase du Parc")
    site = espace.batiment.site
    site.adresse, site.acces = "12 allée des Sports", "Entrée côté parking."
    site.save()
    valider_systeme(reserver(espace, date(2026, 11, 10), "18:00", "20:00", usager=usager))
    reserver(espace, date(2026, 11, 12), "18:00", "20:00", usager=usager)
    return usager


def _jeton(url: str) -> str:
    trouve = re.fullmatch(r"https://portail\.test/api/portail/agenda/([A-Za-z0-9_-]{43})\.ics", url)
    assert trouve, url
    return trouve.group(1)


def test_por05_abonnement_aux_seances_de_la_structure(client_api, structure):
    client = client_contact(compte_actif(structure))
    assert client.get(f"/api/portail/usagers/{structure.pk}/agenda").json()["actif"] is False
    emis = client.post(f"/api/portail/usagers/{structure.pk}/agenda")
    assert emis.status_code == 201
    assert emis.json()["actif"] is True and emis.json()["expire_le"].startswith("2027-11-01")
    jeton = _jeton(emis.json()["url"])

    flux = client_api.get(f"/api/portail/agenda/{jeton}.ics")
    assert flux.status_code == 200 and flux["Content-Type"].startswith("text/calendar")
    assert flux["Cache-Control"] == "private, no-store"
    texte = flux.content.decode().replace("\r\n ", "")
    assert texte.count("BEGIN:VEVENT") == 2
    assert "Gymnase du Parc" in texte and "12 allée des Sports" in texte and "Entrée côté parking." in texte
    # La séance validée est ferme, la demande en cours est provisoire.
    assert "STATUS:CONFIRMED" in texte and "STATUS:TENTATIVE" in texte
    # Seule l'empreinte est conservée, et le dernier accès est noté.
    abonnement = AbonnementAgenda.objects.get()
    assert jeton not in abonnement.empreinte and abonnement.dernier_acces is not None


def test_por05_nouveau_lien_revoque_l_ancien_et_revocation(client_api, structure):
    client = client_contact(compte_actif(structure))
    ancien = _jeton(client.post(f"/api/portail/usagers/{structure.pk}/agenda").json()["url"])
    nouveau = _jeton(client.post(f"/api/portail/usagers/{structure.pk}/agenda").json()["url"])
    assert client_api.get(f"/api/portail/agenda/{ancien}.ics").status_code == 404
    assert client_api.get(f"/api/portail/agenda/{nouveau}.ics").status_code == 200
    assert client.delete(f"/api/portail/usagers/{structure.pk}/agenda").status_code == 204
    assert client_api.get(f"/api/portail/agenda/{nouveau}.ics").status_code == 404
    assert client.get(f"/api/portail/usagers/{structure.pk}/agenda").json()["actif"] is False


def test_por05_lien_refuse_si_le_contact_quitte_la_structure_ou_a_echeance(client_api, structure):
    compte = compte_actif(structure)
    jeton = _jeton(client_contact(compte).post(f"/api/portail/usagers/{structure.pk}/agenda").json()["url"])
    with freeze_time("2027-11-02 10:00"):
        assert client_api.get(f"/api/portail/agenda/{jeton}.ics").status_code == 404
    Rattachement.objects.filter(usager=structure, contact=compte.contact).delete()
    assert client_api.get(f"/api/portail/agenda/{jeton}.ics").status_code == 404


def test_por05_abonnement_refuse_pour_la_structure_d_un_autre(client_api, structure):
    autre = client_contact(compte_actif(usager_avec_contact(nom="Autre club")))
    assert autre.get(f"/api/portail/usagers/{structure.pk}/agenda").status_code == 404
    assert autre.post(f"/api/portail/usagers/{structure.pk}/agenda").status_code == 404
    assert autre.delete(f"/api/portail/usagers/{structure.pk}/agenda").status_code == 404
    assert client_api.post(f"/api/portail/usagers/{structure.pk}/agenda").status_code == 401
    assert not AbonnementAgenda.objects.exists()


def test_sec01_flux_agenda_jeton_inconnu_ou_mal_forme(client_api):
    assert client_api.get(f"/api/portail/agenda/{'a' * 43}.ics").status_code == 404
    assert client_api.get("/api/portail/agenda/court.ics").status_code == 404


def _flux(client_api, structure) -> str:
    jeton = _jeton(client_contact(compte_actif(structure)).post(f"/api/portail/usagers/{structure.pk}/agenda").json()["url"])
    reponse = client_api.get(f"/api/portail/agenda/{jeton}.ics")
    assert reponse.status_code == 200
    return reponse.content.decode().replace("\r\n ", "")


def _evenements(texte: str) -> dict[str, str]:
    """Titre de chaque événement → bloc iCalendar complet."""
    blocs = texte.split("BEGIN:VEVENT")[1:]
    return {re.search(r"SUMMARY:(.*)", b).group(1).strip(): b for b in blocs}


def test_por05_statuts_ferme_provisoire_annule_refuse(client_api):
    usager = usager_avec_contact(nom="Club des statuts")
    espace = EspaceFabrique(nom="Dojo")
    for jour, statut in [(9, "validee"), (10, "demande"), (11, "annulee"), (12, "refusee"), (13, "realisee")]:
        reservation = reserver(espace, date(2026, 11, jour), "18:00", "19:00", usager=usager)
        reservation.occurrences.update(statut=statut)
    texte = _flux(client_api, usager)
    # La séance validée et la séance réalisée sont fermes : même titre, sans mention.
    assert sorted(t.strip() for t in re.findall(r"SUMMARY:(.*)", texte)) == [
        "Annulé — Dojo — Entraînement",
        "Dojo — Entraînement",
        "Dojo — Entraînement",
        "Provisoire — Dojo — Entraînement",
        "Refusé — Dojo — Entraînement",
    ]
    evenements = _evenements(texte)
    assert "STATUS:TENTATIVE" in evenements["Provisoire — Dojo — Entraînement"]
    assert "STATUS:CANCELLED" in evenements["Annulé — Dojo — Entraînement"]
    assert "STATUS:CANCELLED" in evenements["Refusé — Dojo — Entraînement"]
    assert "STATUS:CONFIRMED" in evenements["Dojo — Entraînement"]


def test_por05_flux_limite_aux_seances_de_la_structure(client_api, structure):
    autre = usager_avec_contact(nom="Club voisin")
    valider_systeme(reserver(EspaceFabrique(nom="Salle du club voisin"), date(2026, 11, 10), "10:00", "12:00", usager=autre))
    texte = _flux(client_api, structure)
    assert texte.count("BEGIN:VEVENT") == 2 and "Salle du club voisin" not in texte


def test_por05_heures_en_utc_de_part_et_d_autre_du_changement_d_heure(client_api, structure):
    from apps.reservations.models import Occurrence
    from apps.reservations.tests.outils import paris

    hiver = Occurrence.objects.filter(reservation__dossier__usager=structure, statut="validee").get()
    ete = Occurrence.objects.filter(reservation__dossier__usager=structure).exclude(pk=hiver.pk).get()
    Occurrence.objects.filter(pk=ete.pk).update(debut=paris(2026, 10, 20, 18), fin=paris(2026, 10, 20, 20))
    texte = _flux(client_api, structure)
    assert "DTSTART:20261110T170000Z" in texte  # 18 h à Paris en hiver (UTC+1)
    assert "DTSTART:20261020T160000Z" in texte  # 18 h à Paris en été (UTC+2)


def test_por05_lien_revoque_quand_le_compte_ou_la_structure_est_suspendu(client_api, structure):
    from apps.comptes.services import reactiver_compte, suspendre_compte
    from apps.usagers.services import changer_statut
    from tests.fabriques import agent

    compte = compte_actif(structure)
    client = client_contact(compte)
    jeton = _jeton(client.post(f"/api/portail/usagers/{structure.pk}/agenda").json()["url"])
    gestionnaire = agent("gestionnaire")
    suspendre_compte(compte, acteur=gestionnaire, motif="Conflit au bureau")
    assert client_api.get(f"/api/portail/agenda/{jeton}.ics").status_code == 404
    reactiver_compte(compte, acteur=gestionnaire)
    # La réactivation ne fait pas revivre l'ancien lien.
    assert client_api.get(f"/api/portail/agenda/{jeton}.ics").status_code == 404

    nouveau = _jeton(client_contact(compte).post(f"/api/portail/usagers/{structure.pk}/agenda").json()["url"])
    changer_statut(structure, "suspendu", depuis={"valide"}, acteur=gestionnaire, motif="Assurance échue")
    assert client_api.get(f"/api/portail/agenda/{nouveau}.ics").status_code == 404
    assert not AbonnementAgenda.objects.filter(revoque_le__isnull=True).exists()


def test_por05_lien_revoque_quand_le_contact_est_retire_ou_la_structure_anonymisee(client_api, structure):
    from apps.comptes.models import CompteUsager
    from apps.usagers.rgpd import anonymiser_usager
    from tests.fabriques import ContactFabrique

    principal = compte_actif(structure)
    Rattachement.objects.filter(usager=structure, contact=principal.contact).update(principal=True)
    membre = ContactFabrique()
    Rattachement.objects.create(usager=structure, contact=membre, role="tresorier")
    compte_membre = CompteUsager.objects.create(contact=membre, identifiant=membre.courriel.lower(), statut="actif")
    jeton = _jeton(client_contact(compte_membre).post(f"/api/portail/usagers/{structure.pk}/agenda").json()["url"])
    retrait = client_contact(principal).delete(f"/api/portail/usagers/{structure.pk}/contacts/{membre.pk}")
    assert retrait.status_code == 204
    assert AbonnementAgenda.objects.get(contact=membre).revoque_le is not None
    # Rattaché de nouveau, le contact ne retrouve pas son ancien lien.
    Rattachement.objects.create(usager=structure, contact=membre, role="tresorier")
    assert client_api.get(f"/api/portail/agenda/{jeton}.ics").status_code == 404

    # Une structure sans réservation en cours peut être anonymisée : son lien cesse aussitôt.
    ancienne = usager_avec_contact(nom="Club dissous")
    compte_ancien = compte_actif(ancienne)
    dernier = _jeton(client_contact(compte_ancien).post(f"/api/portail/usagers/{ancienne.pk}/agenda").json()["url"])
    assert client_api.get(f"/api/portail/agenda/{dernier}.ics").status_code == 200
    anonymiser_usager(ancienne, acteur="système", motif="Durée de conservation échue")
    assert client_api.get(f"/api/portail/agenda/{dernier}.ics").status_code == 404
    assert AbonnementAgenda.objects.get(usager=ancienne).revoque_le is not None


def test_por05_export_rgpd_mentionne_les_abonnements(structure):
    from apps.usagers.agenda import emettre
    from apps.usagers.rgpd import exporter_contact

    compte = compte_actif(structure)
    emettre(structure, compte.contact)
    export = exporter_contact(compte.contact)
    assert [a["structure"] for a in export["abonnements_agenda"]] == ["Club de Volley du Parc"]
