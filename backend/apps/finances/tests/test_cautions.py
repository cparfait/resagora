"""Lot 3 — cautions : exigée à la validation (CAU-01), reçue (CAU-02), restituée après l'état des lieux de sortie
(CAU-03, RG-11), retenue motivée avec photos (CAU-04) et double validation au-delà du seuil (CAU-05), état exportable
(CAU-06), alertes de délai (CAU-07), journal immuable (RG-13)."""

from __future__ import annotations

from datetime import date

import pytest
from django.core import mail
from django.core.files.uploadedfile import SimpleUploadedFile
from django.db import DatabaseError, transaction
from freezegun import freeze_time

from apps.documents import services as documents
from apps.finances import cautions
from apps.finances.models import Caution, MouvementCaution
from apps.noyau import fichiers
from apps.noyau.exceptions import AccesRefuse, ErreurMetier, ErreurValidation
from apps.reservations import conditions
from apps.reservations import services as reservations
from tests.fabriques import EspaceFabrique, SiteFabrique, agent

from .outils import PDF, grille_votee, location


@pytest.fixture
def seuil_100_euros():
    from apps.noyau.models import Parametre
    from apps.noyau.parametres import invalider

    Parametre.objects.update_or_create(cle="caution.seuil_double_validation_centimes", defaults={"valeur": 10000})
    invalider()


pytestmark = pytest.mark.django_db
JPEG = b"\xff\xd8\xff\xe0" + b"photo-degats" * 20


@pytest.fixture(autouse=True)
def environnement(monkeypatch, modeles_documents):
    monkeypatch.setattr(documents, "convertir_en_pdfa", lambda nom, docx, transport=None: PDF)
    monkeypatch.setattr(fichiers, "analyser_clamav", lambda contenu: None)
    with freeze_time("2026-11-02 10:00"):
        yield


@pytest.fixture
def espace():
    espace = EspaceFabrique(nom="Salle des fêtes")
    grille_votee(espace)
    return espace


@pytest.fixture
def caution(espace):
    reservation = location(espace=espace, valider=False)
    reservations.valider(reservation, acteur=agent("gestionnaire"))
    return Caution.objects.get(reservation=reservation)


def _photo():
    return fichiers.enregistrer("degats.jpg", JPEG, types_autorises=("image/jpeg",), depose_par="test")


def test_cau01_caution_exigee_a_la_validation_et_condition_de_confirmation(caution):
    assert caution.montant == 30000 and caution.statut == "attendue"
    assert "déposer la caution de 300,00 €" in " ".join(conditions.conditions_manquantes(caution.reservation))
    assert MouvementCaution.objects.filter(caution=caution, action="attendue").count() == 1


def test_cau02_reception_par_la_regie_seulement(caution):
    with pytest.raises(AccesRefuse):
        cautions.recevoir(caution, acteur=agent("gestionnaire"), mode="cheque", reference="Chèque 0012345")
    with pytest.raises(ErreurValidation):
        cautions.recevoir(caution, acteur=agent("regisseur"), mode="cheque", reference="")
    caution = cautions.recevoir(caution, acteur=agent("regisseur"), mode="cheque", reference="Chèque 0012345")
    assert caution.statut == "recue" and caution.recue_le == date(2026, 11, 2)
    assert not [c for c in conditions.conditions_manquantes(caution.reservation) if "caution" in c]


def test_rg11_restitution_seulement_apres_etat_des_lieux_de_sortie_conforme(caution, django_capture_on_commit_callbacks):
    regisseur = agent("regisseur")
    caution = cautions.recevoir(caution, acteur=regisseur, mode="cheque", reference="Chèque 0012345")
    with pytest.raises(ErreurMetier) as refus:
        cautions.restituer(caution, acteur=regisseur)
    assert refus.value.code == "etat_des_lieux_requis"
    seance = caution.reservation.occurrences.get()
    cautions.constater_sortie(seance, acteur=regisseur, constat="conforme")
    caution.refresh_from_db()
    assert caution.statut == "restituable"
    with django_capture_on_commit_callbacks(execute=True):
        caution = cautions.restituer(caution, acteur=regisseur)
    assert caution.statut == "restituee" and any("Restitution de votre caution" in m.subject for m in mail.outbox)
    with pytest.raises(ErreurMetier):
        cautions.restituer(caution, acteur=regisseur)


def test_cau04_retenue_motivee_avec_photos_sous_le_seuil(caution):
    regisseur, gestionnaire = agent("regisseur"), agent("gestionnaire")
    caution = cautions.recevoir(caution, acteur=regisseur, mode="consignation", reference="Consignation 77")
    seance = caution.reservation.occurrences.get()
    with pytest.raises(ErreurMetier):
        cautions.proposer_retenue(caution, acteur=gestionnaire, montant=5000, motif="Vitre brisée côté scène", photos=[_photo()])
    with pytest.raises(ErreurValidation):
        cautions.constater_sortie(seance, acteur=regisseur, constat="degats", observations="")
    cautions.constater_sortie(seance, acteur=regisseur, constat="degats", observations="Vitre brisée côté scène")
    with pytest.raises(ErreurValidation):
        cautions.proposer_retenue(caution, acteur=gestionnaire, montant=5000, motif="Vitre brisée côté scène", photos=[])
    with pytest.raises(ErreurValidation):
        cautions.proposer_retenue(caution, acteur=gestionnaire, montant=40000, motif="Vitre brisée côté scène", photos=[_photo()])
    caution = cautions.proposer_retenue(
        caution, acteur=gestionnaire, montant=5000, motif="Vitre brisée côté scène", photos=[_photo()]
    )
    assert caution.statut == "retenue_partielle" and caution.montant_retenu == 5000
    from apps.communication.models import Notification

    assert Notification.objects.filter(sujet__startswith="Retenue sur votre caution", usager=caution.usager).exists()


def test_cau05_double_validation_au_dela_du_seuil_par_un_autre_agent(caution, seuil_100_euros):
    regisseur, gestionnaire = agent("regisseur"), agent("gestionnaire")
    caution = cautions.recevoir(caution, acteur=regisseur, mode="cheque", reference="Chèque 0012346")
    cautions.constater_sortie(
        caution.reservation.occurrences.get(), acteur=regisseur, constat="degats", observations="Parquet rayé sur 4 m²"
    )
    caution = cautions.proposer_retenue(
        caution, acteur=gestionnaire, montant=30000, motif="Ponçage et vitrification du parquet", photos=[_photo()]
    )
    assert caution.statut == "retenue_a_valider"
    with pytest.raises(AccesRefuse):
        cautions.valider_retenue(caution, acteur=regisseur, accepter=True)
    financier = agent("financier")
    caution = cautions.valider_retenue(caution, acteur=financier, accepter=True)
    assert caution.statut == "retenue_totale"
    caution = cautions.encaisser_retenue(caution, acteur=regisseur, reference="Titre T-2026-000777")
    assert caution.statut == "encaissee"
    actions = list(caution.mouvements.order_by("le").values_list("action", flat=True))
    assert actions == ["attendue", "recue", "retenue_proposee", "retenue", "encaissee"]
    with pytest.raises(DatabaseError), transaction.atomic():
        MouvementCaution.objects.filter(caution=caution).update(montant=1)


def test_cau05_l_agent_qui_propose_ne_valide_pas(caution, seuil_100_euros):
    from apps.habilitations.models import Habilitation, Role
    from tests.fabriques import ville_entiere

    polyvalent = agent("gestionnaire")
    Habilitation.objects.create(utilisateur=polyvalent, role=Role.objects.get(code="financier"), perimetre=ville_entiere())
    caution = cautions.recevoir(caution, acteur=agent("regisseur"), mode="cheque", reference="Chèque 0012347")
    cautions.constater_sortie(
        caution.reservation.occurrences.get(), acteur=agent("regisseur"), constat="degats", observations="Porte enfoncée"
    )
    caution = cautions.proposer_retenue(
        caution, acteur=polyvalent, montant=25000, motif="Remplacement de la porte coupe-feu", photos=[_photo()]
    )
    with pytest.raises(ErreurMetier) as refus:
        cautions.valider_retenue(caution, acteur=polyvalent, accepter=True)
    assert refus.value.code == "double_controle"


def test_cau06_cau07_etat_exportable_et_alertes(caution, client_agent):
    regisseur = client_agent(agent("regisseur"))
    reponse = regisseur.post(
        f"/api/gestion/finances/cautions/{caution.pk}/recevoir", {"mode": "cheque", "reference": "Chèque 0099"}, format="json"
    )
    assert reponse.status_code == 200 and reponse.json()["statut"] == "recue"
    export = regisseur.get("/api/gestion/finances/cautions/export")
    contenu = export.content.decode("utf-8-sig")
    assert export.status_code == 200 and "300,00 €" in contenu and caution.dossier.numero in contenu
    assert regisseur.get("/api/gestion/finances/cautions/alertes").json() == []
    with freeze_time("2027-01-20 10:00"):
        alertes = client_agent(agent("regisseur")).get("/api/gestion/finances/cautions/alertes").json()
    assert [a["id"] for a in alertes] == [caution.pk]
    assert client_agent(agent("accueil")).get("/api/gestion/finances/cautions").status_code == 403
    hors = client_agent(agent("regisseur", SiteFabrique())).get(f"/api/gestion/finances/cautions/{caution.pk}")
    assert hors.status_code == 404


def test_cau04_retenue_par_l_api_avec_photo(caution, client_agent):
    client_regie = client_agent(agent("regisseur"))
    client_regie.post(
        f"/api/gestion/finances/cautions/{caution.pk}/recevoir", {"mode": "cheque", "reference": "Chèque 1"}, format="json"
    )
    seance = caution.reservation.occurrences.get()
    etat = client_regie.post(
        "/api/gestion/finances/etats-des-lieux",
        {
            "occurrence": seance.pk,
            "constat": "degats",
            "observations": "Tache de peinture sur le mur",
            "photos": [SimpleUploadedFile("mur.jpg", JPEG)],
        },
        format="multipart",
    )
    assert etat.status_code == 201
    retenue = client_agent(agent("gestionnaire")).post(
        f"/api/gestion/finances/cautions/{caution.pk}/retenue",
        {"montant": 4000, "motif": "Reprise de peinture du mur nord", "photos": [SimpleUploadedFile("mur.jpg", JPEG)]},
        format="multipart",
    )
    assert retenue.status_code == 200 and retenue.json()["statut"] == "retenue_partielle"
    assert client_agent(agent("accueil")).post(f"/api/gestion/finances/cautions/{caution.pk}/restituer").status_code == 403


def test_cau03_pas_de_restitution_proposee_avant_l_etat_des_lieux_de_sortie(caution, client_agent):
    regie = client_agent(agent("regisseur"))
    regie.post(
        f"/api/gestion/finances/cautions/{caution.pk}/recevoir", {"mode": "cheque", "reference": "Chèque 7"}, format="json"
    )
    refus = regie.post(f"/api/gestion/finances/cautions/{caution.pk}/restituer")
    assert refus.status_code == 409 and refus.json()["code"] == "etat_des_lieux_requis"
    assert regie.get(f"/api/gestion/finances/cautions/{caution.pk}").json()["etat_sortie"] is None


def test_cau07_alerte_quand_le_delai_de_restitution_est_depasse(caution):
    cautions.recevoir(caution, acteur=agent("regisseur"), mode="cheque", reference="Chèque 8")
    assert not cautions.en_alerte(date(2026, 12, 20)).exists()
    assert list(cautions.en_alerte(date(2027, 1, 20))) == [caution]
