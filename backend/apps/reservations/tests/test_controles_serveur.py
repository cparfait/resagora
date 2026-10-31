"""Contrôles côté serveur ajoutés après les revues du lot 1 (sécurité et métier).

Chaque test échoue sans la règle correspondante : droits RG-14 sur les campagnes, conditions RG-06
refusées par défaut, transitions PLA-05/PLA-06, récurrences bornées, fermetures REF-06, hiérarchie
REF-05, capacité REF-07, saisons closes, paramètres ADM-02.
"""

from __future__ import annotations

import time as chrono
from datetime import date, timedelta

import pytest
from django.utils import timezone
from freezegun import freeze_time

from apps.noyau.exceptions import AccesRefuse, ErreurMetier, ErreurValidation
from apps.referentiel.calendrier import importer_saison
from apps.referentiel.models import Fermeture, Saison
from apps.reservations import campagne as services_campagne
from apps.reservations import conditions, services
from apps.reservations.models import Campagne, Occurrence, Reservation, TypeReservation, Verrou
from apps.reservations.recurrence import PARIS, valider_regle
from apps.usagers.models import PieceJustificative, TypePiece
from tests.fabriques import EspaceFabrique, SiteFabrique, agent, saison_2026, usager_avec_contact

from .outils import paris, reserver, valider_systeme

pytestmark = pytest.mark.django_db
CAMPAGNES = "/api/gestion/reservations/campagnes"


@pytest.fixture(autouse=True)
def maintenant():
    with freeze_time("2026-11-01 10:00"):
        yield


@pytest.fixture
def sites():
    site_a, site_b = SiteFabrique(nom="Site A"), SiteFabrique(nom="Site B")
    return site_a, site_b, EspaceFabrique(batiment__site=site_a), EspaceFabrique(batiment__site=site_b)


def _campagne(statut: str = "ouverte", *sites_campagne) -> Campagne:
    campagne = Campagne.objects.create(
        saison=saison_2026(), nom="Campagne 2026-2027", ouverture=date(2026, 10, 1), cloture=date(2026, 12, 1), statut=statut
    )
    campagne.sites.set(sites_campagne)
    return campagne


def _demande_campagne(campagne: Campagne, espace, **champs) -> Reservation:
    r = reserver(
        espace, date(2026, 11, 3), "18:00", "20:00", recurrence="FREQ=WEEKLY;BYDAY=TU", date_fin=date(2026, 12, 15), **champs
    )
    r.dossier.campagne, r.dossier.saison = campagne, campagne.saison
    r.dossier.save()
    return r


# --- RG-14 : campagnes ---------------------------------------------------------------------------


def test_rg14_campagne_tous_sites_reservee_a_un_perimetre_ville_entiere(client_agent, sites):
    site_a, _site_b, _ea, _eb = sites
    corps = {"saison": saison_2026().pk, "nom": "Saison", "ouverture": "2026-10-01", "cloture": "2026-12-01", "sites": []}
    assert client_agent(agent("gestionnaire", site_a)).post(CAMPAGNES, corps, format="json").status_code == 403
    assert client_agent(agent("gestionnaire")).post(CAMPAGNES, corps, format="json").status_code == 201
    assert (
        client_agent(agent("gestionnaire", site_a)).post(CAMPAGNES, {**corps, "sites": [site_a.pk]}, format="json").status_code
        == 201
    )


def test_rg14_attribution_hors_perimetre_refusee_et_analyse_filtree(sites):
    site_a, _site_b, _espace_a, espace_b = sites
    campagne = _campagne("commission")
    demande_b = _demande_campagne(campagne, espace_b)
    _demande_campagne(campagne, espace_b)
    elu_a = agent("elu_commission", site_a)
    with pytest.raises(AccesRefuse):
        services_campagne.attribuer(campagne, {demande_b.pk: {"decision": "attribuer"}}, acteur=elu_a)
    assert Reservation.objects.get(pk=demande_b.pk).statut == "demande"
    assert services_campagne.analyser(campagne, agent=agent("accueil", site_a)) == []
    assert services_campagne.analyser(campagne, agent=agent("accueil")) != []


def test_pla05_attribution_limitee_aux_demandes_en_cours(sites):
    _a, _b, espace_a, _eb = sites
    campagne = _campagne("commission")
    annulee = _demande_campagne(campagne, espace_a)
    Reservation.objects.filter(pk=annulee.pk).update(statut="annulee")
    with pytest.raises(ErreurMetier) as refus:
        services_campagne.attribuer(campagne, {annulee.pk: {"decision": "attribuer"}}, acteur=agent("elu_commission"))
    assert refus.value.code == "transition_interdite"
    assert not Verrou.objects.filter(occurrence__reservation=annulee).exists()


def test_pla05_depot_dans_une_campagne_fermee_refuse(sites):
    campagne = _campagne("commission")
    with pytest.raises(ErreurValidation) as refus:
        services.creer_dossier(
            acteur=agent("gestionnaire"),
            usager=usager_avec_contact(),
            type_reservation=TypeReservation.objects.get(code="creneau_annuel"),
            objet="Créneaux",
            campagne=campagne,
        )
    assert refus.value.code == "campagne_fermee"


# --- RG-06, PLA-06 : conditions et transitions -----------------------------------------------------


def test_rg06_confirmation_sans_convention_ni_caution_refusee_puis_attestee(sites):
    _a, _b, espace, _eb = sites
    usager = usager_avec_contact()
    for type_piece in TypePiece.objects.filter(types_usager__contains=[usager.type], obligatoire=True):
        PieceJustificative.objects.create(
            usager=usager, type_piece=type_piece, fichier=_fichier(), statut="valide", valide_jusqu_au=date(2027, 12, 31)
        )
    r = valider_systeme(reserver(espace, date(2026, 12, 12), "14:00", "18:00", usager=usager, type_code="location"))
    with pytest.raises(ErreurMetier) as refus:
        services.confirmer(r, acteur=agent("gestionnaire"))
    manques = " ".join(refus.value.details["manques"])
    assert "convention" in manques and "acompte" in manques and "caution" in manques
    gestionnaire = agent("gestionnaire")
    for code in ("convention", "acompte", "caution"):
        conditions.attester(r.dossier, code, acteur=gestionnaire, motif="Constaté au guichet")
    assert services.confirmer(r, acteur=gestionnaire).statut == "confirmee"
    with pytest.raises(AccesRefuse):
        conditions.attester(r.dossier, "caution", acteur=agent("accueil"), motif="Chèque reçu")


def test_rg06_pieces_valides_jusqu_a_la_derniere_seance(sites):
    _a, _b, espace, _eb = sites
    saison_2026()
    usager = usager_avec_contact()
    for type_piece in TypePiece.objects.filter(types_usager__contains=[usager.type], obligatoire=True):
        PieceJustificative.objects.create(
            usager=usager, type_piece=type_piece, fichier=_fichier(), statut="valide", valide_jusqu_au=date(2026, 12, 31)
        )
    r = reserver(
        espace, date(2026, 11, 3), "18:00", "20:00", usager=usager, recurrence="FREQ=WEEKLY;BYDAY=TU", date_fin=date(2027, 3, 30)
    )
    assert any("dernière séance" in m for m in conditions.conditions_manquantes(r))


def test_pla06_cloture_impossible_hors_validee_confirmee(sites):
    _a, _b, espace, _eb = sites
    with freeze_time("2026-11-01 10:00"):
        r = reserver(espace, date(2026, 11, 5), "18:00", "20:00")
        services.refuser(r, acteur=agent("gestionnaire"), motif="Complet")
    with freeze_time("2026-11-10 10:00"), pytest.raises(ErreurMetier) as refus:
        services.cloturer(r, acteur=agent("gestionnaire"))
    assert refus.value.code == "transition_interdite"
    assert not Occurrence.objects.filter(reservation=r, statut="cloturee").exists()


# --- PLA-04 : récurrences bornées, séries ------------------------------------------------------------


@pytest.mark.parametrize(
    "regle",
    [
        "FREQ=DAILY;BYMONTHDAY=99",
        "FREQ=WEEKLY;BYDAY=-9MO",
        "FREQ=MONTHLY;INTERVAL=12;BYMONTHDAY=31",
        "FREQ=YEARLY",
        "FREQ=DAILY;INTERVAL=0",
    ],
)
def test_pla04_regle_pathologique_refusee_immediatement(regle):
    debut = chrono.perf_counter()
    with pytest.raises(ErreurValidation):
        valider_regle(regle)
    assert chrono.perf_counter() - debut < 0.1


def test_pla04_sans_calendrier_importe_les_vacances_ne_peuvent_pas_etre_exclues(sites):
    _a, _b, espace, _eb = sites
    saison_2026(vacances=False)
    with pytest.raises(ErreurValidation) as refus:
        reserver(espace, date(2026, 11, 3), "18:00", "20:00", recurrence="FREQ=WEEKLY;BYDAY=TU", date_fin=date(2026, 12, 29))
    assert refus.value.code == "calendrier_absent"


def test_adm01_import_du_calendrier_recalcule_les_series(sites):
    _a, _b, espace, _eb = sites
    saison = saison_2026(vacances=False)
    r = reserver(
        espace,
        date(2026, 11, 3),
        "18:00",
        "20:00",
        recurrence="FREQ=WEEKLY;BYDAY=TU",
        date_fin=date(2027, 1, 12),
        exclure_vacances=False,
    )
    r.exclure_vacances = True
    r.save()
    assert Occurrence.objects.filter(reservation=r, debut__date=date(2026, 12, 22)).exists()
    fichier = b'{"results": [{"description": "Vacances de No\\u00ebl", "start_date": "2026-12-18T23:00:00+00:00", "end_date": "2027-01-03T23:00:00+00:00", "population": "-"}]}'
    importer_saison(saison, fichier=fichier, acteur="test")
    services.appliquer_calendrier(saison, acteur="test")
    jours = {timezone.localtime(o.debut, PARIS).date() for o in Occurrence.objects.filter(reservation=r)}
    assert date(2026, 12, 22) not in jours and date(2027, 1, 5) in jours


def test_pla04_modifier_suivantes_conserve_les_annulations_tardives(sites):
    _a, _b, espace, _eb = sites
    saison_2026()
    r = valider_systeme(
        reserver(espace, date(2026, 11, 3), "18:00", "20:00", recurrence="FREQ=WEEKLY;BYDAY=TU", date_fin=date(2026, 12, 15))
    )
    seances = list(r.occurrences.order_by("debut"))
    contact = r.dossier.usager.rattachements.first().contact
    with freeze_time("2026-11-16 10:00"):
        tardive = services.annuler_occurrence(seances[2], acteur=contact, motif="Imprévu", par_usager=True)
    assert tardive.annulation_tardive
    suite = services.modifier_suivantes(seances[1], acteur=agent("gestionnaire"), heure_debut=paris(2026, 1, 1, 19).time())
    tardive.refresh_from_db()
    assert tardive.reservation_id == suite.pk and tardive.statut == "annulee" and tardive.annulation_tardive
    jours = [timezone.localtime(o.debut, PARIS).date() for o in suite.occurrences.exclude(statut="annulee")]
    assert date(2026, 11, 17) not in jours and len(jours) == len(set(jours))


def test_pla04_toute_la_serie_ne_recree_pas_une_seance_deplacee(sites):
    _a, _b, espace, _eb = sites
    saison_2026()
    r = valider_systeme(
        reserver(espace, date(2026, 11, 3), "18:00", "20:00", recurrence="FREQ=WEEKLY;BYDAY=TU", date_fin=date(2026, 12, 15))
    )
    seance = r.occurrences.order_by("debut")[1]
    gestionnaire = agent("gestionnaire")
    services.deplacer_occurrence(
        seance, acteur=gestionnaire, espace=espace, debut=paris(2026, 11, 11, 18), fin=paris(2026, 11, 11, 20)
    )
    services.modifier_serie(r, acteur=gestionnaire, date_fin=date(2026, 12, 22))
    jours = [timezone.localtime(o.debut, PARIS).date() for o in Reservation.objects.get(pk=r.pk).occurrences.all()]
    assert date(2026, 11, 10) not in jours and date(2026, 11, 11) in jours


def test_pla04_serie_refusee_non_modifiable(sites):
    _a, _b, espace, _eb = sites
    saison_2026()
    r = reserver(espace, date(2026, 11, 3), "18:00", "20:00", recurrence="FREQ=WEEKLY;BYDAY=TU", date_fin=date(2026, 12, 15))
    services.refuser(r, acteur=agent("gestionnaire"), motif="Complet")
    with pytest.raises(ErreurMetier):
        services.modifier_serie(r, acteur=agent("gestionnaire"), date_fin=date(2027, 1, 26))


def test_pla04_heure_inexistante_au_passage_a_l_heure_d_ete(sites):
    _a, _b, espace, _eb = sites
    with pytest.raises(ErreurValidation) as refus:
        reserver(espace, date(2027, 3, 28), "02:30", "03:30")
    assert refus.value.code == "heure_inexistante"


# --- PLA-04, REF-03 : dérogations et durées -------------------------------------------------------


def test_ref03_derogation_horaires_reservee_et_motivee(sites):
    from apps.referentiel.models import HoraireOuverture

    site_a, _b, espace, _eb = sites
    for jour in range(7):
        HoraireOuverture.objects.create(
            espace=espace, jour_semaine=jour, debut=paris(2026, 1, 1, 8).time(), fin=paris(2026, 1, 1, 22).time()
        )
    accueil = agent("accueil", site_a)
    with pytest.raises(AccesRefuse):
        reserver(espace, date(2026, 11, 10), "22:00", "23:00", acteur=accueil, forcer_horaires=True, motif_forcage="Match tardif")
    with pytest.raises(ErreurValidation):
        reserver(espace, date(2026, 11, 10), "22:00", "23:00", acteur=agent("gestionnaire", site_a), forcer_horaires=True)
    r = reserver(
        espace,
        date(2026, 11, 10),
        "22:00",
        "23:00",
        acteur=agent("gestionnaire", site_a),
        forcer_horaires=True,
        motif_forcage="Match tardif",
    )
    assert r.occurrences.count() == 1


def test_pla04_duree_maximale_appliquee_aux_seances_ponctuelles(sites):
    _a, _b, espace, _eb = sites
    with pytest.raises(ErreurValidation) as refus:
        reserver(espace, date(2026, 11, 10), "08:00", "09:00", date_fin=date(2027, 11, 10))
    assert refus.value.code in {"duree_excessive", "horizon_depasse"}


# --- REF-06 : fermetures -----------------------------------------------------------------------------


def test_ref06_fermeture_controlee_a_la_creation_et_au_deplacement(sites):
    _a, _b, espace, autre = sites
    saison_2026()
    Fermeture.objects.create(espace=espace, debut=paris(2026, 11, 9, 0), fin=paris(2026, 11, 19, 0), motif="Travaux")
    with pytest.raises(ErreurValidation) as refus:
        reserver(espace, date(2026, 11, 10), "18:00", "20:00")
    assert refus.value.code == "fermeture"
    serie = reserver(espace, date(2026, 11, 3), "18:00", "20:00", recurrence="FREQ=WEEKLY;BYDAY=TU", date_fin=date(2026, 11, 24))
    jours = [timezone.localtime(o.debut, PARIS).date() for o in serie.occurrences.all()]
    assert date(2026, 11, 10) not in jours and date(2026, 11, 17) not in jours and date(2026, 11, 24) in jours
    seance = valider_systeme(reserver(autre, date(2026, 11, 12), "18:00", "20:00")).occurrences.get()
    with pytest.raises(ErreurValidation):
        services.deplacer_occurrence(
            seance, acteur=agent("gestionnaire"), espace=espace, debut=paris(2026, 11, 12, 18), fin=paris(2026, 11, 12, 20)
        )


# --- REF-05 : hiérarchie modifiée après la pose des verrous -----------------------------------------


def test_ref05_ajout_d_un_sous_espace_replace_les_verrous(sites):
    _a, _b, gymnase, _eb = sites
    valider_systeme(reserver(gymnase, date(2026, 11, 10), "18:00", "20:00"))
    tiers = EspaceFabrique(batiment=gymnase.batiment, parent=gymnase, nom="Tiers 1")
    services.recalculer_verrous([tiers])
    assert services.conflits(tiers, paris(2026, 11, 10, 18), paris(2026, 11, 10, 20))
    assert Verrou.objects.filter(feuille=tiers).exists()


# --- REF-07 : capacité simultanée -------------------------------------------------------------------


def test_ref07_capacite_comptee_au_maximum_simultane(sites):
    _a, _b, _ea, _eb = sites
    salle = EspaceFabrique(partageable=True, capacite_simultanee=2)
    valider_systeme(reserver(salle, date(2026, 11, 10), "18:00", "19:00"))
    valider_systeme(reserver(salle, date(2026, 11, 10), "19:00", "20:00"))
    assert services.conflits(salle, paris(2026, 11, 10, 18), paris(2026, 11, 10, 20)) == []
    valider_systeme(reserver(salle, date(2026, 11, 10), "18:30", "19:30"))
    assert services.conflits(salle, paris(2026, 11, 10, 18), paris(2026, 11, 10, 20))


# --- PLA-07 : alternatives au changement d'heure ---------------------------------------------------


def test_pla07_alternative_semaine_suivante_meme_heure_locale(sites):
    _a, _b, espace, _eb = sites
    valider_systeme(reserver(espace, date(2026, 10, 20), "18:00", "20:00", exclure_vacances=False))
    with freeze_time("2026-10-01 10:00"):
        propositions = services.alternatives(espace, paris(2026, 10, 20, 18), paris(2026, 10, 20, 20))
    semaines = [p for p in propositions if p["raison"].startswith("même créneau")]
    from datetime import datetime

    assert all(datetime.fromisoformat(p["debut"]).astimezone(PARIS).hour == 18 for p in semaines)


# --- Saison close -----------------------------------------------------------------------------------


def test_pla04_saison_close_ni_creation_ni_modification(sites):
    _a, _b, espace, _eb = sites
    saison = saison_2026()
    Saison.objects.filter(pk=saison.pk).update(cloturee=True)
    with pytest.raises(ErreurMetier) as refus:
        reserver(espace, date(2026, 11, 10), "18:00", "20:00")
    assert refus.value.code == "saison_close"


# --- ADM-02 : paramètres validés selon leur schéma ---------------------------------------------------


@pytest.mark.parametrize(
    ("cle", "valeur"),
    [
        ("priorites.ordre", []),
        ("temps_scolaire", {}),
        ("options.duree_jours", 10**18),
        ("annulation.bareme", [{"heures_avant": 72, "taux": 2500}]),
    ],
)
def test_adm02_parametre_invalide_refuse(client_agent, cle, valeur):
    reponse = client_agent(agent("administrateur")).patch("/api/gestion/parametres", {"valeurs": {cle: valeur}}, format="json")
    assert reponse.status_code == 400 and cle in reponse.json()["details"]["champs"]


# --- RG-14 : lectures inter-sites ---------------------------------------------------------------------


def test_rg14_historique_et_apercu_limites_au_perimetre(client_agent, sites):
    site_a, _b, _ea, espace_b = sites
    usager = usager_avec_contact()
    valider_systeme(reserver(espace_b, date(2026, 11, 10), "18:00", "20:00", usager=usager))
    historique = client_agent(agent("accueil", site_a)).get(f"/api/gestion/usagers/usagers/{usager.pk}/historique").json()
    assert historique["dossiers"] == [] and historique["occurrences_total"] == 0
    corps = {
        "espace": espace_b.pk,
        "date_debut": "2026-11-10",
        "date_fin": "2026-11-10",
        "heure_debut": "18:00",
        "heure_fin": "20:00",
    }
    assert (
        client_agent(agent("accueil", site_a)).post("/api/gestion/reservations/dossiers/apercu", corps, format="json").status_code
        == 403
    )


def test_rg14_statut_et_type_d_usager_proteges(client_agent):
    usager = usager_avec_contact(statut="en_attente")
    accueil = client_agent(agent("accueil"))
    accueil.patch(f"/api/gestion/usagers/usagers/{usager.pk}", {"statut": "valide"}, format="json")
    usager.refresh_from_db()
    assert usager.statut == "en_attente"
    refus = client_agent(agent("gestionnaire")).patch(
        f"/api/gestion/usagers/usagers/{usager.pk}", {"type": "service_municipal"}, format="json"
    )
    assert refus.status_code == 400
    assert accueil.post(f"/api/gestion/usagers/usagers/{usager.pk}/valider").status_code == 403
    assert client_agent(agent("gestionnaire")).post(f"/api/gestion/usagers/usagers/{usager.pk}/valider").status_code == 200


def test_rg06_dossier_fige_apres_validation(client_agent, sites):
    _a, _b, espace, _eb = sites
    r = valider_systeme(reserver(espace, date(2026, 11, 10), "18:00", "20:00", type_code="location"))
    reponse = client_agent(agent("gestionnaire")).patch(
        f"/api/gestion/reservations/dossiers/{r.dossier_id}",
        {"type_reservation": TypeReservation.objects.get(code="scolaire").pk},
        format="json",
    )
    assert reponse.status_code == 409 and reponse.json()["code"] == "dossier_fige"


def _fichier():
    from apps.noyau.fichiers import enregistrer_genere

    return enregistrer_genere("piece.pdf", b"%PDF-1.7 test", "application/pdf")


def test_pla09_liste_d_attente_exige_un_creneau_occupe(sites):
    _a, _b, espace, _eb = sites
    usager = usager_avec_contact()
    with pytest.raises(ErreurMetier):
        services.inscrire_liste_attente(
            acteur=agent("gestionnaire"), espace=espace, debut=paris(2026, 11, 20, 18), fin=paris(2026, 11, 20, 20), usager=usager
        )
    with pytest.raises(ErreurValidation):
        services.inscrire_liste_attente(
            acteur=agent("gestionnaire"),
            espace=espace,
            debut=paris(2026, 11, 20, 20),
            fin=paris(2026, 11, 20, 18) - timedelta(hours=1),
            usager=usager,
        )
