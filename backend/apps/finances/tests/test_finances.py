"""Lot 3 — tarification (TAR-01 à TAR-03, RG-05), devis et factures (TAR-04, TAR-05, RG-04, RG-13), acompte
(TAR-09), frais d'annulation (TAR-08, RG-08), titres Ciril (TAR-06), encaissements (TAR-13), retards (TAR-10)."""

from __future__ import annotations

import csv
import io
from datetime import date, timedelta

import pytest
from django.db import DatabaseError, transaction
from django.utils import timezone
from freezegun import freeze_time
from openpyxl import Workbook, load_workbook

from apps.documents import services as documents
from apps.finances import facturation, tarification, titres
from apps.finances.ciril import encaissements
from apps.finances.models import AFacturer, Encaissement, LigneComptable, PieceComptable, Reduction, Tarif
from apps.noyau import fichiers
from apps.noyau.exceptions import AccesRefuse, ErreurMetier, ErreurValidation
from apps.noyau.models import Parametre
from apps.noyau.parametres import invalider
from apps.reservations import conditions
from apps.reservations import services as reservations
from apps.reservations.recurrence import PARIS
from tests.fabriques import EspaceFabrique, agent, usager_avec_contact

from .outils import PDF, grille_votee, location

pytestmark = pytest.mark.django_db


@pytest.fixture(autouse=True)
def environnement(monkeypatch, modeles_documents):
    monkeypatch.setattr(documents, "convertir_en_pdfa", lambda nom, docx, transport=None: PDF)
    monkeypatch.setattr(fichiers, "analyser_clamav", lambda contenu: None)
    with freeze_time("2026-11-02 10:00"):
        yield


@pytest.fixture
def espace():
    return EspaceFabrique(nom="Salle polyvalente Jean-Jaurès")


@pytest.fixture
def grille(espace):
    return grille_votee(espace)


# --- TAR-01 à TAR-03, RG-05 -----------------------------------------------------------------------------------------


def test_tar02_tarif_par_categorie_et_majorations(espace, grille):
    association = usager_avec_contact(type="association", local=True, commune="Châtillon")
    lignes = tarification.calculer_seance(
        espace=espace,
        usager=association,
        debut=timezone.datetime(2026, 12, 9, 18, 0, tzinfo=PARIS),
        fin=timezone.datetime(2026, 12, 9, 20, 0, tzinfo=PARIS),
    )
    assert [(ligne.nature, ligne.montant_du) for ligne in lignes] == [("occupation", 4000)]
    exterieur = usager_avec_contact(type="particulier", commune="Paris")
    samedi = tarification.calculer_seance(
        espace=espace,
        usager=exterieur,
        debut=timezone.datetime(2026, 12, 12, 14, 0, tzinfo=PARIS),
        fin=timezone.datetime(2026, 12, 12, 15, 30, tzinfo=PARIS),
    )
    # 1 h 30 à 40 € = 60 € ; week-end +25 % = 15 € ; non-résident +50 % = 30 €.
    assert sum(ligne.montant_du for ligne in samedi) == 6000 + 1500 + 3000
    assert all(isinstance(ligne.montant_du, int) for ligne in samedi)


def test_rg05_gratuite_reduction_de_100_pour_cent_sur_le_tarif_de_reference(espace, grille):
    club = usager_avec_contact(type="association", local=True, commune="Châtillon")
    with pytest.raises(ErreurValidation):
        tarification.verifier_reduction(10000, "")
    Reduction.objects.create(
        usager=club, taux=10000, fondement="Délibération DCM-2025-06-30-12 (gratuité clubs)", debut=date(2026, 1, 1)
    )
    reservation = location(usager=club, espace=espace)
    devis = facturation.etablir_devis(reservation.dossier, acteur=agent("gestionnaire"))
    ligne = devis.lignes.get()
    assert ligne.montant_reference == 8000 and ligne.taux_reduction == 10000 and ligne.montant_du == 0
    assert devis.total_reference == 8000 and devis.total_du == 0 and "DCM-2025-06-30-12" in ligne.fondement


def test_rg05_sans_tarif_de_reference_ni_facture_ni_gratuite(espace, grille):
    autre = EspaceFabrique(nom="Dojo sans tarif")
    reservation = location(espace=autre)
    with pytest.raises(ErreurMetier) as refus:
        facturation.etablir_devis(reservation.dossier, acteur=agent("gestionnaire"))
    assert refus.value.code == "sans_tarif_reference"


def test_tar01_grille_votee_figee_et_deliberation_obligatoire(client_agent, espace):
    financier = client_agent(agent("financier"))
    grille = financier.post("/api/gestion/finances/grilles", {"nom": "Tarifs 2027", "debut": "2027-01-01"}, format="json").json()
    sans_tarif = financier.post(f"/api/gestion/finances/grilles/{grille['id']}/voter")
    assert sans_tarif.status_code == 400
    assert (
        financier.post(
            "/api/gestion/finances/tarifs",
            {"grille": grille["id"], "espace": espace.pk, "categorie": "particulier", "unite": "heure", "prix_centimes": 4500},
            format="json",
        ).status_code
        == 201
    )
    assert financier.post(f"/api/gestion/finances/grilles/{grille['id']}/voter").json()["code"] == "deliberation_requise"
    financier.patch(
        f"/api/gestion/finances/grilles/{grille['id']}",
        {"deliberation_reference": "DCM-2026-12-14-03", "deliberation_date": "2026-12-14"},
        format="json",
    )
    assert financier.post(f"/api/gestion/finances/grilles/{grille['id']}/voter").json()["statut"] == "votee"
    tarif = Tarif.objects.get(grille_id=grille["id"])
    assert financier.patch(f"/api/gestion/finances/tarifs/{tarif.pk}", {"prix_centimes": 1}, format="json").status_code == 409
    assert (
        client_agent(agent("gestionnaire"))
        .post("/api/gestion/finances/grilles", {"nom": "x", "debut": "2027-01-01"}, format="json")
        .status_code
        == 403
    )


def test_tar03_reduction_sans_fondement_refusee_par_l_api(client_agent):
    club = usager_avec_contact()
    financier = client_agent(agent("financier"))
    refus = financier.post(
        "/api/gestion/finances/reductions",
        {"usager": club.pk, "taux": 5000, "fondement": "", "debut": "2026-01-01"},
        format="json",
    )
    assert refus.status_code == 400
    accord = financier.post(
        "/api/gestion/finances/reductions",
        {"usager": club.pk, "taux": 5000, "fondement": "Convention 2026-14", "debut": "2026-01-01"},
        format="json",
    )
    assert accord.status_code == 201
    assert client_agent(agent("accueil")).get("/api/gestion/finances/reductions").status_code == 403


# --- TAR-04, TAR-05, RG-04, RG-13 -------------------------------------------------------------------------------


def test_rg04_devis_accepte_fige_les_montants_de_la_facture(espace, grille):
    reservation = location(espace=espace)
    gestionnaire = agent("gestionnaire")
    devis = facturation.etablir_devis(reservation.dossier, acteur=gestionnaire, prestations=[{"code": "menage"}])
    assert devis.numero.startswith("DV2026-") and devis.validite == date(2026, 12, 2)
    facturation.accepter_devis(devis, acteur=gestionnaire)
    Tarif.objects.filter(grille=grille).update(prix_centimes=99900)
    with freeze_time("2026-12-13 09:00"):
        facture = facturation.facturer(reservation.dossier, acteur=gestionnaire)
    assert facture.total_du == devis.total_du == 16000 + 12000
    assert facture.origine_id == devis.pk and facture.echeance == date(2027, 1, 12)


def test_tar05_numerotation_chronologique_sans_trou(espace, grille):
    gestionnaire = agent("gestionnaire")
    numeros = []
    for jour in (date(2026, 12, 9), date(2026, 12, 16), date(2026, 12, 23)):
        reservation = location(espace=espace, jour=jour)
        numeros.append(facturation.facturer(reservation.dossier, acteur=gestionnaire).numero)
    assert numeros == ["F2026-00001", "F2026-00002", "F2026-00003"]


def test_rg13_facture_emise_immuable_correction_par_avoir(espace, grille):
    gestionnaire, financier = agent("gestionnaire"), agent("financier")
    facture = facturation.facturer(location(espace=espace).dossier, acteur=gestionnaire)
    with pytest.raises(DatabaseError), transaction.atomic():
        PieceComptable.objects.filter(pk=facture.pk).update(total_du=1)
    with pytest.raises(DatabaseError), transaction.atomic():
        LigneComptable.objects.filter(piece=facture).update(montant_du=1)
    with pytest.raises(DatabaseError), transaction.atomic():
        PieceComptable.objects.filter(pk=facture.pk).delete()
    with pytest.raises(AccesRefuse):
        facturation.emettre_avoir(facture, acteur=gestionnaire, motif="Erreur de durée")
    avoir = facturation.emettre_avoir(facture, acteur=financier, motif="Séance non réalisée (fermeture)")
    assert avoir.numero.startswith("AV2026-") and avoir.total_du == -facture.total_du and avoir.origine_id == facture.pk
    facture.refresh_from_db()
    assert facture.statut == "annulee"
    with pytest.raises(ErreurMetier):
        facturation.emettre_avoir(facture, acteur=financier, motif="Deuxième avoir")


# --- TAR-09, RG-06 ----------------------------------------------------------------------------------------------


def test_tar09_acompte_sur_devis_accepte_condition_de_confirmation(espace, grille):
    reservation = location(espace=espace)
    gestionnaire, regisseur = agent("gestionnaire"), agent("regisseur")
    assert "accepter le devis" in " ".join(conditions.conditions_manquantes(reservation))
    devis = facturation.etablir_devis(reservation.dossier, acteur=gestionnaire)
    with pytest.raises(ErreurMetier):
        facturation.facturer_acompte(reservation.dossier, acteur=gestionnaire)
    facturation.accepter_devis(devis, acteur=gestionnaire)
    acompte = facturation.facturer_acompte(reservation.dossier, acteur=gestionnaire)
    assert acompte.numero.startswith("FA2026-") and acompte.total_du == 4800  # 30 % de 160 €
    assert "régler l'acompte" in " ".join(conditions.conditions_manquantes(reservation))
    with pytest.raises(ErreurValidation):
        facturation.pointer(acompte, acteur=regisseur, montant=4800, jour=date(2026, 11, 5), reference="")
    with pytest.raises(AccesRefuse):
        facturation.pointer(acompte, acteur=gestionnaire, montant=4800, jour=date(2026, 11, 5), reference="VIR 4521")
    facturation.pointer(acompte, acteur=regisseur, montant=4800, jour=date(2026, 11, 5), reference="VIR 4521")
    assert not [c for c in conditions.conditions_manquantes(reservation) if "acompte" in c]
    with freeze_time("2026-12-13 09:00"):
        facture = facturation.facturer(reservation.dossier, acteur=gestionnaire)
    assert facture.acompte_deduit == 4800 and facture.reste_du == 16000 - 4800


# --- TAR-08, RG-08 ----------------------------------------------------------------------------------------------


def test_rg08_frais_d_annulation_tardive_selon_le_bareme(espace, grille):
    reservation = location(espace=espace, jour=date(2026, 11, 3), debut="14:00", fin="18:00")
    seance = reservation.occurrences.get()
    contact = reservation.dossier.usager.rattachements.first().contact
    reservations.annuler_occurrence(seance, acteur=contact, motif="Imprévu", par_usager=True)
    frais = AFacturer.objects.get(occurrence=seance)
    # Annulée 28 h avant : palier 24 h → 50 % de 160 € (4 h à 40 €).
    assert frais.montant_du == 8000 and "50 %" in frais.libelle
    facture = facturation.facturer(reservation.dossier, acteur=agent("gestionnaire"))
    assert facture.lignes.filter(nature="frais").count() == 1
    frais.refresh_from_db()
    assert frais.facture_id == facture.pk


def test_rg08_annulation_dans_les_delais_sans_frais(espace, grille):
    reservation = location(espace=espace, jour=date(2026, 12, 20))
    seance = reservation.occurrences.get()
    contact = reservation.dossier.usager.rattachements.first().contact
    reservations.annuler_occurrence(seance, acteur=contact, motif="Changement de programme", par_usager=True)
    assert not AFacturer.objects.filter(occurrence=seance).exists()


# --- TAR-06 Ciril -----------------------------------------------------------------------------------------------


def _factures(espace, nombre=2):
    gestionnaire = agent("gestionnaire")
    return [
        facturation.facturer(location(espace=espace, jour=date(2026, 12, 9) + timedelta(days=7 * i)).dossier, acteur=gestionnaire)
        for i in range(nombre)
    ]


def test_tar06_export_ciril_csv_parametrable_et_rejouable(espace, grille, client_agent):
    factures = _factures(espace)
    financier = client_agent(agent("financier"))
    assert [p["numero"] for p in financier.get("/api/gestion/finances/lots-titres/a-titrer").json()] == [
        f.numero for f in factures
    ]
    lot = financier.post("/api/gestion/finances/lots-titres", {}, format="json").json()
    assert lot["pieces"] == [f.numero for f in factures] and lot["total_centimes"] == sum(f.total_du for f in factures)
    premier = b"".join(financier.get(f"/api/gestion/finances/lots-titres/{lot['id']}/fichier").streaming_content)
    rejoue = b"".join(financier.get(f"/api/gestion/finances/lots-titres/{lot['id']}/fichier").streaming_content)
    assert premier == rejoue
    lignes = list(csv.reader(io.StringIO(premier.decode("cp1252")), delimiter=";"))
    assert lignes[1][lignes[0].index("Référence facture")] == factures[0].numero
    assert lignes[1][lignes[0].index("Montant")] == "160,00"
    assert financier.get("/api/gestion/finances/lots-titres/a-titrer").json() == []
    with pytest.raises(ErreurMetier):
        titres.exporter(factures, acteur=agent("financier"))
    assert client_agent(agent("gestionnaire")).post("/api/gestion/finances/lots-titres", {}, format="json").status_code == 403


@pytest.mark.parametrize("format_export", ["xlsx", "xml"])
def test_tar06_export_ciril_xlsx_et_xml(espace, grille, format_export):
    factures = _factures(espace, 1)
    lot = titres.exporter(factures, acteur=agent("financier"), format_export=format_export)
    contenu = fichiers.lire(lot.fichier)
    if format_export == "xlsx":
        feuille = load_workbook(io.BytesIO(contenu)).active
        entetes = [c.value for c in feuille[1]]
        assert feuille.cell(2, entetes.index("Référence facture") + 1).value == factures[0].numero
    else:
        assert f"<numero_facture>{factures[0].numero}</numero_facture>".encode() in contenu


def test_tar06_numero_de_titre_reporte(espace, grille):
    facture = _factures(espace, 1)[0]
    facture = titres.reporter_titre(facture, acteur=agent("financier"), titre="T-2026-000412")
    assert facture.statut == "titre_emis" and facture.titre_numero == "T-2026-000412"


# --- TAR-13 encaissements, TAR-10 retards ---------------------------------------------------------------------


def _etat_ciril(lignes: list[list[str]]) -> bytes:
    sortie = io.StringIO()
    ecrivain = csv.writer(sortie, delimiter=";")
    ecrivain.writerow(["N° titre", "Référence", "Montant encaissé", "Date encaissement", "Référence paiement"])
    ecrivain.writerows(lignes)
    return sortie.getvalue().encode("cp1252")


def test_tar13_import_des_encaissements_rapproche_et_rapporte(espace, grille, client_agent):
    premiere, seconde = _factures(espace)
    titres.reporter_titre(premiere, acteur=agent("financier"), titre="T-2026-000501")
    contenu = _etat_ciril(
        [
            ["T-2026-000501", "", "160,00", "15/12/2026", "VIR SEPA 7781"],
            ["", seconde.numero, "50,00", "16/12/2026", "VIR SEPA 7782"],
            ["T-INCONNU", "", "10,00", "16/12/2026", "x"],
        ]
    )
    regisseur = client_agent(agent("regisseur"))
    from django.core.files.uploadedfile import SimpleUploadedFile

    rapport = regisseur.post(
        "/api/gestion/finances/imports-encaissements", {"fichier": SimpleUploadedFile("etat.csv", contenu)}, format="multipart"
    ).json()
    assert rapport["lignes_lues"] == 3 and rapport["rapprochees"] == 2 and rapport["rejets"][0]["titre"] == "T-INCONNU"
    premiere.refresh_from_db()
    seconde.refresh_from_db()
    assert premiere.statut == "solde" and premiere.solde_le == date(2026, 12, 15)
    assert seconde.statut == "solde_partiel" and seconde.reste_du == 16000 - 5000
    rejoue = encaissements.importer("etat.csv", contenu, acteur=agent("regisseur"))
    assert rejoue.rapprochees == 0 and Encaissement.objects.count() == 2
    with pytest.raises(DatabaseError), transaction.atomic():
        Encaissement.objects.filter(piece=premiere).update(montant=1)
    assert (
        client_agent(agent("gestionnaire"))
        .post(
            "/api/gestion/finances/imports-encaissements",
            {"fichier": SimpleUploadedFile("etat.csv", contenu)},
            format="multipart",
        )
        .status_code
        == 403
    )


def test_tar13_import_xlsx_avec_colonnes_parametrees(espace, grille):
    facture = _factures(espace, 1)[0]
    Parametre.objects.update_or_create(
        cle="ciril.import_colonnes",
        defaults={
            "valeur": {"titre": "Titre", "facture": "Facture", "montant": "Montant", "date": "Date", "reference": "Paiement"}
        },
    )
    invalider()
    classeur = Workbook()
    feuille = classeur.active
    feuille.append(["Titre", "Facture", "Montant", "Date", "Paiement"])
    feuille.append(["", facture.numero, "160.00", "2026-12-20", "CB régie"])
    sortie = io.BytesIO()
    classeur.save(sortie)
    lot = encaissements.importer("etat.xlsx", sortie.getvalue(), acteur=agent("regisseur"))
    facture.refresh_from_db()
    assert lot.rapprochees == 1 and facture.statut == "solde"


def test_tar10_factures_en_retard_apres_echeance(espace, grille, client_agent):
    facture = _factures(espace, 1)[0]
    assert not facturation.en_retard(date(2026, 12, 2)).exists()
    with freeze_time("2027-01-05 10:00"):
        retards = client_agent(agent("financier")).get("/api/gestion/finances/pieces/retards").json()
    assert [r["numero"] for r in retards] == [facture.numero]
    with freeze_time("2027-01-05 10:00"):
        assert client_agent(agent("accueil")).get("/api/gestion/finances/pieces/retards").status_code == 403


# --- Droits sur les pièces (RG-14) -----------------------------------------------------------------------------


def test_rg14_pieces_lues_dans_le_perimetre_seulement(espace, grille, client_agent):
    from tests.fabriques import SiteFabrique

    facture = _factures(espace, 1)[0]
    site = espace.batiment.site
    dans = client_agent(agent("financier", site)).get(f"/api/gestion/finances/pieces/{facture.pk}")
    assert dans.status_code == 200 and dans.json()["total_du"] == facture.total_du
    hors = client_agent(agent("financier", SiteFabrique())).get(f"/api/gestion/finances/pieces/{facture.pk}")
    assert hors.status_code == 404
    pdf = client_agent(agent("financier", site)).get(f"/api/gestion/finances/pieces/{facture.pk}/fichier")
    assert pdf.status_code == 200


def test_tar08_annulation_a_j_moins_3_frais_de_50_pour_cent(espace, grille):
    """R3-08 : annulée à J-3 (71 h avant, en deçà du délai de 72 h) → palier de 24 h, 50 %."""
    reservation = location(espace=espace, jour=date(2026, 11, 5), debut="09:00", fin="11:00")
    seance = reservation.occurrences.get()
    contact = reservation.dossier.usager.rattachements.first().contact
    reservations.annuler_occurrence(seance, acteur=contact, motif="Imprévu", par_usager=True)
    frais = AFacturer.objects.get(occurrence=seance)
    assert frais.montant_reference == 4000 and frais.montant_du == 4000  # 50 % de 2 h à 40 €
