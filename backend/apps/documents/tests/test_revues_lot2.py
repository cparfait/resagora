"""Corrections des revues du lot 2 : SIG-01 (signature à tour de rôle), SIG-05 (scan contrôlé), DOC-05 et RG-06
(avenant exigé), DOC-02 (fusion stricte avec des objets réels), DOC-06 (relance), RG-13 (fichiers), sécurité (bac à
sable des modèles)."""

from __future__ import annotations

import io
from datetime import datetime, time

import pytest
from django.core import mail
from django.core.files.uploadedfile import SimpleUploadedFile
from django.db import DatabaseError, transaction
from django.test import override_settings
from docx import Document as DocumentWord

from apps.documents import services
from apps.documents.contexte import FOURNISSEURS, construire
from apps.documents.models import Document, LotGeneration, ModeleDocument
from apps.noyau import fichiers
from apps.noyau.exceptions import ErreurMetier
from tests.fabriques import agent

from .test_documents import PDF, _envoyer, _texte_docx, dossier, environnement  # noqa: F401  (fixtures partagées)

pytestmark = pytest.mark.django_db
ELU = "elu.sports@chatillon.test"


def test_sig01_elu_invite_des_que_l_usager_a_signe(dossier, environnement, django_capture_on_commit_callbacks):  # noqa: F811
    from apps.communication.models import Notification

    _document, circuit = _envoyer(dossier, django_capture_on_commit_callbacks)
    assert not [m for m in mail.outbox if ELU in m.to], "l'élu n'est invité qu'à son tour"
    environnement["docuseal"].signer(int(circuit.soumission), 0)
    with django_capture_on_commit_callbacks(execute=True):
        services.synchroniser(circuit)
    invitations = [m for m in mail.outbox if ELU in m.to]
    assert len(invitations) == 1 and "https://signature.chatillon.test/s/" in invitations[0].body
    journal = Notification.objects.get(destinataire=ELU)
    assert "/s/" not in journal.corps and journal.corps_secret == ""
    assert circuit.signataires.get(role="elu").invite_le is not None
    with django_capture_on_commit_callbacks(execute=True):
        services.synchroniser(circuit)
    assert len([m for m in mail.outbox if ELU in m.to]) == 1, "une seule invitation"


def test_sig01_lien_hors_du_service_publie_ignore(settings):
    """Revue sécurité du lot 2 (mineur 4) : pas de redirection ouverte si DocuSeal renvoyait un lien étranger."""
    settings.DOCUSEAL_URL_PUBLIQUE = "https://signature.chatillon.test"
    assert services._lien_sur("https://signature.chatillon.test/s/abc123") == "https://signature.chatillon.test/s/abc123"
    for lien in (
        "https://pirate.test/s/abc",
        "https://signature.chatillon.test/s/abc/../../x",
        "https://signature.chatillon.test/s/a?b",
    ):
        assert services._lien_sur(lien) == ""


def _circuit_manuel(dossier, django_capture_on_commit_callbacks):  # noqa: F811
    gestionnaire = agent("gestionnaire")
    document = services.generer("convention", dossier, acteur=gestionnaire)
    with django_capture_on_commit_callbacks(execute=True):
        services.envoyer_en_signature(document, acteur=gestionnaire, mode="manuel")
    return document


@pytest.mark.urls("config.urls_portail")
@override_settings(CANAL="portail")
def test_sig05_scan_usager_a_controler_avant_confirmation(dossier, django_capture_on_commit_callbacks):  # noqa: F811
    from apps.portail.tests.outils import client_contact, compte_actif

    compte = compte_actif(dossier.usager)
    document = _circuit_manuel(dossier, django_capture_on_commit_callbacks)
    client = client_contact(compte)
    assert client.get(f"/api/portail/dossiers/{dossier.pk}/documents").json()[0]["scan_attendu"] is True
    with django_capture_on_commit_callbacks(execute=True):
        reponse = client.post(
            f"/api/portail/dossiers/{dossier.pk}/documents/{document.pk}/scan-signe",
            {"fichier": SimpleUploadedFile("signe.pdf", PDF)},
            format="multipart",
        )
    assert reponse.status_code == 200 and reponse.json()["statut"] == "scan_a_controler"
    reservation = dossier.reservations.first()
    assert services.convention_manquante(reservation) == "convention en cours de signature"
    assert any("Scan signé déposé" in m.subject for m in mail.outbox)
    document = services.controler_scan(document, acteur=agent("gestionnaire"), accepter=True)
    assert document.statut == "signe_manuellement" and "constatée par" in document.signe_par
    assert services.convention_manquante(reservation) is None


def test_sig05_scan_refuse_par_l_agent_avec_motif(dossier, django_capture_on_commit_callbacks):  # noqa: F811
    document = _circuit_manuel(dossier, django_capture_on_commit_callbacks)
    contact = dossier.usager.rattachements.first().contact
    document = services.deposer_scan_signe(document, "signe.pdf", PDF, acteur=contact, portail=True)
    with pytest.raises(ErreurMetier):
        services.controler_scan(document, acteur=agent("gestionnaire"), accepter=False, motif="")
    with django_capture_on_commit_callbacks(execute=True):
        document = services.controler_scan(document, acteur=agent("gestionnaire"), accepter=False, motif="Page 2 non signée")
    assert document.statut == "en_signature" and document.scan_depose is None
    assert any("n'a pas pu être accepté" in m.subject for m in mail.outbox)
    with pytest.raises(ErreurMetier):
        services.controler_scan(document, acteur=agent("accueil"), accepter=True)


@pytest.mark.urls("config.urls_portail")
@override_settings(CANAL="portail")
def test_sig05_scan_portail_refuse_pendant_une_signature_electronique(dossier, environnement, django_capture_on_commit_callbacks):  # noqa: F811
    from apps.portail.tests.outils import client_contact, compte_actif

    compte = compte_actif(dossier.usager)
    document, circuit = _envoyer(dossier, django_capture_on_commit_callbacks)
    reponse = client_contact(compte).post(
        f"/api/portail/dossiers/{dossier.pk}/documents/{document.pk}/scan-signe",
        {"fichier": SimpleUploadedFile("signe.pdf", PDF)},
        format="multipart",
    )
    assert reponse.status_code == 409
    document.refresh_from_db()
    circuit.refresh_from_db()
    assert document.statut == "en_signature" and circuit.statut == "envoye"


@pytest.mark.urls("config.urls_portail")
@override_settings(CANAL="portail")
def test_sig05_non_signataire_et_autre_usager_refuses(dossier, django_capture_on_commit_callbacks):  # noqa: F811
    from apps.portail.tests.outils import client_contact, compte_actif

    compte = compte_actif(dossier.usager)
    document = _circuit_manuel(dossier, django_capture_on_commit_callbacks)
    dossier.usager.rattachements.update(peut_signer=False)
    url = f"/api/portail/dossiers/{dossier.pk}/documents/{document.pk}/scan-signe"
    reponse = client_contact(compte).post(url, {"fichier": SimpleUploadedFile("signe.pdf", PDF)}, format="multipart")
    assert reponse.status_code == 400 and reponse.json()["code"] == "non_signataire"
    intrus = client_contact(compte_actif())
    assert intrus.post(url, {"fichier": SimpleUploadedFile("signe.pdf", PDF)}, format="multipart").status_code == 404


def test_doc05_creneau_modifie_apres_signature_exige_un_avenant(dossier):  # noqa: F811
    from apps.reservations.models import Reservation

    gestionnaire = agent("gestionnaire")
    convention = services.deposer_scan_signe(
        services.generer("convention", dossier, acteur=gestionnaire), "scan.pdf", PDF, acteur=gestionnaire
    )
    reservation = dossier.reservations.first()
    assert services.convention_manquante(reservation) is None
    Reservation.objects.filter(pk=reservation.pk).update(heure_fin=time(21, 0))
    reservation.refresh_from_db()
    assert "avenant" in (services.convention_manquante(reservation) or "")
    with pytest.raises(ErreurMetier) as refus:
        services.generer("convention", dossier, acteur=gestionnaire)
    assert refus.value.code == "avenant_requis"
    avenant = services.generer_avenant(convention, acteur=gestionnaire, motif="Fin du créneau à 21 h")
    assert "avenant" in (services.convention_manquante(reservation) or "")
    services.deposer_scan_signe(avenant, "avenant.pdf", PDF, acteur=gestionnaire)
    assert services.convention_manquante(reservation) is None


def test_doc02_chaque_modele_genere_avec_des_objets_reels(dossier):  # noqa: F811
    """R2-22 : chaque modèle livré se fusionne en mode strict (variable inconnue = erreur) avec des objets réels."""
    from apps.referentiel.models import Fermeture
    from apps.reservations.recurrence import PARIS

    reservation = dossier.reservations.first()
    fermeture = Fermeture.objects.create(
        espace=reservation.espace,
        debut=datetime(2026, 11, 10, 0, 0, tzinfo=PARIS),
        fin=datetime(2026, 11, 11, 0, 0, tzinfo=PARIS),
        motif="Travaux de peinture",
    )
    objets = {"fermeture": (fermeture, dossier.usager), "etat_des_lieux": reservation.occurrences.order_by("debut").first()}
    comptables = {"devis", "facture", "avoir"}  # fusionnées avec de vraies pièces dans les tests des finances
    verifies = []
    for modele in ModeleDocument.objects.filter(actif=True).select_related("version_active__fichier"):
        if modele.nature not in FOURNISSEURS or modele.nature in comptables:
            continue
        contexte = construire(modele.nature, objets.get(modele.nature, dossier))
        rendu = services.rendre_docx(fichiers.lire(modele.version_active.fichier), contexte)
        assert "{{" not in _texte_docx(rendu), modele.code
        verifies.append(modele.nature)
    assert {"convention", "contrat_location", "avenant", "attribution", "refus", "fermeture", "etat_des_lieux"} <= set(verifies)
    etat = services.generer("etat-des-lieux", objets["etat_des_lieux"], acteur=agent("gestionnaire"))
    assert etat.dossier_id == dossier.pk
    avis = services.generer("fermeture", objets["fermeture"], acteur=agent("gestionnaire"))
    assert avis.usager_id == dossier.usager_id and avis.dossier_id is None


def _docx(texte: str) -> bytes:
    sortie = io.BytesIO()
    word = DocumentWord()
    word.add_paragraph(texte)
    word.save(sortie)
    return sortie.getvalue()


def test_doc01_modele_malveillant_refuse_par_le_bac_a_sable():
    """Revue sécurité du lot 2 (M1) : un modèle ne peut ni exécuter de code ni lire les objets internes."""
    with pytest.raises(ErreurMetier) as refus:
        services.rendre_docx(_docx("{{ cycler.__init__.__globals__.os.popen('id').read() }}"), {"ville": {"nom": "Châtillon"}})
    assert refus.value.code == "modele_invalide"
    with pytest.raises(ErreurMetier):
        services.rendre_docx(_docx("{{ usager.nomm }}"), {"usager": {"nom": "Association"}})


def test_doc06_erreur_inattendue_au_rapport_puis_relance(dossier, client_agent, monkeypatch, django_capture_on_commit_callbacks):  # noqa: F811
    appels = {"n": 0}
    origine = services.generer

    def capricieux(*args, **kwargs):
        appels["n"] += 1
        if appels["n"] == 1:
            raise TypeError("panne simulée")
        return origine(*args, **kwargs)

    monkeypatch.setattr(services, "generer", capricieux)
    client = client_agent(agent("gestionnaire"))
    with django_capture_on_commit_callbacks(execute=True):
        reponse = client.post(
            "/api/gestion/documents/lots",
            {"modele_code": "convention", "libelle": "Lot", "dossiers": [dossier.pk]},
            format="json",
        )
    lot = LotGeneration.objects.get(pk=reponse.json()["id"])
    assert lot.statut == "echec" and "Erreur inattendue" in lot.erreurs[0]["erreur"]
    assert client_agent(agent("accueil")).post(f"/api/gestion/documents/lots/{lot.pk}/relancer").status_code == 403
    with django_capture_on_commit_callbacks(execute=True):
        assert client.post(f"/api/gestion/documents/lots/{lot.pk}/relancer").status_code == 200
    lot.refresh_from_db()
    assert lot.statut == "termine" and lot.faits == 1 and lot.erreurs == []


def test_rg13_fichier_d_un_document_non_modifiable_en_base(dossier):  # noqa: F811
    """Revue sécurité du lot 2 (M7) : changer le fichier stocké d'un document est refusé par la base."""
    from apps.noyau.models import Fichier

    document = services.generer("convention", dossier, acteur=agent("gestionnaire"))
    with pytest.raises(DatabaseError), transaction.atomic():
        Fichier.objects.filter(pk=document.fichier_id).update(sha256="0" * 64)
    with pytest.raises(DatabaseError), transaction.atomic():
        Fichier.objects.filter(pk=document.fichier_id).update(chemin="ailleurs/autre")
    annule = services.annuler(document, acteur=agent("gestionnaire"), motif="Erreur")
    with pytest.raises(DatabaseError), transaction.atomic():
        Document.objects.filter(pk=annule.pk).update(statut="genere")


def test_doc07_visibilite_portail_par_l_agent_autorise(dossier, client_agent):  # noqa: F811
    document = services.generer("convention", dossier, acteur=agent("gestionnaire"))
    url = f"/api/gestion/documents/documents/{document.pk}/visibilite"
    retire = client_agent(agent("gestionnaire")).post(url, {"visible_portail": False}, format="json")
    assert retire.status_code == 200 and retire.json()["visible_portail"] is False
    assert client_agent(agent("accueil")).post(url, {"visible_portail": True}, format="json").status_code == 403
