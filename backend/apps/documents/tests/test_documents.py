"""DOC-01 à DOC-07, SIG-01 à SIG-05, POR-10, RG-13 : modèles versionnés, génération PDF/A, signature."""

from __future__ import annotations

import hashlib
import io
from datetime import date

import httpx
import pytest
from django.core import mail
from django.core.files.uploadedfile import SimpleUploadedFile
from django.db import DatabaseError, transaction
from django.test import override_settings
from docx import Document as DocumentWord
from freezegun import freeze_time

from apps.documents import services
from apps.documents.contexte import construire
from apps.documents.docuseal import ClientDocuSeal
from apps.documents.gotenberg import convertir_en_pdfa
from apps.documents.models import CircuitSignature, Document, LotGeneration, ModeleDocument
from apps.noyau import fichiers
from apps.noyau.exceptions import ErreurMetier
from apps.reservations import conditions
from apps.reservations.tests.outils import reserver, valider_systeme
from tests.fabriques import EspaceFabrique, SiteFabrique, agent, saison_2026
from tests.faux_docuseal import BASE, FauxDocuSeal

pytestmark = pytest.mark.django_db
PDF = b"%PDF-1.7\n% PDF/A-2b simule <pdfaid:part>2</pdfaid:part>\n%%EOF\n"


@pytest.fixture(autouse=True)
def environnement(monkeypatch, settings, modeles_documents):
    rendus: list[bytes] = []

    def gotenberg(nom: str, docx: bytes, transport: object = None) -> bytes:
        rendus.append(docx)
        return PDF

    monkeypatch.setattr(services, "convertir_en_pdfa", gotenberg)
    monkeypatch.setattr(fichiers, "analyser_clamav", lambda contenu: None)
    faux = FauxDocuSeal()
    origine = ClientDocuSeal.__init__

    def initialiser(self: ClientDocuSeal, transport: httpx.BaseTransport | None = None) -> None:
        origine(self, transport=httpx.MockTransport(faux))

    monkeypatch.setattr(ClientDocuSeal, "__init__", initialiser)
    settings.DOCUSEAL_URL = BASE
    settings.DOCUSEAL_URL_PUBLIQUE = "https://signature.chatillon.test"
    settings.DOCUSEAL_JETON = "jeton-api-test"
    with freeze_time("2026-11-01 10:00"):
        yield {"rendus": rendus, "docuseal": faux}


def _texte_docx(contenu: bytes) -> str:
    doc = DocumentWord(io.BytesIO(contenu))
    morceaux = [p.text for p in doc.paragraphs]
    for table in doc.tables:
        for ligne in table.rows:
            morceaux += [c.text for c in ligne.cells]
    return "\n".join(morceaux)


@pytest.fixture
def dossier():
    saison_2026()
    site = SiteFabrique()
    r = valider_systeme(
        reserver(
            EspaceFabrique(batiment__site=site, nom="Gymnase Jean-Moulin"),
            date(2026, 11, 3),
            "18:00",
            "20:00",
            recurrence="FREQ=WEEKLY;BYDAY=TU",
            date_fin=date(2026, 12, 15),
            type_code="creneau_annuel",
        )
    )
    return r.dossier


def test_doc02_chaque_modele_livre_se_genere_sans_champ_inconnu():
    for modele in ModeleDocument.objects.select_related("version_active__fichier"):
        rendu = services.rendre_docx(fichiers.lire(modele.version_active.fichier), services.exemple_de_contexte(modele.nature))
        texte = _texte_docx(rendu)
        assert "{{" not in texte and "{%" not in texte, modele.code
        assert "Ville de Châtillon" in DocumentWord(io.BytesIO(rendu)).sections[0].header.paragraphs[0].text
    assert ModeleDocument.objects.count() == 11


def test_doc03_convention_affiche_la_recurrence_lisible(dossier, environnement):
    document = services.generer("convention", dossier, acteur=agent("gestionnaire"))
    texte = _texte_docx(environnement["rendus"][-1])
    assert "tous les mardis de 18 h à 20 h, hors vacances scolaires et jours fériés" in texte
    assert dossier.usager.nom in texte and document.contexte["reservations"][0]["espace"] == "Gymnase Jean-Moulin"


def test_doc04_pdf_a_2b_et_empreinte_enregistree(dossier):
    document = services.generer("convention", dossier, acteur=agent("gestionnaire"))
    assert document.sha256 == hashlib.sha256(fichiers.lire(document.fichier)).hexdigest()
    recu = {}

    def gotenberg(requete: httpx.Request) -> httpx.Response:
        recu["corps"] = requete.content
        recu["chemin"] = requete.url.path
        return httpx.Response(200, content=PDF)

    assert convertir_en_pdfa("D1", b"PK\x03\x04docx", transport=httpx.MockTransport(gotenberg)) == PDF
    assert recu["chemin"] == "/forms/libreoffice/convert" and b"PDF/A-2b" in recu["corps"] and b"pdfua" in recu["corps"]


def test_doc01_nouvelle_version_deposee_testee_puis_activee(client_agent):
    modele = ModeleDocument.objects.get(code="refus")
    administrateur = client_agent(agent("administrateur"))
    actuelle = administrateur.get(f"/api/gestion/documents/modeles/{modele.pk}/versions/{modele.version_active_id}/fichier")
    assert actuelle.status_code == 200
    word = DocumentWord(io.BytesIO(b"".join(actuelle.streaming_content)))
    word.add_paragraph("Version révisée pour {{ usager.nom }}.")
    sortie = io.BytesIO()
    word.save(sortie)
    depot = administrateur.post(
        f"/api/gestion/documents/modeles/{modele.pk}/deposer-version",
        {"fichier": SimpleUploadedFile("refus.docx", sortie.getvalue()), "commentaire": "Ajout d'une phrase"},
        format="multipart",
    )
    assert depot.status_code == 201 and depot.json()["numero"] == 2
    modele.refresh_from_db()
    assert modele.version_active.numero == 2
    casse = DocumentWord(io.BytesIO(sortie.getvalue()))
    casse.add_paragraph("{% if %}")
    sortie_cassee = io.BytesIO()
    casse.save(sortie_cassee)
    refus = administrateur.post(
        f"/api/gestion/documents/modeles/{modele.pk}/deposer-version",
        {"fichier": SimpleUploadedFile("refus.docx", sortie_cassee.getvalue())},
        format="multipart",
    )
    assert refus.status_code == 400
    pdf = administrateur.post(
        f"/api/gestion/documents/modeles/{modele.pk}/deposer-version",
        {"fichier": SimpleUploadedFile("refus.pdf", PDF)},
        format="multipart",
    )
    assert pdf.status_code == 400
    assert (
        client_agent(agent("gestionnaire"))
        .post(
            f"/api/gestion/documents/modeles/{modele.pk}/deposer-version",
            {"fichier": SimpleUploadedFile("refus.docx", sortie.getvalue())},
            format="multipart",
        )
        .status_code
        == 403
    )
    v1 = modele.versions.get(numero=1)
    assert (
        administrateur.post(
            f"/api/gestion/documents/modeles/{modele.pk}/activer-version", {"version": v1.pk}, format="json"
        ).status_code
        == 200
    )


def test_doc05_rg13_document_signe_modifie_par_avenant(dossier):
    gestionnaire = agent("gestionnaire")
    document = services.generer("convention", dossier, acteur=gestionnaire)
    signe = services.deposer_scan_signe(document, "scan.pdf", PDF, acteur=gestionnaire)
    assert signe.statut == "signe_manuellement"
    with pytest.raises(DatabaseError), transaction.atomic():
        Document.objects.filter(pk=signe.pk).update(titre="Convention modifiée")
    with pytest.raises(DatabaseError), transaction.atomic():
        Document.objects.filter(pk=signe.pk).update(statut="genere")
    with pytest.raises(DatabaseError), transaction.atomic():
        Document.objects.filter(pk=signe.pk).delete()
    avenant = services.generer_avenant(signe, acteur=gestionnaire, motif="Ajout du créneau du jeudi")
    assert avenant.nature == "avenant" and avenant.parent_id == signe.pk
    assert avenant.contexte["avenant"]["numero_origine"] == signe.numero


def test_rg13_contenu_d_un_document_genere_non_modifiable(dossier):
    document = services.generer("convention", dossier, acteur=agent("gestionnaire"))
    with pytest.raises(DatabaseError), transaction.atomic():
        Document.objects.filter(pk=document.pk).update(sha256="0" * 64)
    annule = services.annuler(document, acteur=agent("gestionnaire"), motif="Erreur de créneau")
    assert annule.statut == "annule"


def test_doc06_generation_en_lot_avec_rapport_d_erreurs(dossier, client_agent, django_capture_on_commit_callbacks):
    sans_signataire = valider_systeme(
        reserver(dossier.reservations.first().espace, date(2026, 11, 5), "18:00", "20:00", type_code="creneau_annuel")
    ).dossier
    sans_signataire.usager.rattachements.update(peut_signer=False)
    client = client_agent(agent("gestionnaire"))
    with django_capture_on_commit_callbacks(execute=True):
        reponse = client.post(
            "/api/gestion/documents/lots",
            {
                "modele_code": "convention",
                "libelle": "Conventions 2026-2027",
                "dossiers": [dossier.pk, sans_signataire.pk],
                "envoyer_signature": True,
            },
            format="json",
        )
    assert reponse.status_code == 201
    lot = LotGeneration.objects.get(pk=reponse.json()["id"])
    assert lot.statut == "termine" and lot.total == 2 and lot.faits == 1
    assert lot.erreurs[0]["dossier"] == sans_signataire.numero and "habilité à signer" in lot.erreurs[0]["erreur"]
    assert client.get(f"/api/gestion/documents/lots/{lot.pk}").json()["faits"] == 1


def test_doc07_telechargement_dans_le_perimetre_seulement(dossier, client_agent):
    document = services.generer("convention", dossier, acteur=agent("gestionnaire"))
    site = dossier.reservations.first().espace.batiment.site
    assert client_agent(agent("accueil", site)).get(f"/api/gestion/documents/documents/{document.pk}/fichier").status_code == 200
    assert (
        client_agent(agent("accueil", SiteFabrique())).get(f"/api/gestion/documents/documents/{document.pk}/fichier").status_code
        == 404
    )


def _envoyer(dossier, django_capture_on_commit_callbacks):
    gestionnaire = agent("gestionnaire")
    document = services.generer("convention", dossier, acteur=gestionnaire)
    with django_capture_on_commit_callbacks(execute=True):
        circuit = services.envoyer_en_signature(document, acteur=gestionnaire, mode="docuseal")
    circuit.refresh_from_db()
    return document, circuit


def test_sig01_envoi_ordonne_avec_expiration(dossier, environnement, django_capture_on_commit_callbacks):
    document, circuit = _envoyer(dossier, django_capture_on_commit_callbacks)
    soumission = environnement["docuseal"].soumissions[int(circuit.soumission)]
    assert circuit.statut == "envoye" and soumission["order"] == "preserved" and soumission["expire_at"].startswith("2026-11-22")
    assert [s.role for s in circuit.signataires.order_by("ordre")] == ["usager", "elu"]
    assert environnement["docuseal"].jeton == "jeton-api-test"
    assert any("Document à signer" in m.subject for m in mail.outbox)
    document.refresh_from_db()
    assert document.statut == "en_signature"
    assert "convention en cours de signature" in conditions.conditions_manquantes(dossier.reservations.first())


@pytest.mark.urls("config.urls_portail")
@override_settings(CANAL="portail")
def test_sig02_webhook_falsifie_sans_effet(dossier, environnement, django_capture_on_commit_callbacks, client_api):
    document, circuit = _envoyer(dossier, django_capture_on_commit_callbacks)
    with django_capture_on_commit_callbacks(execute=True):
        faux = client_api.post(
            "/api/portail/webhooks/docuseal",
            {"event_type": "submission.completed", "data": {"id": circuit.soumission, "status": "completed"}},
            format="json",
        )
    assert faux.status_code == 202
    inconnu = client_api.post(
        "/api/portail/webhooks/docuseal", {"event_type": "submission.completed", "data": {"id": 999999}}, format="json"
    )
    assert inconnu.json() == {"pris_en_compte": False}
    document.refresh_from_db()
    assert document.statut == "en_signature"


def test_sig03_signature_complete_pdf_signe_preuve_et_purge(dossier, environnement, django_capture_on_commit_callbacks):
    document, circuit = _envoyer(dossier, django_capture_on_commit_callbacks)
    faux = environnement["docuseal"]
    faux.signer(int(circuit.soumission), 0)
    faux.signer(int(circuit.soumission), 1)
    with django_capture_on_commit_callbacks(execute=True):
        services.traiter_webhook({"event_type": "submission.completed", "data": {"id": int(circuit.soumission)}})
    document.refresh_from_db()
    circuit.refresh_from_db()
    assert document.statut == "signe" and document.fichier_signe is not None and document.preuve is not None
    assert circuit.statut == "signe" and circuit.purge_le is not None and int(circuit.soumission) in faux.archivees
    assert not [c for c in conditions.conditions_manquantes(dossier.reservations.first()) if "convention" in c]


def test_sig04_relance_avant_expiration_puis_expiration(dossier, environnement, django_capture_on_commit_callbacks):
    document, circuit = _envoyer(dossier, django_capture_on_commit_callbacks)
    with freeze_time("2026-11-15 10:00"):
        assert services.relancer_signatures() == 0
    with freeze_time("2026-11-19 11:00"), django_capture_on_commit_callbacks(execute=True):
        assert services.relancer_signatures() == 1
        assert services.relancer_signatures() == 0
    assert environnement["docuseal"].relances and any("Rappel" in m.subject for m in mail.outbox)
    environnement["docuseal"].expirer(int(circuit.soumission))
    services.synchroniser(circuit)
    circuit.refresh_from_db()
    document.refresh_from_db()
    assert circuit.statut == "expire" and document.statut == "genere"


def test_sig04_annulation_par_l_agent(dossier, environnement, django_capture_on_commit_callbacks):
    _document, circuit = _envoyer(dossier, django_capture_on_commit_callbacks)
    with django_capture_on_commit_callbacks(execute=True):
        services.annuler_circuit(circuit, acteur=agent("gestionnaire"), motif="Erreur de créneau")
    circuit.refresh_from_db()
    assert circuit.statut == "annule" and int(circuit.soumission) in environnement["docuseal"].archivees
    with pytest.raises(ErreurMetier):
        services.annuler_circuit(circuit, acteur=agent("accueil"), motif="x")


def test_sig05_circuit_manuel_scan_depose(dossier, client_agent, django_capture_on_commit_callbacks):
    gestionnaire = agent("gestionnaire")
    document = services.generer("convention", dossier, acteur=gestionnaire)
    with django_capture_on_commit_callbacks(execute=True):
        circuit = services.envoyer_en_signature(document, acteur=gestionnaire, mode="manuel")
    assert circuit.statut == "envoye"
    client = client_agent(gestionnaire)
    reponse = client.post(
        f"/api/gestion/documents/documents/{document.pk}/scan-signe",
        {"fichier": SimpleUploadedFile("scan.pdf", PDF)},
        format="multipart",
    )
    assert reponse.status_code == 200 and reponse.json()["statut"] == "signe_manuellement"
    assert CircuitSignature.objects.get(pk=circuit.pk).statut == "signe"


@pytest.mark.urls("config.urls_portail")
@override_settings(CANAL="portail")
def test_por10_lien_de_signature_pour_le_signataire_attendu(dossier, environnement, django_capture_on_commit_callbacks):
    from apps.portail.tests.outils import client_contact, compte_actif

    compte = compte_actif(dossier.usager)
    document, circuit = _envoyer(dossier, django_capture_on_commit_callbacks)
    client = client_contact(compte)
    liste = client.get(f"/api/portail/dossiers/{dossier.pk}/documents").json()
    assert liste[0]["a_signer_en_ligne"] is True
    lien = client.get(f"/api/portail/dossiers/{dossier.pk}/documents/{document.pk}/signature").json()["lien"]
    assert lien.startswith("https://signature.chatillon.test/s/")
    fichier = client.get(f"/api/portail/dossiers/{dossier.pk}/documents/{document.pk}/fichier")
    assert fichier.status_code == 200
    intrus = client_contact(compte_actif())
    assert intrus.get(f"/api/portail/dossiers/{dossier.pk}/documents/{document.pk}/fichier").status_code == 404
    environnement["docuseal"].signer(int(circuit.soumission), 0)
    circuit.signataires.filter(ordre=0).update(statut="signe")
    assert client.get(f"/api/portail/dossiers/{dossier.pk}/documents/{document.pk}/signature").status_code == 409


def test_doc03_contextes_sans_objet_orm(dossier):
    contexte = construire("convention", dossier)

    def simple(valeur: object) -> bool:
        if isinstance(valeur, dict):
            return all(simple(v) for v in valeur.values())
        if isinstance(valeur, list):
            return all(simple(v) for v in valeur)
        return valeur is None or isinstance(valeur, (str, int, float, bool))

    assert simple(contexte)
