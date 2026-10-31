"""Corrections des revues du lot 5 : prêts séance par séance (MAT-02), suivi des réservations (refus, option expirée,
déplacement, suppression), prêts sortis et inventaire (MAT-03), consommables, matériel fixe, journées civiles,
facturation et avoirs (TAR-04, TAR-05), caution (RG-11), droits (RG-14), pannes et contrôles (MAT-04, MAT-05)."""

from __future__ import annotations

from datetime import date, datetime, time, timedelta

import pytest
from freezegun import freeze_time

from apps.materiel import services
from apps.materiel.models import Materiel, Panne, ReservationMateriel, Stock
from apps.reservations import services as reservations
from apps.reservations.recurrence import PARIS
from apps.reservations.tests.outils import reserver, valider_systeme
from tests.fabriques import EspaceFabrique, SiteFabrique, agent

pytestmark = pytest.mark.django_db
SAMEDI = date(2026, 11, 14)


@pytest.fixture(autouse=True)
def horloge():
    with freeze_time("2026-11-02 10:00") as h:
        yield h


@pytest.fixture
def lieu():
    espace = EspaceFabrique(nom="Salle polyvalente")
    return espace.batiment.site, espace


def _article(code="table", **champs) -> Materiel:
    valeurs = {"libelle": "Table pliante", "unite": "table", "valeur_journaliere_centimes": 300, **champs}
    return Materiel.objects.create(code=code, **valeurs)


def _stock(site, quantite=15, **champs) -> Stock:
    return services.entrer(_article(**champs), site, quantite, acteur="système")


def _seance(espace, jour=SAMEDI, debut="14:00", fin="18:00"):
    return reserver(espace, jour, debut, fin, statut="validee")


def paris(jour: date, heure: int) -> datetime:
    return datetime.combine(jour, time(heure), tzinfo=PARIS)


# --- Prêts séance par séance (B1) ------------------------------------------------------------------------------


def test_mat02_reservation_hebdomadaire_un_pret_par_seance(lieu, client_agent):
    site, espace = lieu
    stock = _stock(site, 2)
    serie = valider_systeme(
        reserver(
            espace,
            date(2026, 11, 3),
            "18:00",
            "20:00",
            recurrence="FREQ=WEEKLY;COUNT=4",
            date_fin=date(2026, 11, 30),
            exclure_vacances=False,
        )
    )
    reponse = client_agent(agent("gestionnaire")).post(
        "/api/gestion/materiel/prets",
        {"dossier": serie.dossier_id, "reservation": serie.pk, "stock": stock.pk, "quantite": 2},
        format="json",
    )
    assert reponse.status_code == 201 and len(reponse.json()) == 4
    # Entre deux séances, les tables sont libres pour un autre usager.
    autre = _seance(EspaceFabrique(batiment=espace.batiment), jour=date(2026, 11, 5))
    assert services.reserver(autre.dossier, stock, 2, acteur="système", occurrence=autre.occurrences.get()).statut == "validee"


def test_mat02_refus_d_une_reservation_libere_son_materiel(lieu):
    site, espace = lieu
    stock = _stock(site)
    demande = reserver(espace, SAMEDI, "14:00", "18:00")
    pret = services.reserver(demande.dossier, stock, 10, acteur=agent("gestionnaire"), occurrence=demande.occurrences.get())
    assert pret.statut == "demandee", "la réservation n'est pas encore accordée"
    reservations.refuser(demande, acteur=agent("gestionnaire"), motif="Équipement indisponible")
    pret.refresh_from_db()
    assert pret.statut == "refusee"


def test_mat02_validation_de_la_reservation_valide_les_prets_du_back_office(lieu):
    site, espace = lieu
    stock = _stock(site)
    demande = reserver(espace, SAMEDI, "14:00", "18:00")
    pret = services.reserver(demande.dossier, stock, 10, acteur=agent("gestionnaire"), occurrence=demande.occurrences.get())
    reservations.valider(demande, acteur=agent("gestionnaire"))
    pret.refresh_from_db()
    assert pret.statut == "validee"


def test_mat02_seance_deplacee_le_pret_suit(lieu):
    site, espace = lieu
    stock = _stock(site)
    reservation = _seance(espace)
    seance = reservation.occurrences.get()
    pret = services.reserver(reservation.dossier, stock, 10, acteur="système", occurrence=seance)
    reservations.deplacer_occurrence(
        seance,
        acteur=agent("gestionnaire"),
        espace=espace,
        debut=paris(SAMEDI + timedelta(days=7), 9),
        fin=paris(SAMEDI + timedelta(days=7), 12),
    )
    pret.refresh_from_db()
    assert (
        pret.debut == paris(SAMEDI + timedelta(days=7), 9)
        and services.disponible(stock, paris(SAMEDI, 14), paris(SAMEDI, 18)) == 15
    )


def test_mat02_pret_sorti_non_rendu_immobilise_le_stock(lieu, horloge):
    site, espace = lieu
    stock = _stock(site, 10)
    reservation = _seance(espace)
    pret = services.reserver(reservation.dossier, stock, 8, acteur="système", occurrence=reservation.occurrences.get())
    services.sortir(pret, acteur="système")
    horloge.move_to("2026-11-20 10:00")
    lendemain = _seance(espace, jour=date(2026, 11, 21))
    with pytest.raises(Exception, match="2 table"):
        services.reserver(lendemain.dossier, stock, 5, acteur="système", occurrence=lendemain.occurrences.get())
    with pytest.raises(Exception, match="présentes"):
        services.declarer_perte(stock, 5, acteur="système", motif="Vol")


def test_mat03_inventaire_pendant_un_pret_sorti(lieu):
    site, espace = lieu
    stock = _stock(site, 20)
    reservation = _seance(espace)
    pret = services.reserver(reservation.dossier, stock, 8, acteur="système", occurrence=reservation.occurrences.get())
    services.sortir(pret, acteur="système")
    services.inventorier(stock, 12, acteur="système")
    stock.refresh_from_db()
    assert stock.quantite == 20, "les 8 tables en prêt restent au stock"


def test_mat03_controle_non_conforme_puis_retour_incomplet(lieu):
    site, espace = lieu
    stock = _stock(site, 20, periodicite_controle_jours=365)
    reservation = _seance(espace)
    pret = services.reserver(reservation.dossier, stock, 20, acteur="système", occurrence=reservation.occurrences.get())
    services.sortir(pret, acteur="système")
    services.enregistrer_controle(
        stock, acteur="système", realise_le=date(2026, 11, 2), conforme=False, observations="Charnières fendues"
    )
    stock.refresh_from_db()
    assert stock.hors_service == 0, "aucune table présente : rien à mettre hors service"
    services.rendre(pret, acteur="système", quantite=18)
    stock.refresh_from_db()
    assert stock.quantite == 18


def test_mat03_retour_en_deux_fois(lieu):
    site, espace = lieu
    stock = _stock(site, 20)
    reservation = _seance(espace)
    pret = services.reserver(reservation.dossier, stock, 20, acteur="système", occurrence=reservation.occurrences.get())
    services.sortir(pret, acteur="système")
    pret = services.rendre(pret, acteur="système", quantite=10, solde=False)
    assert pret.statut == "sortie" and pret.manquants == 0
    pret = services.rendre(pret, acteur="système", quantite=10)
    assert pret.statut == "rendue" and pret.manquants == 0


def test_mat02_consommables_cumules_quelle_que_soit_la_date(lieu):
    site, espace = lieu
    stock = _stock(
        site, 300, code="gobelet", libelle="Gobelet", unite="gobelet", nature="consommable", valeur_journaliere_centimes=5
    )
    premiere, seconde = _seance(espace), _seance(espace, jour=SAMEDI + timedelta(days=7))
    services.reserver(premiere.dossier, stock, 250, acteur="système", occurrence=premiere.occurrences.get())
    with pytest.raises(Exception, match="50 gobelet"):
        services.reserver(seconde.dossier, stock, 250, acteur="système", occurrence=seconde.occurrences.get())


def test_mat02_equipement_fixe_seulement_dans_son_espace(lieu):
    site, espace = lieu
    but = _article("but", libelle="But de handball", nature="fixe")
    stock = services.entrer(but, site, 2, acteur="système", espace=espace)
    ailleurs = _seance(EspaceFabrique(batiment=espace.batiment, nom="Dojo"))
    with pytest.raises(Exception, match="fixe"):
        services.reserver(ailleurs.dossier, stock, 1, acteur="système", occurrence=ailleurs.occurrences.get())
    ici = _seance(espace, jour=SAMEDI + timedelta(days=1))
    pret = services.reserver(ici.dossier, stock, 1, acteur="système", occurrence=ici.occurrences.get())
    with pytest.raises(Exception, match="fixe"):
        services.sortir(pret, acteur="système")


def test_mat02_journees_civiles_au_changement_d_heure():
    vendredi, lundi = datetime(2026, 10, 23, 9, tzinfo=PARIS), datetime(2026, 10, 26, 9, tzinfo=PARIS)
    assert services.jours_touches(vendredi, lundi) == 4  # vendredi, samedi, dimanche, lundi (73 h réelles)
    assert services.jours_touches(datetime(2026, 11, 14, 18, tzinfo=PARIS), datetime(2026, 11, 15, 10, tzinfo=PARIS)) == 2


def test_rg05_materiel_sans_valeur_de_reference_non_pretable(lieu):
    site, espace = lieu
    stock = services.entrer(_article(valeur_journaliere_centimes=0), site, 10, acteur="système")
    reservation = _seance(espace)
    with pytest.raises(Exception, match="valeur de référence"):
        services.reserver(reservation.dossier, stock, 1, acteur="système", occurrence=reservation.occurrences.get())


def test_rg05_valeur_figee_sur_le_pret(lieu):
    site, espace = lieu
    stock = _stock(site)
    reservation = _seance(espace)
    pret = services.reserver(reservation.dossier, stock, 2, acteur="système", occurrence=reservation.occurrences.get())
    Materiel.objects.filter(pk=stock.materiel_id).update(valeur_journaliere_centimes=900)
    pret.refresh_from_db()
    assert pret.valeur_journaliere_centimes == 300


# --- Caution (M9) ---------------------------------------------------------------------------------------------


def test_rg11_caution_bloquee_par_du_materiel_manquant(lieu):
    site, espace = lieu
    caution = type("Caution", (), {})()
    stock = _stock(site, 20)
    reservation = _seance(espace)
    caution.reservation = reservation
    pret = services.reserver(reservation.dossier, stock, 20, acteur="système", occurrence=reservation.occurrences.get())
    services.sortir(pret, acteur="système")
    assert "pas rendu" in services.blocage_caution(caution)
    services.rendre(pret, acteur="système", quantite=18)
    assert "manquants" in services.blocage_caution(caution)
    services.regler_manquants(pret, acteur="système", decision="Retenue de 60 € proposée sur la caution")
    assert services.blocage_caution(caution) is None


# --- Facturation (B2) -----------------------------------------------------------------------------------------


@pytest.fixture
def facture(monkeypatch, modeles_documents, lieu):
    from apps.documents import services as documents
    from apps.finances.models import Prestation
    from apps.finances.tests.outils import PDF, grille_votee

    monkeypatch.setattr(documents, "convertir_en_pdfa", lambda nom, docx, transport=None: PDF)
    site, espace = lieu
    grille = grille_votee(espace)
    Prestation.objects.create(grille=grille, code="pret-tables", libelle="Prêt de tables", unite="forfait", prix_centimes=200)
    return _stock(site, 30, prestation_code="pret-tables")


def test_tar04_facture_sans_devis_avec_materiel_puis_avoir_quand_le_pret_est_annule(lieu, facture):
    from apps.finances import facturation

    _site, espace = lieu
    reservation = reserver(espace, SAMEDI, "14:00", "18:00", statut="validee", type_code="location")
    seance = reservation.occurrences.get()
    pret = services.reserver(reservation.dossier, facture, 10, acteur="système", occurrence=seance)
    piece = facturation.facturer(reservation.dossier, acteur="système")
    ligne = piece.lignes.get(nature="prestation")
    assert ligne.libelle == "Prêt de tables" and ligne.quantite == 10 and ligne.occurrence_id == seance.pk
    services.refuser(pret, acteur="système", motif="Tables déjà prises par la Ville")
    assert ligne.avoirs.exists(), "le prêt annulé est crédité"


def test_tar04_pret_ajoute_apres_acceptation_perime_le_devis(lieu, facture):
    from apps.finances import facturation
    from apps.noyau.exceptions import ErreurMetier

    _site, espace = lieu
    reservation = reserver(espace, SAMEDI, "14:00", "18:00", statut="validee", type_code="location")
    devis = facturation.etablir_devis(reservation.dossier, acteur="système")
    facturation.accepter_devis(devis, acteur="système")
    services.reserver(reservation.dossier, facture, 5, acteur="système", occurrence=reservation.occurrences.get())
    with pytest.raises(ErreurMetier) as refus:
        facturation.facturer(reservation.dossier, acteur="système")
    assert refus.value.code == "devis_perime"


# --- Droits (sécurité M1, M2) ---------------------------------------------------------------------------------


def test_rg14_catalogue_modifiable_seulement_tous_sites_et_prix_par_l_ordonnateur(client_agent, lieu):
    site, _espace = lieu
    article = _article()
    local = client_agent(agent("technicien_materiel", site))
    assert local.patch(f"/api/gestion/materiel/catalogue/{article.pk}", {"libelle": "Autre"}, format="json").status_code == 403
    ville = client_agent(agent("technicien_materiel"))
    assert (
        ville.patch(f"/api/gestion/materiel/catalogue/{article.pk}", {"libelle": "Table de banquet"}, format="json").status_code
        == 200
    )
    ville.patch(f"/api/gestion/materiel/catalogue/{article.pk}", {"valeur_journaliere_centimes": 1}, format="json")
    article.refresh_from_db()
    assert article.valeur_journaliere_centimes == 300, "champ réservé à l'ordonnateur"
    assert (
        ville.post(
            f"/api/gestion/materiel/catalogue/{article.pk}/tarif", {"valeur_journaliere_centimes": 450}, format="json"
        ).status_code
        == 403
    )
    financier = client_agent(agent("financier"))
    assert (
        financier.post(
            f"/api/gestion/materiel/catalogue/{article.pk}/tarif", {"valeur_journaliere_centimes": 450}, format="json"
        ).status_code
        == 200
    )
    assert (
        financier.post(
            f"/api/gestion/materiel/catalogue/{article.pk}/tarif", {"prestation_code": "inexistante"}, format="json"
        ).status_code
        == 400
    )


@pytest.mark.parametrize("role", ["direction", "controle_interne", "accueil"])
def test_rg14_panne_refusee_aux_roles_sans_signalement(client_agent, lieu, role):
    site, _espace = lieu
    stock = _stock(site)
    reponse = client_agent(agent(role)).post(
        f"/api/gestion/materiel/stocks/{stock.pk}/panne", {"quantite": 15, "description": "Tout est cassé"}, format="json"
    )
    assert reponse.status_code == 403
    assert not Panne.objects.exists()


def test_rg14_pret_et_transfert_hors_perimetre_refuses(client_agent, lieu):
    site, espace = lieu
    stock = _stock(site)
    reservation = _seance(espace)
    autre = SiteFabrique()
    hors = client_agent(agent("gestionnaire", autre))
    creation = hors.post(
        "/api/gestion/materiel/prets",
        {"dossier": reservation.dossier_id, "reservation": reservation.pk, "stock": stock.pk, "quantite": 1},
        format="json",
    )
    assert creation.status_code == 403
    local = client_agent(agent("technicien_materiel", site))
    transfert = local.post(
        f"/api/gestion/materiel/stocks/{stock.pk}/transferer", {"site": autre.pk, "quantite": 2}, format="json"
    )
    assert transfert.status_code == 403
    pret = services.reserver(reservation.dossier, stock, 1, acteur="système", occurrence=reservation.occurrences.get())
    assert hors.post(f"/api/gestion/materiel/prets/{pret.pk}/refuser", {"motif": "Non"}, format="json").status_code == 404


def test_mat05_remise_en_service_apres_controle_non_conforme_exige_un_controle_conforme(lieu, horloge):
    site, espace = lieu
    but = _article("but", libelle="But de handball", nature="fixe", periodicite_controle_jours=365)
    stock = services.entrer(but, site, 2, acteur="système", espace=espace)
    services.enregistrer_controle(
        stock, acteur="système", realise_le=date(2026, 11, 2), conforme=False, observations="Ancrage desserré"
    )
    panne = Panne.objects.get()
    with pytest.raises(Exception, match="contrôle conforme"):
        services.resoudre_panne(panne, acteur="système", issue="reparee")
    horloge.tick(timedelta(hours=2))
    services.enregistrer_controle(stock, acteur="système", realise_le=date(2026, 11, 2), conforme=True)
    assert services.resoudre_panne(panne, acteur="système", issue="reparee").statut == "reparee"


def test_mat04_alerte_seulement_une_fois_l_echeance_depassee(lieu):
    site, espace = lieu
    but = _article("but", libelle="But", nature="fixe", periodicite_controle_jours=365)
    stock = services.entrer(but, site, 2, acteur="système", espace=espace)
    services.enregistrer_controle(stock, acteur="système", realise_le=date(2025, 11, 2))
    stock.refresh_from_db()
    assert services.controles_en_retard([stock], jour=date(2026, 11, 2)) == []
    assert services.controles_en_retard([stock], jour=date(2026, 11, 3))


def test_mat02_annulation_d_une_seance_ne_libere_que_son_pret(lieu):
    site, espace = lieu
    stock = _stock(site)
    serie = valider_systeme(
        reserver(
            espace,
            date(2026, 11, 3),
            "18:00",
            "20:00",
            recurrence="FREQ=WEEKLY;COUNT=3",
            date_fin=date(2026, 11, 30),
            exclure_vacances=False,
        )
    )
    prets = services.reserver_pour_reservation(serie, stock, 4, acteur="système")
    premiere = serie.occurrences.order_by("debut").first()
    reservations.annuler_occurrence(premiere, acteur="système", motif="Gymnase fermé")
    statuts = list(
        ReservationMateriel.objects.filter(pk__in=[p.pk for p in prets]).order_by("debut").values_list("statut", flat=True)
    )
    assert statuts == ["annulee", "validee", "validee"]
