"""Corrections des revues du lot 6 — valorisation : montant payé (frais d'annulation, avoirs), devis, espace partagé,
matériel prêt par prêt, personnel des séances annulées (VAL-02, VAL-03, RG-12) ; exercice clos immuable et clôture
qui recalcule (VAL-08) ; paramètres figés par exercice (VAL-01) ; import du numéraire (VAL-06) ; annexe (VAL-05) ;
bénéficiaires exclus (D-061) ; droits rôle × périmètre (RG-14)."""

from __future__ import annotations

from datetime import date, timedelta

import pytest
from django.core.files.uploadedfile import SimpleUploadedFile
from django.db import DatabaseError, transaction
from django.test import override_settings
from freezegun import freeze_time

from apps.finances.models import Reduction
from apps.finances.tests.outils import PDF, grille_votee
from apps.noyau.exceptions import AccesRefuse, ErreurMetier
from apps.reservations import services as reservations
from apps.reservations.tests.outils import reserver
from apps.valorisation import services
from apps.valorisation.models import Exercice, MethodeValorisation, SubventionNumeraire, Valorisation
from tests.fabriques import EspaceFabrique, agent, usager_avec_contact

pytestmark = pytest.mark.django_db
MARDI = date(2026, 11, 10)


@pytest.fixture(autouse=True)
def horloge(monkeypatch, modeles_documents):
    from apps.documents import services as documents
    from apps.noyau import fichiers

    monkeypatch.setattr(documents, "convertir_en_pdfa", lambda nom, docx, transport=None: PDF)
    monkeypatch.setattr(fichiers, "analyser_clamav", lambda contenu: None)
    with freeze_time("2026-11-01 10:00") as h:
        yield h


@pytest.fixture
def espace():
    espace = EspaceFabrique(nom="Gymnase des Écoles", surface_m2=900)
    grille_votee(espace)  # association locale : 20 € de l'heure
    return espace


@pytest.fixture
def exercice():
    return Exercice.objects.create(annee=2026)


def _reduction(usager, taux=10000):
    return Reduction.objects.create(usager=usager, taux=taux, fondement="Convention d'objectifs 2026", debut=date(2026, 1, 1))


def _seance(espace, usager, jour=MARDI, debut="18:00", fin="20:00"):
    return reserver(espace, jour, debut, fin, usager=usager, statut="validee").occurrences.get()


def _meme_grille(source, cible):
    """Ajoute à la grille votée de `source` les tarifs de `cible` (une seule grille en vigueur à une date)."""
    from apps.finances.models import Tarif

    for tarif in Tarif.objects.filter(espace=source):
        Tarif.objects.create(
            grille=tarif.grille,
            espace=cible,
            categorie=tarif.categorie,
            unite=tarif.unite,
            prix_centimes=tarif.prix_centimes,
            caution_centimes=tarif.caution_centimes,
        )


def _espaces(resultat):
    return {ligne.occurrence.pk: ligne for ligne in resultat.lignes if ligne.nature == "espace"}


# --- Montant payé : frais d'annulation tardive (B1) ------------------------------------------------------------


def test_rg12_annulation_tardive_d_une_association_payante_les_frais_sont_deduits(espace, exercice, horloge):
    """2 h à 20 € = 40 € ; annulée 48 h avant : 50 % de frais (20 €) → 20 € valorisés ; moins de 24 h avant : 100 %
    de frais → rien ; séance tenue, due et non encore facturée → rien."""
    club = usager_avec_contact(nom="Club payant")
    a_48h = _seance(espace, club)
    a_10h = _seance(espace, club, jour=MARDI + timedelta(days=7))
    tenue = _seance(espace, club, jour=MARDI + timedelta(days=14))
    horloge.move_to("2026-11-08 18:00")
    reservations.annuler_occurrence(a_48h, acteur=agent("gestionnaire"), motif="Match reporté", par_usager=True)
    horloge.move_to("2026-11-17 08:00")
    reservations.annuler_occurrence(a_10h, acteur=agent("gestionnaire"), motif="Salle inutile", par_usager=True)
    horloge.move_to("2026-12-31 18:00")
    lignes = _espaces(services.calculer(club, exercice))
    assert (lignes[a_48h.pk].montant_reference, lignes[a_48h.pk].montant_paye, lignes[a_48h.pk].montant_valorise) == (
        4000,
        2000,
        2000,
    )
    assert lignes[a_10h.pk].montant_paye == 4000 and lignes[a_10h.pk].montant_valorise == 0
    assert lignes[tenue.pk].montant_paye == 4000 and lignes[tenue.pk].montant_valorise == 0


# --- Espace partagé (M2) ---------------------------------------------------------------------------------------


def test_val02_espace_partage_avec_reduction_partielle_seule_la_part_de_l_ecart(exercice):
    """Piste partagée, deux clubs à 50 % : chacun paie 20 € pour un créneau de 40 € → (40 − 20) × 50 % = 10 €."""
    piste = EspaceFabrique(nom="Piste", partageable=True, capacite_simultanee=2)
    grille_votee(piste)
    athle, triathlon = usager_avec_contact(nom="Athlétisme"), usager_avec_contact(nom="Triathlon")
    for club in (athle, triathlon):
        _reduction(club, 5000)
        _seance(piste, club)
    for club in (athle, triathlon):
        ligne = services.calculer(club, exercice).lignes[0]
        assert (ligne.part, ligne.montant_paye, ligne.montant_valorise) == (5000, 2000, 1000)


# --- Matériel prêt par prêt (M3, m5) ---------------------------------------------------------------------------


def test_val02_deux_prets_facturees_sur_la_meme_seance_chacun_sa_ligne(exercice):
    from apps.finances import facturation
    from apps.finances.models import Prestation
    from apps.materiel import services as materiel
    from apps.materiel.models import Materiel

    salle = EspaceFabrique(nom="Salle polyvalente")
    grille = grille_votee(salle)
    Prestation.objects.create(grille=grille, code="pret-tables", libelle="Prêt de tables", unite="forfait", prix_centimes=200)
    Prestation.objects.create(
        grille=grille, code="pret-sono", libelle="Prêt de sonorisation", unite="forfait", prix_centimes=3000
    )
    site = salle.batiment.site
    tables = materiel.entrer(
        Materiel.objects.create(
            code="table", libelle="Table", unite="table", valeur_journaliere_centimes=300, prestation_code="pret-tables"
        ),
        site,
        30,
        acteur="système",
    )
    sono = materiel.entrer(
        Materiel.objects.create(
            code="sono", libelle="Sonorisation", unite="ensemble", valeur_journaliere_centimes=5000, prestation_code="pret-sono"
        ),
        site,
        2,
        acteur="système",
    )
    reservation = reserver(salle, date(2026, 11, 14), "14:00", "18:00", statut="validee", type_code="location")
    seance = reservation.occurrences.get()
    materiel.reserver(reservation.dossier, tables, 10, acteur="système", occurrence=seance)
    materiel.reserver(reservation.dossier, sono, 1, acteur="système", occurrence=seance)
    facturation.facturer(reservation.dossier, acteur="système")
    lignes = [ligne for ligne in services.calculer(reservation.dossier.usager, exercice).lignes if ligne.nature == "materiel"]
    # Tables : 10 × 3 € − 10 × 2 € = 10 € ; sono : 50 € − 30 € = 20 €.
    assert sorted((ligne.montant_reference, ligne.montant_paye, ligne.montant_valorise) for ligne in lignes) == [
        (3000, 2000, 1000),
        (5000, 3000, 2000),
    ]


def test_val02_beneficiaire_du_seul_materiel_et_particulier_exclu(exercice):
    from apps.materiel import services as materiel
    from apps.materiel.models import Materiel

    salle = EspaceFabrique(nom="Maison des associations")
    association = usager_avec_contact(nom="Comité des fêtes")
    stock = materiel.entrer(
        Materiel.objects.create(code="barnum", libelle="Barnum", unite="barnum", valeur_journaliere_centimes=4000),
        salle.batiment.site,
        4,
        acteur="système",
    )
    # Séance d'une autre année (hors exercice) ; le prêt sur une période, lui, tombe en 2026 : seul le matériel compte.
    reservation = reserver(salle, date(2026, 11, 21), "09:00", "19:00", usager=association, statut="validee")
    seance = reservation.occurrences.get()
    materiel.reserver(reservation.dossier, stock, 2, acteur="système", debut=seance.debut, fin=seance.fin)
    type(seance).objects.filter(pk=seance.pk).update(statut="annulee", annulation_tardive=False)
    particulier = usager_avec_contact(nom="Particulier", type="particulier")
    _seance(EspaceFabrique(nom="Salle B"), particulier)
    assert association in services.beneficiaires(exercice)
    assert particulier not in services.beneficiaires(exercice)
    with pytest.raises(ErreurMetier) as refus:
        services.valoriser(particulier, exercice, acteur="système")
    assert refus.value.code == "beneficiaire_exclu"


# --- Personnel des séances annulées (m3) et paramètres de l'exercice (M8) --------------------------------------


def test_val02_gardiennage_non_valorise_sur_une_seance_annulee_hors_delai(exercice, horloge):
    gymnase = EspaceFabrique(nom="Gymnase gardienné", gardiennage_requis=True)
    grille_votee(gymnase)
    club = usager_avec_contact(nom="Club de lutte")
    _reduction(club)
    tenue, annulee = _seance(gymnase, club), _seance(gymnase, club, jour=MARDI + timedelta(days=1))
    horloge.move_to("2026-11-10 20:00")
    reservations.annuler_occurrence(annulee, acteur=agent("gestionnaire"), motif="Absents", par_usager=True)
    personnel = [ligne for ligne in services.calculer(club, exercice).lignes if ligne.nature == "personnel"]
    assert [ligne.occurrence.pk for ligne in personnel] == [tenue.pk]


def test_val08_parametres_figes_par_exercice(client_agent):
    from apps.noyau.models import Parametre
    from apps.noyau.parametres import invalider

    gymnase = EspaceFabrique(nom="Gymnase gardienné", gardiennage_requis=True)
    grille_votee(gymnase)
    reponse = client_agent(agent("financier")).post("/api/gestion/valorisation/exercices", {"annee": 2026}, format="json")
    assert reponse.status_code == 201 and reponse.json()["cout_horaire_personnel_centimes"] == 3200
    exercice = Exercice.objects.get(annee=2026)
    club = usager_avec_contact(nom="Club de boxe")
    _reduction(club)
    _seance(gymnase, club)
    avant = services.calculer(club, exercice).somme("personnel")
    Parametre.objects.update_or_create(cle="valorisation.cout_horaire_personnel_centimes", defaults={"valeur": 6400})
    invalider()
    assert services.calculer(club, exercice).somme("personnel") == avant > 0


# --- Exercice clos (B2, B3, M5, m6) ----------------------------------------------------------------------------


def test_val08_la_cloture_recalcule_une_version_perimee(espace, exercice, horloge):
    """Calcul le 15/12 avec trois séances ; deux sont annulées à temps le 20/12 ; la clôture du 15/01 fige 40 €, pas
    120 €, dans une nouvelle version motivée ; l'ancienne version est figée aussi."""
    club = usager_avec_contact(nom="Club de natation")
    _reduction(club)
    horloge.move_to("2026-12-01 10:00")
    _seance(espace, club, jour=date(2026, 12, 8))
    fin_annee = [_seance(espace, club, jour=date(2026, 12, j)) for j in (29, 30)]
    horloge.move_to("2026-12-15 10:00")
    premiere = services.valoriser(club, exercice, acteur="système")
    assert premiere.total == 12000
    horloge.move_to("2026-12-20 10:00")
    for seance in fin_annee:
        reservations.annuler_occurrence(seance, acteur=agent("gestionnaire"), motif="Vacances", par_usager=True)
    horloge.move_to("2027-01-15 10:00")
    services.cloturer(exercice, acteur="système")
    actuelle = Valorisation.objects.get(usager=club, exercice=exercice, actuelle=True)
    assert actuelle.total == 4000 and actuelle.figee and actuelle.version == 2 and "clôture" in actuelle.motif_recalcul
    premiere.refresh_from_db()
    assert premiere.figee and not premiere.actuelle


def test_val08_exercice_clos_ni_annee_ni_parametres_ni_subventions_ni_methodes(espace, exercice, horloge, client_agent):
    club = usager_avec_contact(nom="Club de tennis")
    _reduction(club)
    _seance(espace, club)
    autre = Exercice.objects.create(annee=2027)
    methode = MethodeValorisation.objects.create(exercice=exercice, famille=espace.famille, methode="tarif_reference")
    services.valoriser(club, exercice, acteur="système")
    horloge.move_to("2027-01-15 10:00")
    services.cloturer(exercice, acteur="système")
    financier = client_agent(agent("financier"))
    url = f"/api/gestion/valorisation/exercices/{exercice.pk}"
    assert financier.patch(url, {"annee": 2025}, format="json").status_code == 400
    assert financier.patch(url, {"cout_horaire_personnel_centimes": 1}, format="json").status_code == 400
    assert financier.patch(url, {"date_limite_attestations": "2027-04-30"}, format="json").status_code == 200
    assert (
        financier.patch(f"/api/gestion/valorisation/methodes/{methode.pk}", {"exercice": autre.pk}, format="json").status_code
        == 400
    )
    fichier = SimpleUploadedFile("s.csv", b"identifiant;montant\nClub de tennis;100,00\n")
    assert financier.post(f"{url}/subventions", {"fichier": fichier}, format="multipart").status_code == 409
    # La base refuse aussi, quel que soit le chemin (déclencheurs).
    for ecriture in (
        lambda: Exercice.objects.filter(pk=exercice.pk).update(annee=2025),
        lambda: Exercice.objects.filter(pk=exercice.pk).update(statut="ouvert"),
        lambda: SubventionNumeraire.objects.create(exercice=exercice, usager=club, montant_centimes=100),
        lambda: MethodeValorisation.objects.filter(pk=methode.pk).update(methode="cout_revient"),
        lambda: Valorisation.objects.filter(exercice=exercice).update(calcule_par="quelqu'un"),
    ):
        with pytest.raises(DatabaseError), transaction.atomic():
            ecriture()


# --- Import du numéraire (M6, m2 sécurité) ---------------------------------------------------------------------


def test_val06_import_montants_stricts_et_homonymes_refuses(exercice):
    unique = usager_avec_contact(nom="Club unique")
    usager_avec_contact(nom="Homonyme")
    usager_avec_contact(nom="Homonyme")
    contenu = b"identifiant;montant\nClub unique;22 980,50\nClub unique;22.980\nHomonyme;100,00\nClub unique;1e400\n"
    rapport = services.importer_subventions(exercice, contenu, acteur="système")
    assert rapport["confirmation_requise"] and len(rapport["rejets"]) == 3
    assert any("22.980" in r for r in rapport["rejets"]) and any("plusieurs" in r for r in rapport["rejets"])
    rapport = services.importer_subventions(exercice, contenu, acteur="système", confirmer=True)
    assert rapport["importees"] == 1
    assert SubventionNumeraire.objects.get(usager=unique).montant_centimes == 2_298_050


def test_val06_un_fichier_sans_ligne_valable_ne_remplace_pas_l_import_precedent(exercice):
    club = usager_avec_contact(nom="Club fidèle")
    services.importer_subventions(exercice, "identifiant;montant\nClub fidèle;1 000,00\n".encode(), acteur="système")
    with pytest.raises(Exception):  # noqa: B017 — ErreurValidation « import_vide »
        services.importer_subventions(exercice, b"identifiant;montant\ninconnu;10,00\n", acteur="système", confirmer=True)
    assert SubventionNumeraire.objects.get(usager=club).montant_centimes == 100_000


# --- Annexe (m4) -------------------------------------------------------------------------------------------------


def test_val05_annexe_sans_ecole_ni_ligne_nulle_et_noms_neutralises(espace, exercice):
    hostile = usager_avec_contact(nom="=SOMME(A1:A9)")
    ecole = usager_avec_contact(nom="École Jules-Ferry", type="ecole")
    payant = usager_avec_contact(nom="Club qui paie tout")
    for decalage, usager in enumerate((hostile, ecole)):
        _reduction(usager)
        _seance(espace, usager, jour=MARDI + timedelta(days=7 * decalage))
    _seance(espace, payant, jour=MARDI + timedelta(days=1))
    services.valoriser_exercice(exercice, acteur="système")
    texte = services.annexe_csv(exercice).decode("utf-8-sig")
    assert "'=SOMME(A1:A9)" in texte
    assert "École Jules-Ferry" not in texte and "Club qui paie tout" not in texte


# --- Droits rôle × périmètre (M1, M2, m4 sécurité ; règle 2 de CLAUDE.md) ---------------------------------------


def test_rg14_un_financier_limite_a_un_site_ne_modifie_pas_la_valorisation_de_la_ville(espace, exercice, horloge, client_agent):
    club = usager_avec_contact(nom="Club de basket")
    _reduction(club)
    _seance(espace, club)
    services.valoriser(club, exercice, acteur="système")
    horloge.move_to("2027-01-15 10:00")
    local = client_agent(agent("financier", espace.batiment.site))
    url = f"/api/gestion/valorisation/exercices/{exercice.pk}"
    assert local.post(f"{url}/calculer", {}, format="json").status_code == 403
    assert local.post(f"{url}/calculer", {"usager": club.pk}, format="json").status_code == 403
    fichier = SimpleUploadedFile("s.csv", b"identifiant;montant\nClub de basket;100,00\n")
    assert local.post(f"{url}/subventions", {"fichier": fichier}, format="multipart").status_code == 403
    assert (
        local.post(
            "/api/gestion/valorisation/methodes",
            {"exercice": exercice.pk, "famille": espace.famille_id, "methode": "tarif_reference"},
            format="json",
        ).status_code
        == 403
    )
    assert local.get(f"{url}/synthese").status_code == 200, "la lecture reste permise"
    assert local.post(f"{url}/cloturer").status_code == 403
    with pytest.raises(AccesRefuse):
        services.cloturer(exercice, acteur=agent("financier", espace.batiment.site))
    assert client_agent(agent("financier")).post(f"{url}/cloturer").status_code == 200


def test_rg14_actions_de_valorisation_refusees_aux_roles_non_habilites(espace, exercice, horloge, client_agent):
    club = usager_avec_contact(nom="Club de hand")
    _reduction(club)
    _seance(espace, club)
    valorisation = services.valoriser(club, exercice, acteur="système")
    horloge.move_to("2027-01-15 10:00")
    services.cloturer(exercice, acteur="système")
    url = f"/api/gestion/valorisation/exercices/{exercice.pk}"
    accueil = client_agent(agent("accueil"))
    assert accueil.get("/api/gestion/valorisation/exercices").status_code == 403
    assert accueil.get(f"{url}/synthese").status_code in {403, 404}
    assert accueil.get(f"/api/gestion/valorisation/valorisations/{valorisation.pk}").status_code in {403, 404}
    direction = client_agent(agent("direction"))
    assert direction.get(f"{url}/simulation", {"usager": club.pk}).status_code == 403
    assert (
        direction.post(
            "/api/gestion/valorisation/methodes",
            {"exercice": exercice.pk, "famille": espace.famille_id, "methode": "tarif_reference"},
            format="json",
        ).status_code
        == 403
    )
    gestion = client_agent(agent("gestionnaire"))
    motif = {"motif": "Séance du 10 novembre oubliée dans le calcul initial."}
    assert (
        gestion.post(f"/api/gestion/valorisation/valorisations/{valorisation.pk}/recalculer", motif, format="json").status_code
        == 403
    )
    assert direction.post(f"/api/gestion/valorisation/valorisations/{valorisation.pk}/attestation").status_code == 403


def test_rg14_le_detail_d_une_valorisation_se_limite_aux_sites_de_l_agent(espace, exercice, client_agent):
    autre = EspaceFabrique(nom="Gymnase du centre")
    _meme_grille(espace, autre)
    club = usager_avec_contact(nom="Club multisite")
    _reduction(club)
    _seance(espace, club)
    _seance(autre, club, jour=MARDI + timedelta(days=1))
    valorisation = services.valoriser(club, exercice, acteur="système")
    detail = client_agent(agent("gestionnaire", espace.batiment.site)).get(
        f"/api/gestion/valorisation/valorisations/{valorisation.pk}"
    )
    assert detail.status_code == 200 and [ligne["libelle"].split(",")[0] for ligne in detail.json()["lignes"]] == [espace.nom]
    complet = client_agent(agent("financier")).get(f"/api/gestion/valorisation/valorisations/{valorisation.pk}").json()
    assert len(complet["lignes"]) == 2


# --- Portail (VAL-04) -------------------------------------------------------------------------------------------


@override_settings(CANAL="portail")
@pytest.mark.urls("config.urls_portail")
def test_val04_portail_sans_session_refuse_et_version_remplacee_invisible(espace, exercice, horloge):
    from django.test import Client

    from apps.portail.tests.outils import client_contact, compte_actif

    club = usager_avec_contact(nom="Club de gym")
    _reduction(club)
    _seance(espace, club)
    services.valoriser(club, exercice, acteur="système")
    horloge.move_to("2027-01-15 10:00")
    services.cloturer(exercice, acteur="système")
    valorisation = Valorisation.objects.get(usager=club, actuelle=True)
    with override_settings(SIGNATURE_MODE="manuel"):
        valorisation = services.editer_attestation(valorisation, acteur="système")
    from apps.documents import services as documents

    documents.deposer_scan_signe(valorisation.document, "attestation-signee.pdf", b"%PDF-1.7 signee", acteur="système")
    client = client_contact(compte_actif(club))
    assert [a["id"] for a in client.get("/api/portail/attestations").json()] == [valorisation.pk]
    assert Client().get("/api/portail/attestations").status_code in {401, 403}
    services.recalculer_apres_cloture(
        valorisation, acteur="système", motif="Séance du 10 novembre comptée deux fois par erreur de saisie."
    )
    assert client.get("/api/portail/attestations").json() == [], "l'attestation remplacée n'est plus proposée"
    assert client.get(f"/api/portail/attestations/{valorisation.pk}/fichier").status_code == 404


def test_val06_seuils_legaux_reenregistrables_par_l_ordonnateur_seulement(client_agent):
    """m1 : 153 000 € dépassait la borne générique ; les seuils sont des paramètres financiers (séparation des tâches)."""
    valeurs = {"valeurs": {"valorisation.seuil_compte_rendu_centimes": 15_300_000}}
    assert client_agent(agent("administrateur")).patch("/api/gestion/parametres", valeurs, format="json").status_code == 403
    assert client_agent(agent("financier")).patch("/api/gestion/parametres", valeurs, format="json").status_code == 200
