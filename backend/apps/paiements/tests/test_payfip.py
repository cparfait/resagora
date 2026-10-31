"""Lot 7 — paiement en ligne PayFiP (TAR-07, POR-07), scénarios R7-01 et R7-02, et corrections des revues : tentative
créée avant la redirection, opération créée par le worker, retour du navigateur sans valeur de preuve, notification
signée et revérifiée, idempotence, tentative remplacée encore relue, résultat incohérent ou inconnu à contrôler,
trop-perçu et paiement déjà encaissé, rapprochement, modes Titres et Régie, Ciril, droits (RG-14), immuabilité."""

from __future__ import annotations

import re
import secrets
from datetime import date
from urllib.parse import parse_qs, urlparse

import httpx
import pytest
from django.db import DatabaseError, transaction
from django.test import override_settings
from django.utils import timezone
from freezegun import freeze_time

from apps.communication.models import Notification
from apps.finances import facturation
from apps.finances.models import Encaissement, PieceComptable
from apps.finances.payfip import ClientPayFiP
from apps.finances.tests.outils import PDF, grille_votee, location
from apps.noyau.exceptions import ErreurMetier
from apps.paiements import services
from apps.paiements.models import RemboursementTropPercu, TentativePaiement
from tests.fabriques import EspaceFabrique, agent

pytestmark = pytest.mark.django_db
NUMCLI = "012345"
REGLAGES = {
    "PAYFIP_ACTIF": True,
    "PAYFIP_MODE": "regie",
    "PAYFIP_NUMCLI": NUMCLI,
    "PAYFIP_SAISIE": "T",
    "PAYFIP_URL_SERVICE": "http://payfip.test/tpa/services/securite",
    "PAYFIP_URL_PAIEMENT": "https://payfip.test/tpa/paiementws.web",
    "PAYFIP_URL_NOTIFICATION": "https://equipements.chatillon.test/api/portail/payfip/notification",
    "PAYFIP_SECRET": "secret-de-test-payfip-24-caracteres",
    "PAYFIP_MONTANT_MINIMUM": 100,
    "RECETTE": True,
}


class FauxPayFiP:
    """Service SOAP « PaiementSecuriseService » simulé (mêmes règles que simulateurs/payfip.py)."""

    def __init__(self):
        self.operations: dict[str, dict[str, str]] = {}
        self.appels: list[str] = []
        self.injoignable = False

    def __call__(self, requete: httpx.Request) -> httpx.Response:
        if self.injoignable:
            raise httpx.ConnectError("injoignable")
        xml = requete.content.decode()

        def valeur(nom: str) -> str:
            trouve = re.search(rf"<{nom}>([^<]*)</{nom}>", xml)
            return trouve.group(1) if trouve else ""

        if "creerPaiementSecurise" in xml:
            self.appels.append("creer")
            if valeur("numcli") != NUMCLI:
                return self._faute("P1", "Numéro de client inconnu")
            id_op = secrets.token_hex(16)
            champs = ("numcli", "exer", "refdet", "objet", "montant", "mel", "urlnotif", "urlredirect", "saisie")
            self.operations[id_op] = {c: valeur(c) for c in champs} | {"resultrans": ""}
            return self._reponse(f"<idOp>{id_op}</idOp>")
        self.appels.append("detail")
        operation = self.operations.get(valeur("idOp"))
        if operation is None:
            return self._faute("P2", "Opération inconnue")
        if not operation["resultrans"]:
            return self._faute("P3", "Paiement non terminé")
        retour = "".join(
            f"<{c}>{operation[c]}</{c}>" for c in ("exer", "mel", "montant", "numcli", "objet", "refdet", "resultrans", "saisie")
        )
        return self._reponse(
            f"{retour}<idOp>{valeur('idOp')}</idOp><numauto>{operation.get('numauto', '')}</numauto>"
            "<dattrans>12112026</dattrans><heurtrans>1015</heurtrans>"
        )

    def payer(self, id_op: str, resultat: str = "P", **modifs: str) -> None:
        self.operations[id_op].update({"resultrans": resultat, "numauto": "654321" if resultat in "PV" else "", **modifs})

    @staticmethod
    def _reponse(corps: str) -> httpx.Response:
        return httpx.Response(
            200,
            content=(
                '<S:Envelope xmlns:S="http://schemas.xmlsoap.org/soap/envelope/"><S:Body>'
                f"<ns2:reponse xmlns:ns2='urn:payfip'><return>{corps}</return></ns2:reponse></S:Body></S:Envelope>"
            ).encode(),
        )

    @staticmethod
    def _faute(code: str, libelle: str) -> httpx.Response:
        return httpx.Response(
            500,
            content=(
                '<S:Envelope xmlns:S="http://schemas.xmlsoap.org/soap/envelope/"><S:Body><S:Fault><faultcode>S:Server</faultcode>'
                f"<faultstring>{libelle}</faultstring><detail><FonctionnelleErreur><code>{code}</code><libelle>{libelle}</libelle>"
                "</FonctionnelleErreur></detail></S:Fault></S:Body></S:Envelope>"
            ).encode(),
        )


@pytest.fixture
def payfip(monkeypatch, settings, modeles_documents):
    from apps.documents import services as documents
    from apps.noyau import fichiers

    monkeypatch.setattr(documents, "convertir_en_pdfa", lambda nom, docx, transport=None: PDF)
    monkeypatch.setattr(fichiers, "analyser_clamav", lambda contenu: None)
    for cle, valeur in REGLAGES.items():
        setattr(settings, cle, valeur)
    faux = FauxPayFiP()
    origine = ClientPayFiP.__init__

    def initialiser(self, transport=None):
        origine(self, transport=httpx.MockTransport(faux))

    monkeypatch.setattr(ClientPayFiP, "__init__", initialiser)
    with freeze_time("2026-11-12 10:00") as horloge:
        faux.horloge = horloge
        yield faux


@pytest.fixture
def facture(payfip):
    salle = EspaceFabrique(nom="Salle des fêtes")
    grille_votee(salle)
    return facturation.facturer(location(espace=salle).dossier, acteur=agent("gestionnaire"))


def _autre_facture(facture):
    return facturation.facturer(
        location(espace=facture.dossier.reservations.first().espace, jour=date(2026, 12, 16)).dossier,
        acteur=agent("gestionnaire"),
    )


def _initier(facture, capture, contact=None) -> TentativePaiement:
    with capture(execute=True):
        tentative = services.initier(facture, contact=contact)
    return TentativePaiement.objects.get(pk=tentative.pk)


def _notifier(client, tentative: TentativePaiement, capture, **surcharges):
    requete = {"ref": str(tentative.uuid), "sig": services.signature(str(tentative.uuid)), **surcharges}
    with capture(execute=True):
        return client.post(
            f"/api/portail/payfip/notification?ref={requete['ref']}&sig={requete['sig']}",
            {"idop": requete.get("idop", tentative.id_op)},
        )


# --- POR-07 / R7-01 et TAR-07 / R7-02 ---------------------------------------------------------------------------


@override_settings(CANAL="portail")
@pytest.mark.urls("config.urls_portail")
def test_por07_r7_01_payer_une_facture_en_ligne(payfip, facture, django_capture_on_commit_callbacks):
    from django.test import Client

    from apps.portail.tests.outils import client_contact, compte_actif

    capture = django_capture_on_commit_callbacks
    usager = client_contact(compte_actif(facture.usager))
    with capture(execute=True):
        reponse = usager.post(f"/api/portail/factures/{facture.pk}/paiement-en-ligne")
    assert reponse.status_code == 202 and reponse.json()["statut"] == "creee", "tentative enregistrée avant tout"
    tentative = TentativePaiement.objects.get(uuid=reponse.json()["uuid"])
    # Opération créée par le worker : le portail obtient alors l'adresse de PayFiP.
    assert tentative.statut == "redirigee" and tentative.montant == facture.reste_du
    assert tentative.refdet == facture.reference_virement and "-" not in tentative.refdet
    etat = usager.get(f"/api/portail/paiements/{tentative.uuid}").json()
    assert etat["url"] == f"https://payfip.test/tpa/paiementws.web?idop={tentative.id_op}" and not etat["termine"]
    notification = payfip.operations[tentative.id_op]["urlnotif"].replace("&amp;", "&")
    assert set(parse_qs(urlparse(notification).query)) == {"ref", "sig"}
    # Retour du navigateur sans résultat chez PayFiP : rien n'est encaissé, quoi que dise l'adresse.
    with capture(execute=True):
        assert usager.get(f"/api/portail/paiements/{tentative.uuid}?resultrans=P").json()["statut"] == "redirigee"
    assert not Encaissement.objects.exists()
    payfip.payer(tentative.id_op)
    assert _notifier(Client(), tentative, capture).status_code == 200
    facture.refresh_from_db()
    tentative.refresh_from_db()
    assert tentative.statut == "payee" and tentative.numauto == "654321" and facture.reste_du == 0
    encaissement = Encaissement.objects.get(piece=facture)
    assert encaissement.origine == "payfip" and encaissement.montant == tentative.montant
    assert usager.get(f"/api/portail/paiements/{tentative.uuid}").json()["statut"] == "payee"


@override_settings(CANAL="portail")
@pytest.mark.urls("config.urls_portail")
def test_tar07_r7_02_deux_notifications_un_seul_encaissement(payfip, facture, django_capture_on_commit_callbacks):
    from django.test import Client

    capture = django_capture_on_commit_callbacks
    tentative = _initier(facture, capture)
    perimee = TentativePaiement.objects.get(pk=tentative.pk)  # objet resté « en cours » en mémoire
    payfip.payer(tentative.id_op)
    for _ in range(2):
        assert _notifier(Client(), tentative, capture).status_code == 200
    services.verifier(perimee, source="retour concurrent")
    assert Encaissement.objects.filter(piece=facture).count() == 1
    tentative.refresh_from_db()
    assert tentative.notifications == 2 and tentative.trop_percu == 0
    assert Notification.objects.filter(modele__code="paiement_en_ligne_recu").count() == 1


# --- Notification (B1, M4 sécurité) -------------------------------------------------------------------------------


@override_settings(CANAL="portail")
@pytest.mark.urls("config.urls_portail")
def test_tar07_notification_forgee_croisee_ou_mal_formee_ecartee(payfip, facture, django_capture_on_commit_callbacks):
    from django.test import Client

    capture = django_capture_on_commit_callbacks
    tentative = _initier(facture, capture)
    autre = _initier(_autre_facture(facture), capture)
    payfip.payer(tentative.id_op)
    appels = len(payfip.appels)
    for surcharge in (
        {"sig": "0" * 32},
        {"sig": services.signature(str(autre.uuid))},  # signature d'une autre tentative
        {"idop": autre.id_op},  # opération d'une autre tentative
        {"sig": "é" * 32},
        {"ref": "pas-un-uuid"},
    ):
        reponse = _notifier(Client(), tentative, capture, **surcharge)
        assert reponse.status_code == 200 and reponse.json() == {"recu": True}, "réponse neutre"
    assert len(payfip.appels) == appels, "aucun appel à PayFiP pour une notification invalide"
    assert not Encaissement.objects.exists()


@pytest.mark.parametrize("champ", ["montant", "refdet", "exer", "numcli", "saisie"])
def test_tar07_resultat_incoherent_a_controler_et_signale(payfip, facture, champ, django_capture_on_commit_callbacks):
    tentative = _initier(facture, django_capture_on_commit_callbacks)
    payfip.payer(tentative.id_op, **{champ: "W" if champ == "saisie" else "9999"})
    tentative = services.verifier(tentative, source="notification")
    assert tentative.statut == "a_controler" and tentative.controle == "incoherent" and champ in tentative.erreur
    assert not Encaissement.objects.exists()
    assert Notification.objects.filter(modele__code="paiement_en_ligne_a_controler").exists()
    assert "vérification" in services.motif_non_payable(PieceComptable.objects.get(pk=facture.pk))


def test_tar07_resultat_inconnu_a_controler_v_vaut_paiement(payfip, facture, django_capture_on_commit_callbacks):
    capture = django_capture_on_commit_callbacks
    tentative = _initier(facture, capture)
    payfip.payer(tentative.id_op, "X")
    tentative = services.verifier(tentative, source="notification")
    assert tentative.controle == "resultat_inconnu"
    agent_regie = agent("regisseur")
    with pytest.raises(ErreurMetier):
        services.clore_apres_controle(tentative, acteur=agent_regie, motif="court")
    close = services.clore_apres_controle(tentative, acteur=agent_regie, motif="Vérifié avec la DGFiP : aucun prélèvement.")
    assert close.statut == "erreur" and services.payable(PieceComptable.objects.get(pk=facture.pk))
    seconde = _initier(PieceComptable.objects.get(pk=facture.pk), capture)
    payfip.payer(seconde.id_op, "V")
    assert services.verifier(seconde, source="notification").statut == "payee"


def test_tar07_paiement_de_test_hors_recette_non_encaisse(payfip, facture, settings, django_capture_on_commit_callbacks):
    tentative = _initier(facture, django_capture_on_commit_callbacks)
    settings.RECETTE = False
    payfip.payer(tentative.id_op)
    assert services.verifier(tentative, source="notification").controle == "saisie_test"
    assert not Encaissement.objects.exists()


# --- Tentative remplacée (B2 des deux revues) ---------------------------------------------------------------------


def test_tar07_paiement_sur_tentative_remplacee_encaisse_et_second_paiement_en_trop_percu(
    payfip, facture, django_capture_on_commit_callbacks
):
    from tests.fabriques import ContactFabrique

    capture = django_capture_on_commit_callbacks
    contact = ContactFabrique()
    premiere = _initier(facture, capture, contact=contact)
    assert _initier(facture, capture, contact=contact).pk == premiere.pk, "reprise de moins de 20 minutes"
    payfip.horloge.move_to("2026-11-12 10:25")
    seconde = _initier(facture, capture, contact=contact)
    premiere.refresh_from_db()
    assert seconde.pk != premiere.pk and premiere.statut == "remplacee"
    payfip.payer(premiere.id_op)  # l'usager paie dans le premier onglet…
    payfip.payer(seconde.id_op)  # … puis dans le second
    services.rapprocher()
    services.verifier(TentativePaiement.objects.get(pk=seconde.pk), source="notification")
    premiere.refresh_from_db()
    seconde.refresh_from_db()
    assert premiere.statut == "payee" and premiere.encaissement is not None
    assert seconde.statut == "payee" and seconde.trop_percu == seconde.montant and seconde.controle == "trop_percu"
    assert Encaissement.objects.filter(piece=facture).count() == 1


def test_tar07_remplacee_avant_creation_de_l_operation_close(payfip, facture):
    with transaction.atomic():
        premiere = services.initier(facture, contact=None)  # tâches non exécutées : opération non créée
    payfip.horloge.move_to("2026-11-12 10:25")
    with transaction.atomic():
        services.initier(facture, contact=None)
    premiere.refresh_from_db()
    assert premiere.statut == "erreur" and premiere.id_op is None


# --- Trop-perçu, paiement déjà encaissé, remboursement (M2, M6) --------------------------------------------------


def test_tar07_paiement_deja_pointe_a_verifier_puis_remboursement_trace(payfip, facture, django_capture_on_commit_callbacks):
    tentative = _initier(facture, django_capture_on_commit_callbacks)
    montant = facture.reste_du
    facturation.pointer(facture, acteur=agent("regisseur"), montant=montant, jour=date(2026, 11, 12), reference="VIR 77")
    payfip.payer(tentative.id_op)
    tentative = services.verifier(tentative, source="notification")
    assert tentative.statut == "payee" and tentative.trop_percu == montant and tentative.controle == "doublon_probable"
    regie = agent("regisseur")
    services.enregistrer_remboursement(tentative, acteur=regie, date=date(2026, 11, 20), reference="MANDAT 42", par="ville")
    assert RemboursementTropPercu.objects.get(tentative=tentative).montant == montant
    with pytest.raises(ErreurMetier):
        services.enregistrer_remboursement(tentative, acteur=regie, date=date(2026, 11, 21), reference="MANDAT 43", par="ville")
    with pytest.raises(DatabaseError), transaction.atomic():
        RemboursementTropPercu.objects.filter(tentative=tentative).update(reference="autre")


# --- Rapprochement (M3) ---------------------------------------------------------------------------------------------


def test_tar07_rapprochement_rattrape_expire_puis_relit_un_paiement_tardif(payfip, facture, django_capture_on_commit_callbacks):
    perdue = _initier(facture, django_capture_on_commit_callbacks)
    payfip.horloge.move_to("2026-11-12 10:30")
    assert services.rapprocher()["relues"] == 1
    assert TentativePaiement.objects.get(pk=perdue.pk).statut == "redirigee"
    payfip.horloge.move_to("2026-11-13 11:00")
    services.rapprocher()
    assert TentativePaiement.objects.get(pk=perdue.pk).statut == "expiree", "sans résultat après 24 h"
    payfip.payer(perdue.id_op)  # résultat arrivé tard chez PayFiP
    payfip.horloge.move_to("2026-11-14 09:00")
    bilan = services.rapprocher()
    assert bilan["payees"] == 1 and TentativePaiement.objects.get(pk=perdue.pk).statut == "payee"


def test_tar07_rapprochement_previent_le_service_de_ce_qui_demande_une_action(
    payfip, facture, django_capture_on_commit_callbacks
):
    tentative = _initier(facture, django_capture_on_commit_callbacks)
    payfip.payer(tentative.id_op, montant="1")
    payfip.horloge.move_to("2026-11-12 10:30")
    assert services.rapprocher()["a_controler"] == 1
    assert Notification.objects.filter(modele__code="paiements_en_ligne_rapprochement").exists()


def test_tar07_relecture_au_retour_limitee_a_une_toutes_les_30_secondes(payfip, facture, django_capture_on_commit_callbacks):
    capture = django_capture_on_commit_callbacks
    tentative = _initier(facture, capture)
    avant = payfip.appels.count("detail")
    with capture(execute=True):
        for _ in range(5):
            services.demander_relecture(TentativePaiement.objects.get(pk=tentative.pk), source="retour")
    assert payfip.appels.count("detail") == avant + 1
    payfip.horloge.move_to("2026-11-12 10:01")
    with capture(execute=True):
        services.demander_relecture(TentativePaiement.objects.get(pk=tentative.pk), source="retour")
    assert payfip.appels.count("detail") == avant + 2


def test_tar07_payfip_injoignable_puis_operation_jamais_creee_expiree(payfip, facture):
    payfip.injoignable = True
    with transaction.atomic():
        tentative = services.initier(facture, contact=None)
    with pytest.raises(ErreurMetier) as refus:
        services.creer_operation(tentative.pk)
    assert refus.value.code == "payfip_indisponible"
    assert TentativePaiement.objects.get(pk=tentative.pk).statut == "creee"
    payfip.horloge.move_to("2026-11-13 11:00")
    payfip.injoignable = False
    services.rapprocher()
    assert TentativePaiement.objects.get(pk=tentative.pk).statut == "expiree"


# --- Modes, références, montant minimal (B1 métier, M5) ---------------------------------------------------------------


def test_tar07_mode_titres_reference_du_titre_et_exercice_de_la_piece(
    payfip, facture, settings, django_capture_on_commit_callbacks
):
    settings.PAYFIP_MODE = "titres"
    assert "titre" in services.motif_non_payable(facture)
    PieceComptable.objects.filter(pk=facture.pk).update(
        statut="titre_emis", titre_numero="T2026000451", titre_le=date(2027, 1, 5), exercice=2026
    )
    tentative = _initier(PieceComptable.objects.get(pk=facture.pk), django_capture_on_commit_callbacks)
    assert (tentative.mode, tentative.refdet, tentative.exer) == ("titres", "T2026000451", "2026")
    illisible = _autre_facture(facture)
    PieceComptable.objects.filter(pk=illisible.pk).update(statut="titre_emis", titre_numero="T-2026/451")
    assert "incompatible" in services.motif_non_payable(PieceComptable.objects.get(pk=illisible.pk))
    PieceComptable.objects.filter(pk=illisible.pk).update(statut="en_recouvrement")
    assert not services.payable(PieceComptable.objects.get(pk=illisible.pk)), "recouvrement contentieux : au comptable"


def test_tar07_mode_regie_facture_transmise_au_comptable_non_payable_et_signalee_a_l_export(
    payfip, facture, django_capture_on_commit_callbacks
):
    from apps.finances import titres
    from apps.finances.ciril import export

    tentative = _initier(facture, django_capture_on_commit_callbacks)
    payfip.payer(tentative.id_op)
    services.verifier(tentative, source="notification")
    piece = PieceComptable.objects.get(pk=facture.pk)
    assert piece.statut == "solde" and piece in titres.a_titrer()
    assert export.CHAMPS["mode_encaissement"](piece) == "REGIE"
    assert export.CHAMPS["montant_encaisse_regie_centimes"](piece) == piece.total_du
    autre = _autre_facture(facture)
    titres.exporter([autre], acteur=agent("financier"))
    assert "comptable" in services.motif_non_payable(PieceComptable.objects.get(pk=autre.pk))


def test_tar13_l_etat_ciril_confirme_un_paiement_en_ligne_sans_le_dupliquer(payfip, facture, django_capture_on_commit_callbacks):
    from apps.finances.ciril import encaissements

    tentative = _initier(facture, django_capture_on_commit_callbacks)
    payfip.payer(tentative.id_op)
    services.verifier(tentative, source="notification")
    montant = f"{facture.total_du // 100},{facture.total_du % 100:02d}"
    contenu = f"Référence;Montant encaissé;Date encaissement\n{facture.numero};{montant};13/11/2026\n".encode("cp1252")
    lot = encaissements.importer("etat.csv", contenu, acteur=agent("regisseur"))
    assert lot.confirmees == 1 and lot.rapprochees == 0 and lot.rejets == []
    assert Encaissement.objects.filter(piece=facture).count() == 1


def test_tar07_montant_minimal_et_paiement_desactive(payfip, facture, settings):
    settings.PAYFIP_MONTANT_MINIMUM = facture.reste_du + 1
    assert "commence à" in services.motif_non_payable(facture)
    settings.PAYFIP_MONTANT_MINIMUM = 100
    settings.PAYFIP_ACTIF = False
    with pytest.raises(ErreurMetier):
        services.initier(facture, contact=None)


# --- Immuabilité (RG-13) et RGPD -------------------------------------------------------------------------------------


def test_rg13_resultat_de_paiement_definitif_en_base(payfip, facture, django_capture_on_commit_callbacks):
    from tests.fabriques import ContactFabrique

    tentative = _initier(facture, django_capture_on_commit_callbacks, contact=ContactFabrique(courriel="payeur@exemple.test"))
    payfip.payer(tentative.id_op)
    services.verifier(tentative, source="notification")
    for ecriture in (
        lambda: TentativePaiement.objects.filter(pk=tentative.pk).update(statut="refusee"),
        lambda: TentativePaiement.objects.filter(pk=tentative.pk).update(montant=1),
        lambda: TentativePaiement.objects.filter(pk=tentative.pk).delete(),
    ):
        with pytest.raises(DatabaseError), transaction.atomic():
            ecriture()
    assert services.anonymiser_usager(facture.usager) == 1
    assert TentativePaiement.objects.get(pk=tentative.pk).mel == ""


# --- Droits (RG-14) -------------------------------------------------------------------------------------------------


@override_settings(CANAL="portail")
@pytest.mark.urls("config.urls_portail")
def test_rg14_portail_un_contact_ne_paie_ni_ne_voit_la_facture_d_un_autre(payfip, facture, django_capture_on_commit_callbacks):
    from apps.portail.tests.outils import client_contact, compte_actif

    intrus = client_contact(compte_actif())
    assert intrus.post(f"/api/portail/factures/{facture.pk}/paiement-en-ligne").status_code == 404
    tentative = _initier(facture, django_capture_on_commit_callbacks)
    assert intrus.get(f"/api/portail/paiements/{tentative.uuid}").status_code == 404
    assert client_contact(compte_actif(facture.usager)).get(f"/api/portail/paiements/{tentative.uuid}").status_code == 200


def test_rg14_back_office_suivi_relecture_cloture_et_rapprochement(
    payfip, facture, client_agent, django_capture_on_commit_callbacks
):
    capture = django_capture_on_commit_callbacks
    tentative = _initier(facture, capture)
    regie = client_agent(agent("regisseur"))
    liste = regie.get("/api/gestion/finances/paiements-en-ligne").json()
    assert liste["count"] == 1 and liste["results"][0]["facture"] == facture.numero
    payfip.payer(tentative.id_op)
    with capture(execute=True):
        assert regie.post(f"/api/gestion/finances/paiements-en-ligne/{tentative.pk}/verifier").status_code == 200
    assert TentativePaiement.objects.get(pk=tentative.pk).statut == "payee"
    with capture(execute=True):
        assert regie.post("/api/gestion/finances/paiements-en-ligne/rapprocher").status_code == 200
    assert client_agent(agent("accueil")).get("/api/gestion/finances/paiements-en-ligne").status_code == 403
    financier = client_agent(agent("financier"))
    assert financier.get("/api/gestion/finances/paiements-en-ligne").status_code == 200
    assert financier.post(f"/api/gestion/finances/paiements-en-ligne/{tentative.pk}/verifier").status_code == 403
    local = client_agent(agent("regisseur", EspaceFabrique(nom="Ailleurs").batiment.site))
    assert local.get("/api/gestion/finances/paiements-en-ligne").json()["count"] == 0
    assert local.post(f"/api/gestion/finances/paiements-en-ligne/{tentative.pk}/verifier").status_code == 404
    assert local.post("/api/gestion/finances/paiements-en-ligne/rapprocher").status_code == 403
    motif = {"motif": "Vérifié avec la DGFiP : rien à faire."}
    assert local.post(f"/api/gestion/finances/paiements-en-ligne/{tentative.pk}/clore", motif, format="json").status_code == 403
    assert regie.post(f"/api/gestion/finances/paiements-en-ligne/{tentative.pk}/clore", motif, format="json").status_code == 409


def test_tar07_date_d_encaissement_en_heure_de_paris(payfip, facture, django_capture_on_commit_callbacks):
    tentative = _initier(facture, django_capture_on_commit_callbacks)
    payfip.payer(tentative.id_op)
    services.verifier(tentative, source="notification")
    assert Encaissement.objects.get(piece=facture).date == date(2026, 11, 12)
    assert timezone.localtime(TentativePaiement.objects.get(pk=tentative.pk).paye_le).hour == 10
