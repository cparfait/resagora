"""Lot 6 — valorisation des avantages en nature (VAL-01 à VAL-08), selon les tests indispensables du skill :
gratuité totale, réduction partielle, espace partagé, annulation hors délai, changement de méthode, seuil de
23 000 € avec subvention importée ; clôture et recalcul tracé ; attestation sur le portail ; annexe."""

from __future__ import annotations

from datetime import date, timedelta

import pytest
from django.db import DatabaseError, transaction
from django.test import override_settings
from freezegun import freeze_time

from apps.finances.models import Reduction
from apps.finances.tests.outils import PDF, grille_votee
from apps.noyau.exceptions import ErreurMetier
from apps.reservations import services as reservations
from apps.reservations.tests.outils import reserver
from apps.valorisation import services
from apps.valorisation.models import Exercice, MethodeValorisation, SubventionNumeraire, Valorisation
from tests.fabriques import EspaceFabrique, agent, usager_avec_contact

pytestmark = pytest.mark.django_db
MARDI = date(2026, 11, 10)


@pytest.fixture(autouse=True)
def environnement(monkeypatch, modeles_documents):
    from apps.documents import services as documents

    monkeypatch.setattr(documents, "convertir_en_pdfa", lambda nom, docx, transport=None: PDF)
    with freeze_time("2026-12-31 18:00") as horloge:
        yield horloge


@pytest.fixture
def espace():
    espace = EspaceFabrique(nom="Gymnase des Écoles", surface_m2=900)
    grille_votee(espace)  # association locale : 20 € de l'heure
    return espace


@pytest.fixture
def exercice():
    return Exercice.objects.create(annee=2026)


def _gratuite(usager, taux=10000):
    return Reduction.objects.create(usager=usager, taux=taux, fondement="Convention d'objectifs 2026", debut=date(2026, 1, 1))


def _seance(espace, usager, jour=MARDI, debut="18:00", fin="20:00"):
    return reserver(espace, jour, debut, fin, usager=usager, statut="validee").occurrences.get()


def test_val02_gratuite_totale_valorisee_au_tarif_de_reference(espace, exercice):
    club = usager_avec_contact(nom="Club de basket")
    _gratuite(club)
    _seance(espace, club)
    resultat = services.calculer(club, exercice)
    assert resultat.somme("espace") == 4000  # 2 h × 20 €


def test_val02_reduction_partielle_seul_l_ecart_est_valorise(espace, exercice):
    club = usager_avec_contact(nom="Club de judo")
    _gratuite(club, taux=5000)
    _seance(espace, club)
    assert services.calculer(club, exercice).somme("espace") == 2000


def test_val02_espace_partage_entre_deux_associations(exercice):
    piste = EspaceFabrique(nom="Piste", partageable=True, capacite_simultanee=2)
    grille_votee(piste)
    athle, triathlon = usager_avec_contact(nom="Athlétisme"), usager_avec_contact(nom="Triathlon")
    for club in (athle, triathlon):
        _gratuite(club)
        _seance(piste, club)
    assert services.calculer(athle, exercice).somme("espace") == 2000
    assert services.calculer(triathlon, exercice).lignes[0].part == 5000


def test_val03_annulation_hors_delai_valorisee_dans_les_delais_non(espace, exercice, environnement):
    club = usager_avec_contact(nom="Club de volley")
    _gratuite(club)
    environnement.move_to("2026-11-09 20:00")  # moins de 72 h avant
    tardive = _seance(espace, club)
    reservations.annuler_occurrence(tardive, acteur=agent("gestionnaire"), motif="Équipe absente", par_usager=True)
    environnement.move_to("2026-11-02 10:00")
    a_temps = _seance(espace, club, jour=MARDI + timedelta(days=7))
    reservations.annuler_occurrence(a_temps, acteur=agent("gestionnaire"), motif="Tournoi déplacé", par_usager=True)
    environnement.move_to("2026-12-31 18:00")
    resultat = services.calculer(club, exercice)
    assert [ligne.occurrence.pk for ligne in resultat.lignes if ligne.nature == "espace"] == [tardive.pk]
    assert "hors délai" in resultat.lignes[0].observation


def test_rg12_valorisation_apres_annulations_seules_les_heures_annulees_dans_les_delais_sortent(espace, exercice, environnement):
    """R6-51 : trois séances de 2 h, une réalisée, une annulée à temps, une annulée hors délai → 4 h valorisées."""
    club = usager_avec_contact(nom="Club de tennis de table")
    _gratuite(club)
    environnement.move_to("2026-11-01 10:00")
    _seance(espace, club)
    a_temps = _seance(espace, club, jour=MARDI + timedelta(days=7))
    tardive = _seance(espace, club, jour=MARDI + timedelta(days=14))
    reservations.annuler_occurrence(a_temps, acteur=agent("gestionnaire"), motif="Stage annulé", par_usager=True)
    environnement.move_to("2026-11-23 10:00")  # 32 h avant la troisième séance
    reservations.annuler_occurrence(tardive, acteur=agent("gestionnaire"), motif="Salle inutile", par_usager=True)
    environnement.move_to("2026-12-31 18:00")
    resultat = services.calculer(club, exercice)
    assert resultat.somme("espace") == 8000
    assert sum(ligne.quantite for ligne in resultat.lignes if ligne.nature == "espace") == 240


def test_val03_absence_signalee_non_valorisee_absence_non_signalee_valorisee(espace, exercice):
    club = usager_avec_contact(nom="Club de hand")
    _gratuite(club)
    signalee, muette = _seance(espace, club), _seance(espace, club, jour=MARDI + timedelta(days=1))
    type(signalee).objects.filter(pk=signalee.pk).update(presence="absent_signale")
    type(muette).objects.filter(pk=muette.pk).update(presence="absent_non_signale")
    lignes = [ligne for ligne in services.calculer(club, exercice).lignes if ligne.nature == "espace"]
    assert [ligne.occurrence.pk for ligne in lignes] == [muette.pk]


def test_val01_changement_de_methode_entre_deux_exercices(espace, exercice, client_agent):
    club = usager_avec_contact(nom="Club de badminton")
    _gratuite(club)
    _seance(espace, club)
    exercice_2027 = Exercice.objects.create(annee=2027)
    MethodeValorisation.objects.create(
        exercice=exercice_2027,
        famille=espace.famille,
        methode="cout_revient",
        cout_horaire_centimes=5500,
        deliberation_reference="DCM-2026-12-01",
    )
    _seance(espace, club, jour=date(2027, 1, 12))
    assert services.calculer(club, exercice).somme("espace") == 4000
    ligne_2027 = services.calculer(club, exercice_2027).lignes[0]
    assert ligne_2027.methode == "cout_revient" and ligne_2027.montant_reference == 11000
    gestion = client_agent(agent("gestionnaire"))
    sans_fondement = gestion.post(
        "/api/gestion/valorisation/methodes",
        {"exercice": exercice.pk, "famille": espace.famille_id, "methode": "cout_revient", "cout_horaire_centimes": 5000},
        format="json",
    )
    assert sans_fondement.status_code == 400


def test_rg05_tarif_de_reference_manquant_bloque_le_calcul(exercice):
    sans_tarif = EspaceFabrique(nom="Salle sans tarif")
    grille_votee(EspaceFabrique(nom="Autre salle"))
    club = usager_avec_contact(nom="Club sans tarif")
    _gratuite(club)
    _seance(sans_tarif, club)
    with pytest.raises(ErreurMetier) as refus:
        services.valoriser(club, exercice, acteur="système")
    assert refus.value.code == "tarif_reference_manquant"


def test_val06_seuil_de_convention_avec_subvention_importee(espace, exercice, client_agent):
    club = usager_avec_contact(nom="Grand club omnisports")
    club.siret = "12345678900011"
    club.save()
    _gratuite(club)
    _seance(espace, club)
    services.valoriser(club, exercice, acteur="système")
    fichier = b"identifiant;montant;objet;deliberation\n12345678900011;22 980,00;Fonctionnement;DCM-2026-03-10\ninconnu;10,00;;\n"
    from django.core.files.uploadedfile import SimpleUploadedFile

    gestion = client_agent(agent("gestionnaire"))
    # M6 : une ligne rejetée suspend l'import tant que l'agent ne l'a pas vue ; rien n'est remplacé.
    rapport = gestion.post(
        f"/api/gestion/valorisation/exercices/{exercice.pk}/subventions",
        {"fichier": SimpleUploadedFile("subventions.csv", fichier)},
        format="multipart",
    ).json()
    assert rapport["confirmation_requise"] and rapport["importees"] == 0 and len(rapport["rejets"]) == 1
    assert not SubventionNumeraire.objects.exists()
    rapport = gestion.post(
        f"/api/gestion/valorisation/exercices/{exercice.pk}/subventions",
        {"fichier": SimpleUploadedFile("subventions.csv", fichier), "confirmer": "oui"},
        format="multipart",
    ).json()
    assert rapport["importees"] == 1 and len(rapport["rejets"]) == 1
    synthese = gestion.get(f"/api/gestion/valorisation/exercices/{exercice.pk}/synthese").json()
    ligne = next(item for item in synthese["lignes"] if item["usager"] == club.pk)
    assert ligne["numeraire"] == 2_298_000 and ligne["nature"] == 4000 and ligne["alertes"] == ["convention"]


def test_val07_simulation_au_30_juin(espace, client_agent):
    exercice = Exercice.objects.create(annee=2027)
    club = usager_avec_contact(nom="Club de tennis de table")
    _gratuite(club)
    _seance(espace, club, jour=date(2027, 3, 2))
    _seance(espace, club, jour=date(2027, 9, 7))
    reponse = client_agent(agent("gestionnaire")).get(
        f"/api/gestion/valorisation/exercices/{exercice.pk}/simulation", {"usager": club.pk, "jusqu_au": "2027-06-30"}
    )
    assert reponse.status_code == 200 and reponse.json()["total"] == 4000
    assert not Valorisation.objects.exists(), "une simulation n'enregistre rien"


def test_val08_cloture_puis_recalcul_sans_procedure_refuse(espace, exercice, client_agent, environnement):
    club = usager_avec_contact(nom="Club de natation")
    _gratuite(club)
    _seance(espace, club)
    services.valoriser(club, exercice, acteur="système")
    environnement.move_to("2027-01-15 10:00")
    directeur = client_agent(agent("direction"))
    assert directeur.post(f"/api/gestion/valorisation/exercices/{exercice.pk}/cloturer").status_code == 403
    financier = client_agent(agent("financier"))
    assert financier.post(f"/api/gestion/valorisation/exercices/{exercice.pk}/cloturer").status_code == 200
    refus = client_agent(agent("gestionnaire")).post(
        f"/api/gestion/valorisation/exercices/{exercice.pk}/calculer", {"usager": club.pk}, format="json"
    )
    assert refus.status_code == 409 and refus.json()["code"] == "exercice_cloture"
    valorisation = Valorisation.objects.get()
    with pytest.raises(DatabaseError), transaction.atomic():
        Valorisation.objects.filter(pk=valorisation.pk).update(total=1)
    sans_motif = financier.post(
        f"/api/gestion/valorisation/valorisations/{valorisation.pk}/recalculer", {"motif": "Erreur"}, format="json"
    )
    assert sans_motif.status_code == 400
    nouvelle = financier.post(
        f"/api/gestion/valorisation/valorisations/{valorisation.pk}/recalculer",
        {"motif": "Séance du 10 novembre omise : régularisation demandée par le service financier."},
        format="json",
    )
    assert nouvelle.status_code == 201 and nouvelle.json()["version"] == 2 and nouvelle.json()["figee"] is True
    valorisation.refresh_from_db()
    assert valorisation.actuelle is False and valorisation.total == 4000


@pytest.fixture
def docuseal(monkeypatch, settings):
    import httpx

    from apps.documents.docuseal import ClientDocuSeal
    from tests.faux_docuseal import BASE, FauxDocuSeal

    faux = FauxDocuSeal()
    origine = ClientDocuSeal.__init__

    def initialiser(self, transport=None):
        origine(self, transport=httpx.MockTransport(faux))

    monkeypatch.setattr(ClientDocuSeal, "__init__", initialiser)
    from apps.noyau import fichiers

    monkeypatch.setattr(fichiers, "analyser_clamav", lambda contenu: None)
    settings.DOCUSEAL_URL = BASE
    settings.DOCUSEAL_URL_PUBLIQUE = "https://signature.chatillon.test"
    settings.DOCUSEAL_JETON = "jeton-api-test"
    return faux


def _cloturee(espace, club, exercice, environnement):
    _gratuite(club)
    _seance(espace, club)
    services.valoriser(club, exercice, acteur="système")
    environnement.move_to("2027-01-15 10:00")
    services.cloturer(exercice, acteur="système")
    return Valorisation.objects.get(usager=club, exercice=exercice, actuelle=True)


@override_settings(CANAL="portail")
@pytest.mark.urls("config.urls_portail")
def test_val04_attestation_signee_par_l_elu_puis_deposee_sur_le_portail(
    espace, exercice, environnement, docuseal, django_capture_on_commit_callbacks
):
    from apps.documents import services as documents
    from apps.portail.tests.outils import client_contact, compte_actif

    club = usager_avec_contact(nom="Club de gym")
    valorisation = _cloturee(espace, club, exercice, environnement)
    with django_capture_on_commit_callbacks(execute=True):
        valorisation = services.editer_attestation(valorisation, acteur=agent("gestionnaire"))
    circuit = valorisation.document.circuits.get()
    assert valorisation.deposee_le is None and [s.role for s in circuit.signataires.all()] == ["elu"]
    compte = compte_actif(club)
    client = client_contact(compte)
    assert client.get("/api/portail/attestations").json() == []  # pas avant la signature de l'élu
    circuit.refresh_from_db()
    docuseal.signer(int(circuit.soumission), 0)
    with django_capture_on_commit_callbacks(execute=True):
        documents.traiter_webhook({"event_type": "submission.completed", "data": {"id": int(circuit.soumission)}})
    attestations = client.get("/api/portail/attestations").json()
    assert [a["exercice"] for a in attestations] == [2026] and attestations[0]["montant_texte"].startswith("40,00")
    assert client.get(f"/api/portail/attestations/{attestations[0]['id']}/fichier").status_code == 200
    intrus = client_contact(compte_actif())
    assert intrus.get(f"/api/portail/attestations/{attestations[0]['id']}/fichier").status_code == 404


def test_val04_attestation_fusionnee_en_mode_strict(espace, exercice):
    """Le modèle livré se fusionne avec une vraie valorisation (variable inconnue = erreur) et porte le montant."""
    from apps.documents import services as documents
    from apps.documents.contexte import construire
    from apps.documents.models import ModeleDocument
    from apps.documents.tests.test_documents import _texte_docx
    from apps.noyau import fichiers

    club = usager_avec_contact(nom="Club de tir à l'arc")
    _gratuite(club)
    _seance(espace, club)
    valorisation = services.valoriser(club, exercice, acteur="système")
    modele = ModeleDocument.objects.select_related("version_active__fichier").get(code="attestation-valorisation")
    texte = _texte_docx(
        documents.rendre_docx(fichiers.lire(modele.version_active.fichier), construire(modele.nature, valorisation))
    )
    assert "{{" not in texte and "Club de tir à l'arc" in texte and "40,00" in texte and "2026" in texte


def test_val04_pas_d_attestation_pour_une_ecole(espace, exercice):
    ecole = usager_avec_contact(nom="École Jules-Ferry", type="ecole")
    _gratuite(ecole)
    _seance(espace, ecole)
    valorisation = services.valoriser(ecole, exercice, acteur="système")
    with pytest.raises(ErreurMetier) as refus:
        services.editer_attestation(valorisation, acteur="système")
    assert refus.value.code == "attestation_non_prevue"


def test_val04_pas_d_attestation_sur_un_exercice_ouvert(espace, exercice):
    """M7 : une attestation éditée en octobre attesterait des séances de décembre qui n'ont pas encore eu lieu."""
    club = usager_avec_contact(nom="Club de rugby")
    _gratuite(club)
    _seance(espace, club)
    valorisation = services.valoriser(club, exercice, acteur="système")
    with pytest.raises(ErreurMetier) as refus:
        services.editer_attestation(valorisation, acteur="système")
    assert refus.value.code == "exercice_ouvert"


def test_val05_annexe_du_compte_administratif(espace, exercice, client_agent):
    club = usager_avec_contact(nom="Club de foot")
    _gratuite(club)
    _seance(espace, club)
    services.valoriser(club, exercice, acteur="système")
    SubventionNumeraire.objects.create(exercice=exercice, usager=club, montant_centimes=150_000)
    reponse = client_agent(agent("financier")).get(f"/api/gestion/valorisation/exercices/{exercice.pk}/annexe")
    texte = reponse.content.decode("utf-8-sig")
    assert (
        reponse.status_code == 200 and "Club de foot" in texte and "mise à disposition de locaux" in texte and "1540,00" in texte
    )
    assert client_agent(agent("accueil")).get(f"/api/gestion/valorisation/exercices/{exercice.pk}/annexe").status_code == 403


def test_val02_materiel_prete_et_personnel_dedie(exercice):
    from apps.materiel import services as materiel
    from apps.materiel.models import Materiel

    gymnase = EspaceFabrique(nom="Gymnase gardienné", gardiennage_requis=True, temps_ouverture_min=15, temps_fermeture_min=15)
    grille_votee(gymnase)
    club = usager_avec_contact(nom="Club de basket gardienné")
    _gratuite(club)
    seance = _seance(gymnase, club, jour=date(2026, 12, 15))
    tables = Materiel.objects.create(code="table", libelle="Table", valeur_journaliere_centimes=300)
    stock = materiel.entrer(tables, gymnase.batiment.site, 20, acteur="système")
    with freeze_time("2026-12-01 10:00"):
        materiel.reserver(seance.reservation.dossier, stock, 10, acteur="système", occurrence=seance)
    resultat = services.calculer(club, exercice)
    assert resultat.somme("materiel") == 3000  # 10 tables × 1 journée × 3 €
    assert resultat.somme("personnel") == round(3200 * 150 / 60)  # 2 h 30 de gardiennage à 32 €/h


def test_rg14_valorisation_reservee_aux_roles_habilites(exercice, client_agent):
    assert client_agent(agent("financier")).get("/api/gestion/valorisation/exercices").status_code == 200
    assert client_agent(agent("accueil")).get("/api/gestion/valorisation/exercices").status_code == 403
    assert (
        client_agent(agent("direction"))
        .post(f"/api/gestion/valorisation/exercices/{exercice.pk}/calculer", {}, format="json")
        .status_code
        == 403
    )
