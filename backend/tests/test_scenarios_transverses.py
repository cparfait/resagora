"""Scénarios transverses du cahier des charges (§9.3, skill tests-recette), joués de bout en bout sur les services :

1. campagne annuelle : demandes → arbitrage → attribution → conventions en lot → signature ;
2. location d'une salle des fêtes par un particulier non résident : devis, PayFiP, caution, état des lieux, retenue
   partielle ;
3. fermeture imprévue d'un gymnase : séances touchées, notification groupée, besoins de gardiennage mis à jour ;
4. absence d'un gardien : vacation non couverte, remplaçant proposé conforme aux règles de temps de travail ;
5. clôture d'exercice : attestations de valorisation et annexe du compte administratif.
"""

from __future__ import annotations

from datetime import date, datetime, time, timedelta

import httpx
import pytest
from freezegun import freeze_time

from apps.communication.models import Notification
from apps.documents import services as documents
from apps.documents.docuseal import ClientDocuSeal
from apps.documents.models import Document, ModeleDocument
from apps.finances import cautions, facturation
from apps.finances.models import Caution, Encaissement, Reduction
from apps.finances.tests.outils import PDF, grille_votee
from apps.noyau import fichiers
from apps.personnel import services as personnel
from apps.personnel.models import Besoin, Vacation
from apps.personnel.tests.outils import gardien, site_gardienne
from apps.referentiel.models import Fermeture
from apps.reservations import campagne as campagnes
from apps.reservations import conditions
from apps.reservations import services as reservations
from apps.reservations.models import Campagne, Reservation
from apps.reservations.recurrence import PARIS
from apps.reservations.tests.outils import reserver, valider_systeme
from apps.valorisation import services as valorisation
from apps.valorisation.models import Exercice, Valorisation
from tests.fabriques import EspaceFabrique, agent, saison_2026, usager_avec_contact
from tests.faux_docuseal import BASE, FauxDocuSeal

pytestmark = pytest.mark.django_db
JPEG = b"\xff\xd8\xff\xe0" + b"photo-degats" * 20


@pytest.fixture(autouse=True)
def environnement(monkeypatch, settings, modeles_documents):
    monkeypatch.setattr(documents, "convertir_en_pdfa", lambda nom, docx, transport=None: PDF)
    monkeypatch.setattr(fichiers, "analyser_clamav", lambda contenu: None)
    faux = FauxDocuSeal()
    origine = ClientDocuSeal.__init__

    def initialiser(self, transport=None):
        origine(self, transport=httpx.MockTransport(faux))

    monkeypatch.setattr(ClientDocuSeal, "__init__", initialiser)
    settings.DOCUSEAL_URL = BASE
    settings.DOCUSEAL_URL_PUBLIQUE = "https://signature.chatillon.test"
    settings.DOCUSEAL_JETON = "jeton-api-test"
    with freeze_time("2026-11-02 10:00") as horloge:
        yield {"horloge": horloge, "docuseal": faux}


def _signer_tout(document: Document, faux: FauxDocuSeal, capture) -> Document:
    circuit = document.circuits.get(statut="envoye")
    for rang in range(circuit.signataires.count()):
        faux.signer(int(circuit.soumission), rang)
    with capture(execute=True):
        documents.traiter_webhook({"event_type": "submission.completed", "data": {"id": int(circuit.soumission)}})
    document.refresh_from_db()
    return document


def paris(jour: date, heure: int, minute: int = 0) -> datetime:
    return datetime.combine(jour, time(heure, minute), tzinfo=PARIS)


# --- 1. Campagne annuelle -------------------------------------------------------------------------------------


def test_scenario_1_campagne_annuelle_jusqu_a_la_signature_des_conventions(environnement, django_capture_on_commit_callbacks):
    capture = django_capture_on_commit_callbacks
    gymnase = EspaceFabrique(nom="Gymnase Colette-Besson")
    campagne = Campagne.objects.create(
        saison=saison_2026(), nom="Campagne 2026-2027", ouverture=date(2026, 10, 1), cloture=date(2026, 12, 1), statut="ouverte"
    )
    demandes = []
    for nom in ("Basket club", "Volley club"):
        r = reserver(
            gymnase,
            date(2026, 11, 3),
            "18:00",
            "20:00",
            usager=usager_avec_contact(nom=nom),
            recurrence="FREQ=WEEKLY;BYDAY=TU",
            date_fin=date(2026, 12, 15),
        )
        r.dossier.campagne, r.dossier.saison = campagne, campagne.saison
        r.dossier.save()
        demandes.append(r)
    for statut in ("instruction", "commission"):  # clôture des demandes, instruction, puis commission
        campagnes.changer_statut(campagne, statut, acteur=agent("gestionnaire"))
    groupes = campagnes.analyser(campagne, agent=agent("gestionnaire"))
    assert any({d.pk for d in demandes} <= {c.reservation_id for c in g.candidats} for g in groupes), "conflit détecté"
    with capture(execute=True):
        bilan = campagnes.attribuer(
            campagne,
            {
                demandes[0].pk: {"decision": "attribuer"},
                demandes[1].pk: {"decision": "refuser", "motif": "Créneau déjà attribué"},
            },
            acteur=agent("elu_commission"),
        )
    assert bilan == {"attribuees": 1, "refusees": 1}
    attribuee = Reservation.objects.get(pk=demandes[0].pk)
    assert attribuee.statut == "validee" and Reservation.objects.get(pk=demandes[1].pk).statut == "refusee"
    modele = ModeleDocument.objects.get(code="convention")
    with capture(execute=True):
        lot = documents.creer_lot(
            modele, [attribuee.dossier], acteur=agent("gestionnaire"), libelle="Conventions 2026-2027", envoyer_signature=True
        )
    lot.refresh_from_db()
    assert lot.statut == "termine" and lot.faits == 1
    convention = Document.objects.get(dossier=attribuee.dossier, modele=modele)
    assert convention.statut == "en_signature"
    convention = _signer_tout(convention, environnement["docuseal"], capture)
    assert convention.statut == "signe"
    assert not [c for c in conditions.conditions_manquantes(attribuee) if "convention" in c.lower()]


# --- 2. Location par un particulier non résident ------------------------------------------------------------------


def test_scenario_2_location_particulier_non_resident_devis_payfip_caution_et_retenue(
    environnement, settings, monkeypatch, django_capture_on_commit_callbacks
):
    from apps.paiements import services as paiements
    from apps.paiements.tests.test_payfip import REGLAGES, FauxPayFiP

    capture = django_capture_on_commit_callbacks
    for cle, valeur in REGLAGES.items():
        setattr(settings, cle, valeur)
    payfip = FauxPayFiP()
    from apps.finances.payfip import ClientPayFiP

    origine = ClientPayFiP.__init__
    monkeypatch.setattr(
        ClientPayFiP, "__init__", lambda self, transport=None: origine(self, transport=httpx.MockTransport(payfip))
    )
    salle = EspaceFabrique(nom="Salle des fêtes")
    grille_votee(salle)
    particulier = usager_avec_contact(nom="Dupont", type="particulier", commune="Montrouge", resident=False)
    reservation = reserver(salle, date(2026, 12, 9), "14:00", "18:00", usager=particulier, type_code="location")
    reservations.valider(reservation, acteur=agent("gestionnaire"))
    caution = Caution.objects.get(reservation=reservation)
    assert caution.statut == "attendue"
    gestion = agent("gestionnaire")
    devis = facturation.etablir_devis(reservation.dossier, acteur=gestion)
    assert devis.total_du == 4 * 4000 * 3 // 2, "4 h à 40 € majorées de 50 % (non résident)"
    facturation.accepter_devis(devis, acteur=gestion)
    facture = facturation.facturer(reservation.dossier, acteur=gestion)
    # PayFiP (mode Régie de recette) : tentative, paiement sur le site de la DGFiP, notification relue.
    with capture(execute=True):
        tentative = paiements.initier(facture, contact=particulier.rattachements.first().contact)
    tentative.refresh_from_db()
    payfip.payer(tentative.id_op)
    tentative = paiements.verifier(tentative, source="notification")
    assert tentative.statut == "payee" and Encaissement.objects.get(piece=facture).origine == "payfip"
    regie = agent("regisseur")
    caution = cautions.recevoir(caution, acteur=regie, mode="cheque", reference="Chèque 0045871")
    environnement["horloge"].move_to("2026-12-09 19:00")
    cautions.constater_sortie(
        reservation.occurrences.get(), acteur=regie, constat="degats", observations="Vitre brisée côté scène"
    )
    photo = fichiers.enregistrer("degats.jpg", JPEG, types_autorises=("image/jpeg",), depose_par="test")
    caution = cautions.proposer_retenue(
        caution, acteur=gestion, montant=5000, motif="Remplacement de la vitre côté scène", photos=[photo]
    )
    assert caution.statut == "retenue_partielle" and caution.montant_retenu == 5000
    assert Notification.objects.filter(usager=particulier, sujet__startswith="Retenue sur votre caution").exists()


# --- 3. Fermeture imprévue d'un gymnase -------------------------------------------------------------------------


def test_scenario_3_fermeture_imprevue_notification_groupee_et_besoins_mis_a_jour(django_capture_on_commit_callbacks):
    capture = django_capture_on_commit_callbacks
    site, gymnase = site_gardienne()
    jour = date(2026, 11, 10)
    with capture(execute=True):
        seances = [
            valider_systeme(reserver(gymnase, jour, debut, fin, usager=usager_avec_contact(nom=nom))).occurrences.get()
            for nom, debut, fin in (("Basket club", "17:00", "19:00"), ("Volley club", "19:00", "21:00"))
        ]
    personnel.recalculer_besoins(site.pk, jour)  # aussi déclenché par les séances, après validation
    besoin = Besoin.objects.get(site=site, jour=jour)
    martin = gardien(site, nom="Martin")
    vacation = personnel.affecter(personnel.creer_vacation_pour_besoin(besoin, acteur="système"), martin, acteur="système")
    with capture(execute=True):
        fermeture = Fermeture.objects.create(
            espace=gymnase, debut=paris(jour, 0), fin=paris(jour + timedelta(days=1), 0), motif="Fuite de la toiture"
        )
        touchees = reservations.enregistrer_fermeture(fermeture, acteur=agent("gestionnaire"))
    assert {o.pk for o in touchees} == {s.pk for s in seances}
    avis = Notification.objects.filter(modele__code="fermeture_exceptionnelle")
    assert avis.values("usager").distinct().count() == 2 and avis.values("groupe").distinct().count() == 1
    vacation.refresh_from_db()
    assert not Besoin.objects.filter(site=site, jour=jour).exclude(statut="supprime").exists(), "plus de gardien à prévoir"
    assert vacation.statut == "a_revoir"


# --- 4. Absence d'un gardien --------------------------------------------------------------------------------------


def test_scenario_4_absence_d_un_gardien_remplacant_conforme_propose():
    site, gymnase = site_gardienne()
    jour = date(2026, 11, 10)
    valider_systeme(reserver(gymnase, jour, "18:00", "20:00"))
    personnel.recalculer_besoins(site.pk, jour)
    besoin = Besoin.objects.get(site=site, jour=jour)
    martin, durand, bernard = gardien(site, nom="Martin"), gardien(site, nom="Durand"), gardien(site, nom="Bernard")
    vacation = personnel.affecter(personnel.creer_vacation_pour_besoin(besoin, acteur="système"), martin, acteur="système")
    # Bernard a déjà travaillé de 7 h à 16 h ce jour-là : la soirée porterait sa journée au-delà de 10 heures.
    longue = Vacation.objects.create(site=site, debut=paris(jour, 7), fin=paris(jour, 16), type="normale")
    personnel.affecter(longue, bernard, acteur="système")
    _absence, liberees = personnel.saisir_absence(
        martin, acteur="système", debut=paris(jour, 0), fin=paris(jour, 23, 59), nature="maladie"
    )
    vacation.refresh_from_db()
    besoin.refresh_from_db()
    assert liberees == [vacation] and vacation.statut == "a_pourvoir" and besoin.statut == "a_couvrir"
    propositions = {c["agent"]: c for c in personnel.candidats(vacation)}
    assert durand in propositions and not propositions[durand]["violations"]
    assert bernard not in propositions or propositions[bernard]["violations"], "règle de temps de travail signalée"
    personnel.affecter(vacation, durand, acteur="système")
    besoin.refresh_from_db()
    assert besoin.statut == "couvert"


# --- 5. Clôture d'exercice ----------------------------------------------------------------------------------------


def test_scenario_5_cloture_d_exercice_attestations_et_annexe(environnement, django_capture_on_commit_callbacks):
    from apps.portail.tests.outils import client_contact, compte_actif

    capture = django_capture_on_commit_callbacks
    gymnase = EspaceFabrique(nom="Gymnase des Écoles")
    grille_votee(gymnase)
    exercice = Exercice.objects.create(annee=2026)
    clubs = [usager_avec_contact(nom=nom) for nom in ("Club de judo", "Club de tennis de table")]
    for rang, club in enumerate(clubs):
        Reduction.objects.create(usager=club, taux=10000, fondement="Convention d'objectifs 2026", debut=date(2026, 1, 1))
        valider_systeme(reserver(gymnase, date(2026, 11, 10) + timedelta(days=rang), "18:00", "20:00", usager=club))
    clubs[0].siret = "12345678900011"
    clubs[0].save()
    valorisation.importer_subventions(exercice, b"identifiant;montant\n12345678900011;22 980,00\n", acteur="système")
    valorisation.valoriser_exercice(exercice, acteur="système")
    environnement["horloge"].move_to("2027-01-15 10:00")
    valorisation.cloturer(exercice, acteur=agent("financier"))
    for club in clubs:
        actuelle = Valorisation.objects.get(exercice=exercice, usager=club, actuelle=True)
        assert actuelle.figee and actuelle.total == 4000
        with capture(execute=True):
            actuelle = valorisation.editer_attestation(actuelle, acteur=agent("financier"))
        _signer_tout(actuelle.document, environnement["docuseal"], capture)
    portail = client_contact(compte_actif(clubs[0]))
    from django.test import override_settings

    with override_settings(CANAL="portail", ROOT_URLCONF="config.urls_portail"):
        attestations = portail.get("/api/portail/attestations").json()
    assert [a["exercice"] for a in attestations] == [2026]
    synthese = {ligne["usager"].pk: ligne for ligne in valorisation.synthese(exercice)}
    assert synthese[clubs[0].pk]["alertes"] == ["convention"], "22 980 € + 40 € de concours en nature > 23 000 €"
    annexe = valorisation.annexe_csv(exercice).decode("utf-8-sig")
    assert "Club de judo" in annexe and "Club de tennis de table" in annexe and "23020,00" in annexe
