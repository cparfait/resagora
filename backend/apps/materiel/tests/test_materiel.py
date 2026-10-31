"""Lot 5 — matériel : inventaire (MAT-01), réservation et disponibilité (MAT-02), mouvements et retours (MAT-03),
contrôles périodiques (MAT-04), pannes (MAT-05), droits rôle × périmètre (RG-14), devis (TAR-04)."""

from __future__ import annotations

from datetime import date, datetime, time, timedelta

import pytest
from django.core import mail
from django.db import DatabaseError, transaction
from freezegun import freeze_time

from apps.materiel import services
from apps.materiel.models import Materiel, Mouvement, Panne, ReservationMateriel, Stock
from apps.reservations import services as reservations
from apps.reservations.recurrence import PARIS
from apps.reservations.tests.outils import reserver
from tests.fabriques import EspaceFabrique, SiteFabrique, agent

pytestmark = pytest.mark.django_db
JOUR = date(2026, 11, 14)  # samedi


@pytest.fixture(autouse=True)
def horloge():
    with freeze_time("2026-11-02 10:00") as h:
        yield h


@pytest.fixture
def lieu():
    espace = EspaceFabrique(nom="Salle des fêtes")
    return espace.batiment.site, espace


def _tables(site, quantite=15) -> Stock:
    tables = Materiel.objects.create(code="table", libelle="Table pliante", unite="table", valeur_journaliere_centimes=300)
    return services.entrer(tables, site, quantite, acteur="système")


def _location(espace, jour=JOUR, debut="14:00", fin="23:00"):
    return reserver(espace, jour, debut, fin, statut="validee")


def paris(jour: date, heure: int) -> datetime:
    return datetime.combine(jour, time(heure), tzinfo=PARIS)


# --- MAT-01 -------------------------------------------------------------------------------------------------


def test_mat01_creer_un_materiel_et_l_affecter_a_un_espace(client_agent, lieu):
    site, espace = lieu
    technicien = client_agent(agent("technicien_materiel"))
    reponse = technicien.post(
        "/api/gestion/materiel/catalogue",
        {"code": "but-hand", "libelle": "But de handball", "nature": "fixe", "periodicite_controle_jours": 365},
        format="json",
    )
    assert reponse.status_code == 201
    sans_espace = technicien.post(
        "/api/gestion/materiel/stocks/entrer", {"materiel": reponse.json()["id"], "site": site.pk, "quantite": 2}, format="json"
    )
    assert sans_espace.status_code == 400 and sans_espace.json()["code"] == "espace_requis"
    entree = technicien.post(
        "/api/gestion/materiel/stocks/entrer",
        {"materiel": reponse.json()["id"], "site": site.pk, "espace": espace.pk, "quantite": 2, "motif": "Achat"},
        format="json",
    )
    assert entree.status_code == 201 and entree.json()["espace_nom"] == "Salle des fêtes" and entree.json()["quantite"] == 2
    assert (
        client_agent(agent("accueil"))
        .post("/api/gestion/materiel/catalogue", {"code": "x", "libelle": "X"}, format="json")
        .status_code
        == 403
    )


def test_rg14_stock_hors_perimetre_invisible_et_non_modifiable(client_agent, lieu):
    site, _espace = lieu
    stock = _tables(site)
    autre = SiteFabrique()
    hors = client_agent(agent("technicien_materiel", autre))
    assert hors.get(f"/api/gestion/materiel/stocks/{stock.pk}").status_code == 404
    assert (
        hors.post(f"/api/gestion/materiel/stocks/{stock.pk}/perte", {"quantite": 1, "motif": "Vol"}, format="json").status_code
        == 404
    )
    entree = hors.post(
        "/api/gestion/materiel/stocks/entrer", {"materiel": stock.materiel_id, "site": site.pk, "quantite": 1}, format="json"
    )
    assert entree.status_code == 403


# --- MAT-02 -------------------------------------------------------------------------------------------------


def test_mat02_reserver_20_tables_quand_15_sont_disponibles_refuse(client_agent, lieu):
    site, espace = lieu
    stock = _tables(site, 15)
    reservation = _location(espace)
    gestionnaire = client_agent(agent("gestionnaire"))
    refus = gestionnaire.post(
        "/api/gestion/materiel/prets",
        {"dossier": reservation.dossier_id, "reservation": reservation.pk, "stock": stock.pk, "quantite": 20},
        format="json",
    )
    assert refus.status_code == 409 and refus.json()["code"] == "materiel_indisponible"
    assert "15" in refus.json()["message"]
    accord = gestionnaire.post(
        "/api/gestion/materiel/prets",
        {"dossier": reservation.dossier_id, "reservation": reservation.pk, "stock": stock.pk, "quantite": 15},
        format="json",
    )
    assert accord.status_code == 201 and accord.json()[0]["statut"] == "validee"


def test_mat02_disponibilite_au_pic_d_engagement(lieu):
    site, espace = lieu
    stock = _tables(site, 15)
    matin, apres_midi = _location(espace, debut="08:00", fin="12:00"), _location(espace, debut="13:00", fin="18:00")
    services.reserver(matin.dossier, stock, 10, acteur="système", occurrence=matin.occurrences.get())
    services.reserver(apres_midi.dossier, stock, 10, acteur="système", occurrence=apres_midi.occurrences.get())
    journee = (paris(JOUR, 7), paris(JOUR, 20))
    assert services.disponible(stock, *journee) == 5  # jamais plus de 10 tables prêtées en même temps
    soir = _location(EspaceFabrique(batiment=espace.batiment, nom="Salle annexe"), debut="11:00", fin="14:00")
    with pytest.raises(Exception, match="disponible"):
        services.reserver(soir.dossier, stock, 6, acteur="système", occurrence=soir.occurrences.get())


def test_mat02_demande_du_portail_validee_par_un_agent(lieu):
    site, espace = lieu
    stock = _tables(site, 15)
    Materiel.objects.filter(pk=stock.materiel_id).update(propose_portail=True)
    stock.refresh_from_db()
    reservation = _location(espace)
    demande = services.reserver(
        reservation.dossier,
        stock,
        12,
        acteur=reservation.dossier.usager.rattachements.first().contact,
        occurrence=reservation.occurrences.get(),
        origine="portail",
    )
    assert demande.statut == "demandee"
    assert services.disponible(stock, demande.debut, demande.fin) == 15, "une demande ne bloque pas avant validation"
    services.valider(demande, acteur=agent("accueil"))
    demande.refresh_from_db()
    assert demande.statut == "validee" and services.disponible(stock, demande.debut, demande.fin) == 3


def test_mat02_materiel_d_un_autre_site_refuse(lieu):
    _site, espace = lieu
    stock = _tables(SiteFabrique(), 15)
    reservation = _location(espace)
    with pytest.raises(Exception, match="site"):
        services.reserver(reservation.dossier, stock, 2, acteur="système", occurrence=reservation.occurrences.get())


# --- MAT-03 -------------------------------------------------------------------------------------------------


def test_mat03_retour_de_18_tables_sur_20_signale_2_manquantes(client_agent, lieu, django_capture_on_commit_callbacks):
    site, espace = lieu
    stock = _tables(site, 30)
    reservation = _location(espace)
    pret = services.reserver(reservation.dossier, stock, 20, acteur="système", occurrence=reservation.occurrences.get())
    technicien = client_agent(agent("technicien_materiel"))
    assert technicien.post(f"/api/gestion/materiel/prets/{pret.pk}/sortir", {}, format="json").json()["statut"] == "sortie"
    with django_capture_on_commit_callbacks(execute=True):
        retour = technicien.post(
            f"/api/gestion/materiel/prets/{pret.pk}/rendre",
            {"quantite": 18, "observations": "Deux tables absentes"},
            format="json",
        )
    assert retour.status_code == 200 and retour.json()["manquants"] == 2 and "manquant" in retour.json()["signalement"]
    stock.refresh_from_db()
    assert stock.quantite == 28
    assert list(Mouvement.objects.filter(reservation=pret).values_list("type", flat=True).order_by("id")) == [
        "sortie",
        "retour",
        "perte",
    ]
    assert any("manquant" in m.subject.lower() for m in mail.outbox)
    services.retrouver(pret, acteur="système", quantite=2)
    stock.refresh_from_db()
    pret.refresh_from_db()
    assert stock.quantite == 30 and pret.manquants == 0


def test_mat03_consommable_non_rendu_consomme(lieu):
    site, espace = lieu
    gobelets = Materiel.objects.create(
        code="gobelet", libelle="Gobelet", nature="consommable", seuil_alerte=100, valeur_journaliere_centimes=5
    )
    stock = services.entrer(gobelets, site, 300, acteur="système")
    reservation = _location(espace)
    pret = services.reserver(reservation.dossier, stock, 250, acteur="système", occurrence=reservation.occurrences.get())
    services.sortir(pret, acteur="système")
    pret = services.rendre(pret, acteur="système", quantite=60)
    stock.refresh_from_db()
    assert pret.manquants == 0 and stock.quantite == 110
    assert Mouvement.objects.filter(type="consommation", quantite=190).exists()
    assert services.stocks_sous_seuil([stock]) == []
    services.declarer_perte(stock, 20, acteur="système", motif="Casse")
    stock.refresh_from_db()
    assert services.stocks_sous_seuil([stock]) == [stock]


def test_mat03_journal_des_mouvements_immuable(lieu):
    site, _espace = lieu
    _tables(site)
    mouvement = Mouvement.objects.get()
    with pytest.raises(DatabaseError), transaction.atomic():
        Mouvement.objects.filter(pk=mouvement.pk).update(quantite=1)
    with pytest.raises(DatabaseError), transaction.atomic():
        Mouvement.objects.filter(pk=mouvement.pk).delete()


def test_mat03_transfert_refuse_s_il_prive_des_prets_valides(lieu):
    site, espace = lieu
    stock = _tables(site, 15)
    reservation = _location(espace)
    services.reserver(reservation.dossier, stock, 12, acteur="système", occurrence=reservation.occurrences.get())
    autre = SiteFabrique()
    with pytest.raises(Exception, match="priverait"):
        services.transferer(stock, autre, 5, acteur="système")
    destination = services.transferer(stock, autre, 3, acteur="système")
    stock.refresh_from_db()
    assert stock.quantite == 12 and destination.quantite == 3


def test_mat03_etat_du_stock_exporte(client_agent, lieu):
    site, _espace = lieu
    _tables(site, 15)
    reponse = client_agent(agent("technicien_materiel")).get("/api/gestion/materiel/stocks/etat", {"export": "csv"})
    assert reponse.status_code == 200 and "Table pliante" in reponse.content.decode("utf-8-sig")


# --- MAT-04 -------------------------------------------------------------------------------------------------


def test_mat04_controle_periodique_depasse_en_alerte(client_agent, lieu, horloge, django_capture_on_commit_callbacks):
    site, espace = lieu
    but = Materiel.objects.create(code="but", libelle="But de handball", nature="fixe", periodicite_controle_jours=365)
    stock = services.entrer(but, site, 2, acteur="système", espace=espace)
    services.enregistrer_controle(stock, acteur="système", realise_le=date(2025, 10, 1))
    technicien = client_agent(agent("technicien_materiel"))
    alertes = technicien.get("/api/gestion/materiel/stocks/alertes").json()
    assert [a["id"] for a in alertes["controles"]] == [stock.pk] and alertes["controles"][0]["echeance"] == "2026-10-01"
    with django_capture_on_commit_callbacks(execute=True):
        assert services.alerter_controles() == 1
    assert any("Matériel" in m.subject for m in mail.outbox)
    reponse = technicien.post(
        f"/api/gestion/materiel/stocks/{stock.pk}/controle",
        {"realise_le": "2026-11-02", "prestataire": "Bureau de contrôle"},
        format="json",
    )
    assert reponse.status_code == 201 and reponse.json()["prochain_le"] == "2027-11-02"
    assert technicien.get("/api/gestion/materiel/stocks/alertes").json()["controles"] == []
    assert (
        client_agent(agent("accueil"))
        .post(f"/api/gestion/materiel/stocks/{stock.pk}/controle", {"realise_le": "2026-11-02"}, format="json")
        .status_code
        == 403
    )


def test_mat04_controle_non_conforme_met_le_materiel_hors_service(lieu):
    site, espace = lieu
    but = Materiel.objects.create(code="but", libelle="But de handball", nature="fixe", periodicite_controle_jours=365)
    stock = services.entrer(but, site, 2, acteur="système", espace=espace)
    services.enregistrer_controle(
        stock, acteur="système", realise_le=date(2026, 11, 2), conforme=False, observations="Ancrage au sol desserré"
    )
    stock.refresh_from_db()
    assert stock.hors_service == 2 and Panne.objects.get().source == "controle"


# --- MAT-05 -------------------------------------------------------------------------------------------------


def test_mat05_materiel_en_panne_n_est_plus_reservable(client_agent, lieu, django_capture_on_commit_callbacks):
    site, espace = lieu
    sono = Materiel.objects.create(code="sono", libelle="Sonorisation mobile", unite="ensemble", valeur_journaliere_centimes=6000)
    stock = services.entrer(sono, site, 1, acteur="système")
    deja = _location(espace)
    pret = services.reserver(deja.dossier, stock, 1, acteur="système", occurrence=deja.occurrences.get())
    with django_capture_on_commit_callbacks(execute=True):
        reponse = client_agent(agent("gardien")).post(
            f"/api/gestion/materiel/stocks/{stock.pk}/panne", {"description": "Enceinte muette"}, format="json"
        )
    assert reponse.status_code == 201
    pret.refresh_from_db()
    assert "panne" in pret.signalement
    assert any("indisponible" in m.subject.lower() for m in mail.outbox)
    nouvelle = _location(espace, jour=JOUR + timedelta(days=7))
    with pytest.raises(Exception, match="disponible"):
        services.reserver(nouvelle.dossier, stock, 1, acteur="système", occurrence=nouvelle.occurrences.get())
    panne = Panne.objects.get()
    assert (
        client_agent(agent("gardien"))
        .post(f"/api/gestion/materiel/pannes/{panne.pk}/resoudre", {"issue": "reparee"}, format="json")
        .status_code
        == 403
    )
    client_agent(agent("technicien_materiel")).post(
        f"/api/gestion/materiel/pannes/{panne.pk}/resoudre", {"issue": "reparee"}, format="json"
    )
    assert (
        services.reserver(nouvelle.dossier, stock, 1, acteur="système", occurrence=nouvelle.occurrences.get()).statut == "validee"
    )


def test_mat05_mise_au_rebut_retire_du_stock(lieu):
    site, _espace = lieu
    stock = _tables(site, 15)
    panne = services.signaler_panne(stock, acteur="système", quantite=3, description="Pieds tordus")
    services.resoudre_panne(panne, acteur="système", issue="rebut", resolution="Irréparables")
    stock.refresh_from_db()
    assert stock.quantite == 12 and stock.hors_service == 0


# --- Droits, devis, annulation --------------------------------------------------------------------------------


def test_rg14_accueil_reserve_mais_ne_sort_pas_le_materiel(client_agent, lieu):
    site, espace = lieu
    stock = _tables(site, 15)
    reservation = _location(espace)
    accueil = client_agent(agent("accueil"))
    pret = accueil.post(
        "/api/gestion/materiel/prets",
        {"dossier": reservation.dossier_id, "reservation": reservation.pk, "stock": stock.pk, "quantite": 5},
        format="json",
    )
    assert pret.status_code == 201
    assert accueil.post(f"/api/gestion/materiel/prets/{pret.json()[0]['id']}/sortir", {}, format="json").status_code == 403
    hors = client_agent(agent("gestionnaire", SiteFabrique()))
    assert hors.get(f"/api/gestion/materiel/prets/{pret.json()[0]['id']}").status_code == 404


def test_tar04_pret_d_un_materiel_facture_entre_au_devis(lieu, monkeypatch, modeles_documents):
    from apps.documents import services as documents
    from apps.finances import facturation
    from apps.finances.models import Prestation
    from apps.finances.tests.outils import PDF, grille_votee

    monkeypatch.setattr(documents, "convertir_en_pdfa", lambda nom, docx, transport=None: PDF)
    site, espace = lieu
    grille = grille_votee(espace)
    Prestation.objects.create(grille=grille, code="pret-tables", libelle="Prêt de tables", unite="journee", prix_centimes=200)
    stock = _tables(site, 30)
    Materiel.objects.filter(pk=stock.materiel_id).update(prestation_code="pret-tables")
    reservation = _location(espace)
    services.reserver(reservation.dossier, stock, 10, acteur="système", occurrence=reservation.occurrences.get())
    devis = facturation.etablir_devis(reservation.dossier, acteur="système")
    ligne = devis.lignes.get(nature="prestation")
    assert ligne.libelle == "Prêt de tables" and ligne.quantite == 10 and ligne.prix_unitaire == 200


def test_mat02_annulation_de_la_reservation_libere_le_materiel(lieu):
    site, espace = lieu
    stock = _tables(site, 15)
    reservation = _location(espace)
    pret = services.reserver(reservation.dossier, stock, 10, acteur="système", occurrence=reservation.occurrences.get())
    reservations.annuler_occurrence(reservation.occurrences.get(), acteur="système", motif="Fête reportée")
    pret.refresh_from_db()
    assert pret.statut == "annulee" and services.disponible(stock, pret.debut, pret.fin) == 15
    assert ReservationMateriel.objects.filter(statut="validee").count() == 0
