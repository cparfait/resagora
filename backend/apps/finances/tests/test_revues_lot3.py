"""Corrections des revues du lot 3 : facturation à partir du devis (RG-04, TAR-04, TAR-09), avoirs (TAR-05), Ciril
(TAR-06, TAR-13), annulations (RG-08), cautions (CAU-02, CAU-03, CAU-05, RG-11), tarifs (RG-05), sécurité (formules,
périmètre, immuabilité, coordonnées bancaires, rôles)."""

from __future__ import annotations

import csv
import io
from datetime import date, time

import pytest
from django.core.files.uploadedfile import SimpleUploadedFile
from django.db import DatabaseError, transaction
from freezegun import freeze_time
from openpyxl import load_workbook

from apps.documents import services as documents
from apps.finances import cautions, facturation, titres
from apps.finances.ciril import encaissements
from apps.finances.models import AFacturer, Caution, GrilleTarifaire, LigneComptable, PieceComptable, Tarif
from apps.noyau import fichiers
from apps.noyau.exceptions import AccesRefuse, ErreurMetier
from apps.noyau.models import Parametre
from apps.noyau.parametres import invalider, valider_valeur
from apps.reservations import services as reservations
from apps.reservations.models import Occurrence
from tests.fabriques import EspaceFabrique, SiteFabrique, agent, usager_avec_contact

from .outils import PDF, grille_votee, location

pytestmark = pytest.mark.django_db


@pytest.fixture(autouse=True)
def environnement(monkeypatch, modeles_documents):
    monkeypatch.setattr(documents, "convertir_en_pdfa", lambda nom, docx, transport=None: PDF)
    monkeypatch.setattr(fichiers, "analyser_clamav", lambda contenu: None)
    with freeze_time("2026-11-02 10:00") as horloge:
        yield horloge


@pytest.fixture
def espace():
    espace = EspaceFabrique(nom="Salle des fêtes")
    grille_votee(espace)
    return espace


def _ajouter(dossier, espace, jour):
    """Séance supplémentaire (14 h – 18 h) dans le même dossier, validée."""
    from apps.reservations.tests.outils import valider_systeme

    return valider_systeme(
        reservations.ajouter_reservation(
            dossier, acteur="système", espace=espace, date_debut=jour, date_fin=jour, heure_debut=time(14), heure_fin=time(18)
        )
    )


def _serie(espace, usager=None):
    """Location de deux séances (9 et 16 décembre) dans le même dossier, validées."""
    premiere = location(espace=espace, usager=usager)
    _ajouter(premiere.dossier, espace, date(2026, 12, 16))
    return premiere.dossier


# --- Facturation à partir du devis -------------------------------------------------------------------------


def test_tar09_acompte_deduit_une_seule_fois_sur_factures_partielles(espace):
    dossier = _serie(espace)
    g = agent("gestionnaire")
    devis = facturation.etablir_devis(dossier, acteur=g)
    facturation.accepter_devis(devis, acteur=g)
    acompte = facturation.facturer_acompte(dossier, acteur=g)
    seances = list(Occurrence.objects.filter(reservation__dossier=dossier).order_by("debut"))
    premiere = facturation.facturer(dossier, acteur=g, occurrences=[seances[0]])
    seconde = facturation.facturer(dossier, acteur=g, occurrences=[seances[1]])
    assert premiere.acompte_deduit == acompte.total_du and seconde.acompte_deduit == 0


def test_rg04_seance_annulee_apres_acceptation_non_facturee_et_ajout_exige_un_nouveau_devis(espace):
    dossier = _serie(espace)
    g = agent("gestionnaire")
    devis = facturation.etablir_devis(dossier, acteur=g)
    facturation.accepter_devis(devis, acteur=g)
    seance = Occurrence.objects.filter(reservation__dossier=dossier).order_by("-debut").first()
    reservations.annuler_occurrence(seance, acteur=g, motif="Fermeture de la salle")
    facture = facturation.facturer(dossier, acteur=g)
    assert facture.lignes.filter(occurrence=seance).count() == 0 and facture.total_du == devis.total_du // 2
    _ajouter(dossier, espace, date(2026, 12, 23))
    with pytest.raises(ErreurMetier) as refus:
        facturation.facturer(dossier, acteur=g)
    assert refus.value.code == "devis_perime"


def test_rg04_prestations_du_devis_facturees_une_seule_fois(espace):
    dossier = _serie(espace)
    g = agent("gestionnaire")
    devis = facturation.etablir_devis(dossier, acteur=g, prestations=[{"code": "menage"}])
    facturation.accepter_devis(devis, acteur=g)
    seances = list(Occurrence.objects.filter(reservation__dossier=dossier).order_by("debut"))
    premiere = facturation.facturer(dossier, acteur=g, occurrences=[seances[0]])
    seconde = facturation.facturer(dossier, acteur=g)
    menages = LigneComptable.objects.filter(piece__in=[premiere, seconde], nature="prestation").count()
    assert menages == 1


def test_tar04_seul_le_dernier_devis_peut_etre_accepte(espace):
    dossier = location(espace=espace).dossier
    g = agent("gestionnaire")
    ancien = facturation.etablir_devis(dossier, acteur=g)
    nouveau = facturation.etablir_devis(dossier, acteur=g, prestations=[{"code": "menage"}])
    ancien.refresh_from_db()
    assert ancien.statut == "remplace"
    with pytest.raises(ErreurMetier):
        facturation.accepter_devis(ancien, acteur=g)
    facturation.accepter_devis(nouveau, acteur=g)
    with freeze_time("2027-01-15"):
        expire = facturation.etablir_devis(dossier, acteur=g)
    with pytest.raises(ErreurMetier) as refus, freeze_time("2027-03-01"):
        facturation.accepter_devis(expire, acteur=g)
    assert refus.value.code == "devis_expire"
    expire.refresh_from_db()
    assert expire.statut == "expire"


# --- Avoirs -------------------------------------------------------------------------------------------


def test_tar05_avoir_partiel_reduit_le_reste_du_et_une_ligne_n_est_creditee_qu_une_fois(espace):
    dossier = _serie(espace)
    g, f = agent("gestionnaire"), agent("financier")
    facture = facturation.facturer(dossier, acteur=g)
    premiere_ligne = facture.lignes.order_by("rang").first()
    facturation.emettre_avoir(facture, acteur=f, motif="Séance non réalisée", lignes=[premiere_ligne.pk])
    facture.refresh_from_db()
    assert facture.reste_du == facture.total_du - premiere_ligne.montant_du and facture.statut == "a_titrer"
    with pytest.raises(ErreurMetier) as refus:
        facturation.emettre_avoir(facture, acteur=f, motif="Doublon", lignes=[premiere_ligne.pk])
    assert refus.value.code == "ligne_deja_creditee"
    facturation.enregistrer_encaissement(
        facture, montant=facture.reste_du, jour=date(2026, 11, 20), reference="VIR 1", origine="pointage"
    )
    facture.refresh_from_db()
    assert facture.statut == "solde"


def test_tar05_avoir_total_ne_credite_que_le_montant_titre(espace):
    dossier = location(espace=espace).dossier
    g, f = agent("gestionnaire"), agent("financier")
    facturation.accepter_devis(facturation.etablir_devis(dossier, acteur=g), acteur=g)
    acompte = facturation.facturer_acompte(dossier, acteur=g)
    facture = facturation.facturer(dossier, acteur=g)
    avoir = facturation.emettre_avoir(facture, acteur=f, motif="Location annulée par la Ville")
    assert avoir.total_du == -(facture.total_du - acompte.total_du)


def test_tar06_avoir_d_une_facture_jamais_titree_et_annulee_non_exporte(espace):
    facture = facturation.facturer(location(espace=espace).dossier, acteur=agent("gestionnaire"))
    facturation.emettre_avoir(facture, acteur=agent("financier"), motif="Erreur de dossier")
    assert list(titres.a_titrer()) == []


def test_tar06_lot_rejete_par_ciril_annule_puis_reexporte(espace):
    facture = facturation.facturer(location(espace=espace).dossier, acteur=agent("gestionnaire"))
    financier = agent("financier")
    lot = titres.exporter([facture], acteur=financier)
    assert list(titres.a_titrer()) == []
    titres.annuler_lot(lot, acteur=financier, motif="Format refusé par Ciril")
    assert [p.pk for p in titres.a_titrer()] == [facture.pk]
    nouveau = titres.exporter(list(titres.a_titrer()), acteur=financier, format_export="xlsx")
    lot.refresh_from_db()
    assert lot.numeros == [facture.numero] and nouveau.numeros == [facture.numero]


def test_tar06_numero_de_titre_reporte_une_seule_fois(espace):
    facture = facturation.facturer(location(espace=espace).dossier, acteur=agent("gestionnaire"))
    titres.reporter_titre(facture, acteur=agent("financier"), titre="T-1")
    with pytest.raises(ErreurMetier):
        titres.reporter_titre(facture, acteur=agent("financier"), titre="T-2")


# --- Annulations (RG-08) -----------------------------------------------------------------------------------


def test_rg08_bareme_coherent_avec_le_delai_tardif():
    assert valider_valeur("annulation.bareme", [{"heures_avant": 96, "taux": 2500}, {"heures_avant": 0, "taux": 10000}])
    assert valider_valeur("annulation.bareme", [{"heures_avant": 24, "taux": 5000}, {"heures_avant": 0, "taux": 10000}]) is None
    assert valider_valeur("annulation.delai_tardif_heures", 12)


def test_rg08_seance_facturee_puis_annulee_tardivement_avoir_et_frais_au_prix_du_devis(espace, environnement):
    dossier = location(espace=espace, jour=date(2026, 11, 5), debut="09:00", fin="11:00").dossier
    g = agent("gestionnaire")
    devis = facturation.etablir_devis(dossier, acteur=g)
    facturation.accepter_devis(devis, acteur=g)
    Tarif.objects.update(prix_centimes=99900)
    facture = facturation.facturer(dossier, acteur=g)
    seance = Occurrence.objects.get(reservation__dossier=dossier)
    contact = dossier.usager.rattachements.first().contact
    reservations.annuler_occurrence(seance, acteur=contact, motif="Imprévu", par_usager=True)
    facture.refresh_from_db()
    assert facture.statut == "annulee" and PieceComptable.objects.filter(nature="avoir", origine=facture).exists()
    frais = AFacturer.objects.get(occurrence=seance)
    assert frais.montant_du == devis.total_du // 2  # 50 % du prix figé du devis, pas de la grille modifiée


# --- Cautions --------------------------------------------------------------------------------------------


@pytest.fixture
def caution(espace):
    reservation = location(espace=espace, valider=False)
    reservations.valider(reservation, acteur=agent("gestionnaire"))
    return Caution.objects.get(reservation=reservation)


def test_rg11_etat_des_lieux_de_sortie_refuse_avant_la_fin_de_la_seance(caution):
    with pytest.raises(ErreurMetier) as refus:
        cautions.constater_sortie(caution.reservation.occurrences.get(), acteur=agent("regisseur"), constat="conforme")
    assert refus.value.code == "seance_non_terminee"


def test_cau02_caution_recue_apres_un_etat_des_lieux_conforme_devient_restituable(caution, environnement):
    environnement.move_to("2026-12-09 19:00")
    regie = agent("regisseur")
    cautions.constater_sortie(caution.reservation.occurrences.get(), acteur=regie, constat="conforme")
    caution = cautions.recevoir(caution, acteur=regie, mode="cheque", reference="Chèque tardif")
    assert caution.statut == "restituable"
    assert cautions.restituer(caution, acteur=regie).statut == "restituee"


def test_cau02_retenue_partielle_puis_solde_restitue_puis_encaissement(caution, environnement):
    regie = agent("regisseur")
    cautions.recevoir(caution, acteur=regie, mode="cheque", reference="Chèque 1")
    environnement.move_to("2026-12-09 19:00")
    cautions.constater_sortie(
        caution.reservation.occurrences.get(), acteur=regie, constat="degats", observations="Rayure du parquet"
    )
    photo = fichiers.enregistrer("p.jpg", b"\xff\xd8\xff\xe0photo", types_autorises=("image/jpeg",), depose_par="test")
    caution = cautions.proposer_retenue(
        caution, acteur=agent("gestionnaire"), montant=8000, motif="Ponçage d'une lame de parquet", photos=[photo]
    )
    assert caution.statut == "retenue_partielle"
    assert list(cautions.en_alerte(date(2027, 2, 1))) == [caution]
    with pytest.raises(ErreurMetier):
        cautions.encaisser_retenue(caution, acteur=regie, reference="Titre 9")
    caution = cautions.restituer(caution, acteur=regie)
    assert caution.statut == "solde_restitue" and caution.mouvements.filter(action="solde_restitue", montant=22000).exists()
    assert cautions.encaisser_retenue(caution, acteur=regie, reference="Titre 9").statut == "encaissee"


def test_cau05_retenue_en_attente_de_validation_ne_se_contourne_pas(caution, environnement, settings):
    Parametre.objects.update_or_create(cle="caution.seuil_double_validation_centimes", defaults={"valeur": 10000})
    invalider()
    regie, gestionnaire, financier = agent("regisseur"), agent("gestionnaire"), agent("financier")
    cautions.recevoir(caution, acteur=regie, mode="cheque", reference="Chèque 2")
    environnement.move_to("2026-12-09 19:00")
    cautions.constater_sortie(caution.reservation.occurrences.get(), acteur=regie, constat="degats", observations="Porte abîmée")
    photo = fichiers.enregistrer("p.jpg", b"\xff\xd8\xff\xe0photo", types_autorises=("image/jpeg",), depose_par="test")
    caution = cautions.proposer_retenue(
        caution, acteur=gestionnaire, montant=30000, motif="Remplacement de la porte", photos=[photo]
    )
    assert caution.statut == "retenue_a_valider"
    with pytest.raises(ErreurMetier):
        cautions.proposer_retenue(caution, acteur=gestionnaire, montant=5000, motif="Petite retenue à la place", photos=[photo])
    caution = cautions.valider_retenue(caution, acteur=financier, accepter=False, commentaire="Devis de réparation à fournir")
    caution = cautions.proposer_retenue(
        caution, acteur=gestionnaire, montant=5000, motif="Retenue réduite après refus", photos=[photo]
    )
    assert caution.statut == "retenue_a_valider", "après un refus, toute proposition repasse par le second agent"


# --- Tarifs, grilles (RG-05, RG-04) -------------------------------------------------------------------------


def test_rg05_tarif_a_zero_refuse(client_agent, espace):
    grille = GrilleTarifaire.objects.create(nom="Brouillon", debut=date(2027, 1, 1))
    reponse = client_agent(agent("financier")).post(
        "/api/gestion/finances/tarifs",
        {"grille": grille.pk, "espace": espace.pk, "categorie": "ecole", "unite": "heure", "prix_centimes": 0},
        format="json",
    )
    assert reponse.status_code == 400
    with pytest.raises(DatabaseError), transaction.atomic():
        Tarif.objects.create(grille=grille, espace=espace, categorie="ecole", prix_centimes=0)


def test_rg04_grille_archivee_seulement_apres_sa_periode_et_toujours_appliquee(client_agent, espace):
    grille = GrilleTarifaire.objects.get(statut="votee")
    financier = client_agent(agent("financier"))
    assert financier.post(f"/api/gestion/finances/grilles/{grille.pk}/archiver").status_code == 409
    GrilleTarifaire.objects.filter(pk=grille.pk).update(fin=date(2026, 10, 31))
    assert financier.post(f"/api/gestion/finances/grilles/{grille.pk}/archiver").json()["statut"] == "archivee"
    from apps.finances.tarification import grille_en_vigueur

    assert grille_en_vigueur(date(2026, 6, 1)).pk == grille.pk


# --- Encaissements (TAR-13) ----------------------------------------------------------------------------------


def test_tar13_pointage_puis_import_du_meme_reglement_signale_a_verifier(espace):
    facture = facturation.facturer(location(espace=espace).dossier, acteur=agent("gestionnaire"))
    regie = agent("regisseur")
    facturation.pointer(facture, acteur=regie, montant=5000, jour=date(2026, 11, 10), reference="CB régie")
    sortie = io.StringIO()
    ecrivain = csv.writer(sortie, delimiter=";")
    ecrivain.writerow(["N° titre", "Référence", "Montant encaissé", "Date encaissement", "Référence paiement"])
    ecrivain.writerow(["", facture.numero, "50,00", "12/11/2026", "VIR"])
    ecrivain.writerow(["", facture.numero, "-20,00", "13/11/2026", "REJET"])
    lot = encaissements.importer("etat.csv", sortie.getvalue().encode("cp1252"), acteur=regie)
    assert lot.rapprochees == 0 and len(lot.rejets) == 2
    assert "à vérifier" in lot.rejets[0]["motif"] and "négatif" in lot.rejets[1]["motif"]


# --- Sécurité ------------------------------------------------------------------------------------------------


@pytest.mark.parametrize("nom", ['=HYPERLINK("https://x.invalid";"RIB")', "+cmd", "@SUM(A1)", "-1+2"])
def test_sec_injection_de_formules_neutralisee_dans_les_exports(espace, nom):
    usager = usager_avec_contact(type="particulier", nom=nom, commune="Châtillon")
    facture = facturation.facturer(location(espace=espace, usager=usager).dossier, acteur=agent("gestionnaire"))
    lot_csv = titres.exporter([facture], acteur=agent("financier"), format_export="csv")
    lignes = list(csv.reader(io.StringIO(fichiers.lire(lot_csv.fichier).decode("cp1252")), delimiter=";"))
    debiteur = lignes[1][lignes[0].index("Débiteur")]
    assert debiteur.startswith("'") and lignes[1][lignes[0].index("Montant")] == "160,00"
    titres.annuler_lot(lot_csv, acteur=agent("financier"), motif="Essai de format")
    lot_xlsx = titres.exporter([facture], acteur=agent("financier"), format_export="xlsx")
    feuille = load_workbook(io.BytesIO(fichiers.lire(lot_xlsx.fichier))).active
    assert all(c.data_type != "f" for rangee in feuille.iter_rows() for c in rangee)
    assert cautions.etat_csv(Caution.objects.none()).decode("utf-8-sig").startswith("Dossier")


def test_rg14_export_des_titres_et_import_reserves_au_perimetre_ville_entiere(espace, client_agent):
    facturation.facturer(location(espace=espace).dossier, acteur=agent("gestionnaire"))
    site = espace.batiment.site
    mono = client_agent(agent("financier", site))
    assert mono.get("/api/gestion/finances/lots-titres/a-titrer").status_code == 403
    assert mono.post("/api/gestion/finances/lots-titres", {}, format="json").status_code == 403
    regie_mono = client_agent(agent("regisseur", SiteFabrique()))
    contenu = SimpleUploadedFile("etat.csv", "N° titre;Référence;Montant encaissé;Date encaissement\n".encode("cp1252"))
    assert (
        regie_mono.post("/api/gestion/finances/imports-encaissements", {"fichier": contenu}, format="multipart").status_code
        == 403
    )
    with pytest.raises(AccesRefuse):
        titres.exporter(list(titres.a_titrer()), acteur=agent("financier", site))


def test_rg13_lignes_et_statuts_des_pieces_emises_proteges_en_base(espace):
    facture = facturation.facturer(location(espace=espace).dossier, acteur=agent("gestionnaire"))
    brouillon = PieceComptable.objects.create(nature="facture", dossier=facture.dossier, usager=facture.usager, objet="x")
    with pytest.raises(DatabaseError), transaction.atomic():
        LigneComptable.objects.filter(piece=facture).update(piece=brouillon)
    with pytest.raises(DatabaseError), transaction.atomic():
        LigneComptable.objects.create(
            piece=facture,
            rang=9,
            libelle="Ajout",
            nature="frais",
            quantite=1,
            unite="forfait",
            prix_unitaire=1,
            montant_reference=1,
            montant_du=1,
        )
    with pytest.raises(DatabaseError), transaction.atomic():
        PieceComptable.objects.filter(pk=facture.pk).update(statut="brouillon")
    with pytest.raises(DatabaseError), transaction.atomic():
        PieceComptable.objects.filter(pk=facture.pk).update(document=None)
    PieceComptable.objects.filter(pk=facture.pk).update(montant_regle=1000)
    with pytest.raises(DatabaseError), transaction.atomic():
        PieceComptable.objects.filter(pk=facture.pk).update(montant_regle=0)


def test_tar12_iban_fige_et_coordonnees_reservees_a_l_ordonnateur(espace, client_agent):
    facture = facturation.facturer(location(espace=espace).dossier, acteur=agent("gestionnaire"))
    iban_emission = facture.reglement["iban"]
    administrateur = client_agent(agent("administrateur"))
    nouvel_iban = "FR7630001007941234567890185"
    assert (
        administrateur.patch("/api/gestion/parametres", {"valeurs": {"comptable.iban": nouvel_iban}}, format="json").status_code
        == 403
    )
    financier = client_agent(agent("financier"))
    assert (
        financier.patch("/api/gestion/parametres", {"valeurs": {"comptable.iban": "FR00 1234"}}, format="json").status_code == 400
    )
    assert (
        financier.patch("/api/gestion/parametres", {"valeurs": {"comptable.iban": nouvel_iban}}, format="json").status_code == 200
    )
    facture.refresh_from_db()
    assert facture.reglement["iban"] == iban_emission
    from apps.communication.models import Notification

    alerte = Notification.objects.get(modele__code="parametre_financier_modifie")
    assert "comptable.iban" in alerte.sujet


def test_tar08_tache_quotidienne_expire_les_devis_non_acceptes(espace):
    from apps.finances.tasks import expirer_devis

    devis = facturation.etablir_devis(location(espace=espace).dossier, acteur=agent("gestionnaire"))
    assert expirer_devis() == 0
    with freeze_time("2027-06-01"):
        assert expirer_devis() == 1
    devis.refresh_from_db()
    assert devis.statut == "expire"


def test_adr0005_un_role_ne_reunit_pas_des_actions_incompatibles(client_agent):
    from apps.habilitations.models import Role

    administrateur = client_agent(agent("administrateur"))
    role = Role.objects.get(code="administrateur")
    reponse = administrateur.patch(
        f"/api/gestion/admin/roles/{role.pk}", {"actions": [*role.actions, "encaisser"]}, format="json"
    )
    assert reponse.status_code == 400
    gestionnaire = Role.objects.get(code="gestionnaire")
    reponse = administrateur.patch(
        f"/api/gestion/admin/roles/{gestionnaire.pk}", {"actions": [*gestionnaire.actions, "encaisser"]}, format="json"
    )
    assert reponse.status_code == 400, "émettre et encaisser ne se cumulent pas"


def test_cau04_photos_sans_metadonnees_exif():
    exif = b"\xff\xe1\x00\x10Exif\x00\x00GPS-48.8N!!"
    photo = b"\xff\xd8" + exif + b"\xff\xdb\x00\x04\x00\x00\xff\xda\x00\x02image"
    nettoyee = fichiers.sans_metadonnees(photo)
    assert b"GPS" not in nettoyee and nettoyee.endswith(b"image")


def test_tar04_prestation_de_quantite_invalide_refusee(espace, client_agent):
    dossier = location(espace=espace).dossier
    reponse = client_agent(agent("gestionnaire")).post(
        "/api/gestion/finances/pieces/devis",
        {"dossier": dossier.pk, "prestations": [{"code": "menage", "quantite": 0}]},
        format="json",
    )
    assert reponse.status_code == 400


def test_tar03_reduction_accordee_seule_la_fin_se_modifie(client_agent):
    from apps.finances.models import Reduction

    reduction = Reduction.objects.create(
        usager=usager_avec_contact(), taux=5000, fondement="Convention 12", debut=date(2026, 1, 1)
    )
    financier = client_agent(agent("financier"))
    assert financier.patch(f"/api/gestion/finances/reductions/{reduction.pk}", {"taux": 10000}, format="json").status_code == 400
    assert (
        financier.patch(f"/api/gestion/finances/reductions/{reduction.pk}", {"fin": "2026-12-31"}, format="json").status_code
        == 200
    )
