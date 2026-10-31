"""Corrections des revues du lot 6 — pilotage : taux d'occupation (horaires de saison, sous-espaces, espace
partageable, changement d'heure — STA-01), recettes (avoirs, acompte — STA-03), compteurs qui ouvrent la liste qu'ils
comptent (DSH-06), éditions avec sous-espaces (IMP-01, IMP-03), envoi programmé (IMP-04 : domaines, responsable,
minimisation, semaine de l'échéance, échecs isolés), exports neutralisés (STA-04) et droits (RG-14)."""

from __future__ import annotations

import io
import zipfile
from datetime import date, datetime, time, timedelta

import pytest
from django.core import mail
from freezegun import freeze_time
from openpyxl import load_workbook

from apps.documents import gotenberg
from apps.pilotage import impressions, services
from apps.pilotage.models import EnvoiProgramme
from apps.referentiel.models import HoraireOuverture, Saison
from apps.reservations.models import Reservation
from apps.reservations.recurrence import PARIS
from apps.reservations.tests.outils import reserver
from tests.fabriques import EspaceFabrique, agent, usager_avec_contact

pytestmark = pytest.mark.django_db
LUNDI = date(2026, 11, 9)
PDF = b"%PDF-1.7 planning"


@pytest.fixture(autouse=True)
def environnement(monkeypatch):
    convertis: list[bytes] = []

    def convertir(nom, docx, transport=None):
        convertis.append(docx)
        return PDF

    monkeypatch.setattr(gotenberg, "convertir_en_pdfa", convertir)
    with freeze_time("2026-11-16 09:00") as horloge:
        yield {"horloge": horloge, "convertis": convertis}


def _texte(docx: bytes) -> str:
    with zipfile.ZipFile(io.BytesIO(docx)) as archive:
        return archive.read("word/document.xml").decode("utf-8")


def _occupation(client, **parametres):
    return client.get("/api/gestion/pilotage/statistiques/occupation", parametres).json()


# --- STA-01 : taux d'occupation (M9, M10, m9) -----------------------------------------------------------------


def test_sta01_horaires_de_saison_prioritaires(client_agent):
    """Horaires permanents 8 h – 22 h tous les jours ; en saison, 17 h – 22 h du lundi au vendredi (le week-end garde
    ses horaires permanents, comme pour le contrôle des réservations) : 4 × 5 h (11 novembre férié) + 2 × 14 h."""
    gymnase = EspaceFabrique(nom="Gymnase de saison")
    saison = Saison.objects.create(nom="Hiver 2026", debut=date(2026, 11, 1), fin=date(2026, 12, 15))
    for jour in range(7):
        HoraireOuverture.objects.create(espace=gymnase, jour_semaine=jour, debut=time(8), fin=time(22))
    for jour in range(5):
        HoraireOuverture.objects.create(espace=gymnase, jour_semaine=jour, debut=time(17), fin=time(22), saison=saison)
    for decalage in (0, 1, 3, 4):  # 4 séances de 5 h (le 11 novembre, férié, est fermé)
        reserver(gymnase, LUNDI + timedelta(days=decalage), "17:00", "22:00", usager=usager_avec_contact(), statut="validee")
    ligne = _occupation(client_agent(agent("direction")), du="2026-11-09", au="2026-11-15")["espaces"][0]
    assert ligne["minutes_ouverture"] == 48 * 60 and ligne["minutes_reservees"] == 20 * 60
    assert ligne["taux"] == round(10000 * 20 / 48)


def test_sta01_sous_espaces_parent_et_site_comptes_une_fois(client_agent):
    """Gymnase réservé 2 h en entier, sa moitié A 1 h à un autre moment : A occupée 3 h, B 2 h, le gymnase 3 h ;
    le site ne compte que le gymnase (14 h ouvertes le lundi, sans doubler par ses moitiés)."""
    gymnase = EspaceFabrique(nom="Gymnase")
    moitie_a = EspaceFabrique(nom="Moitié A", parent=gymnase, batiment=gymnase.batiment)
    moitie_b = EspaceFabrique(nom="Moitié B", parent=gymnase, batiment=gymnase.batiment)
    reserver(gymnase, LUNDI, "18:00", "20:00", usager=usager_avec_contact(), statut="validee")
    reserver(moitie_a, LUNDI, "10:00", "11:00", usager=usager_avec_contact(), statut="validee")
    donnees = _occupation(client_agent(agent("direction")), du="2026-11-09", au="2026-11-09")
    minutes = {ligne["espace"]: ligne["minutes_reservees"] for ligne in donnees["espaces"]}
    assert minutes == {gymnase.pk: 180, moitie_a.pk: 180, moitie_b.pk: 120}
    assert donnees["sites"][0]["minutes_reservees"] == 180 and donnees["sites"][0]["minutes_ouverture"] == 14 * 60


def test_sta01_espace_partageable_jamais_au_dela_de_100_pourcent(client_agent):
    piste = EspaceFabrique(nom="Piste", partageable=True, capacite_simultanee=2)
    for nom in ("Athlétisme", "Triathlon"):
        reserver(piste, LUNDI, "08:00", "22:00", usager=usager_avec_contact(nom=nom), statut="validee")
    ligne = _occupation(client_agent(agent("direction")), du="2026-11-09", au="2026-11-09")["espaces"][0]
    assert ligne["minutes_reservees"] == 14 * 60 and ligne["taux"] == 10000


def test_sta01_duree_reelle_le_jour_du_changement_d_heure():
    """Le 25 octobre 2026 dure 25 h : un espace ouvert jour et nuit l'est 1 500 minutes ce jour-là."""
    salle = EspaceFabrique(nom="Salle ouverte jour et nuit")
    HoraireOuverture.objects.create(espace=salle, jour_semaine=6, debut=time(0), fin=time(23, 59))
    assert services.minutes_ouverture(salle, date(2026, 10, 25), date(2026, 10, 25)) == 1500


# --- STA-03 : recettes (M11) ----------------------------------------------------------------------------------


def test_sta03_facture_creditee_compte_zero_et_acompte_regle_ne_laisse_rien_du(client_agent, modeles_documents, monkeypatch):
    from apps.documents import services as documents
    from apps.finances import facturation
    from apps.finances.tests.outils import grille_votee, location

    monkeypatch.setattr(documents, "convertir_en_pdfa", lambda nom, docx, transport=None: PDF)
    salle = EspaceFabrique(nom="Salle des fêtes")
    grille_votee(salle)
    with freeze_time("2026-11-02 10:00"):
        g, regie = agent("gestionnaire"), agent("regisseur")
        annulee = facturation.facturer(location(espace=salle, jour=date(2026, 12, 2)).dossier, acteur=g)
        facturation.emettre_avoir(annulee, acteur=agent("financier"), motif="Location annulée par la Ville")
        dossier = location(espace=salle).dossier
        devis = facturation.etablir_devis(dossier, acteur=g)
        facturation.accepter_devis(devis, acteur=g)
        acompte = facturation.facturer_acompte(dossier, acteur=g)
        facturation.pointer(acompte, acteur=regie, montant=acompte.total_du, jour=date(2026, 11, 2), reference="VIR-ACOMPTE")
        solde = facturation.facturer(dossier, acteur=g)
        facturation.pointer(solde, acteur=regie, montant=solde.reste_du, jour=date(2026, 11, 2), reference="VIR-SOLDE")
    donnees = (
        client_agent(agent("financier"))
        .get("/api/gestion/pilotage/statistiques/recettes", {"du": "2026-01-01", "au": "2026-12-31"})
        .json()
    )
    assert donnees["emis"] == annulee.total_du + solde.total_du and donnees["avoirs"] == annulee.total_du
    assert donnees["net"] == solde.total_du, "la facture entièrement créditée compte 0"
    assert donnees["regle"] == solde.total_du and donnees["reste_du"] == 0, "l'acompte réglé est déduit du solde"


def test_sta03_concours_en_nature_reserves_a_la_lecture_ville_entiere(client_agent):
    salle = EspaceFabrique(nom="Salle")
    periode = {"du": "2026-01-01", "au": "2026-12-31"}
    local = client_agent(agent("financier", salle.batiment.site)).get("/api/gestion/pilotage/statistiques/recettes", periode)
    assert local.json()["concours_en_nature"] is None
    ville = client_agent(agent("financier")).get("/api/gestion/pilotage/statistiques/recettes", periode)
    assert ville.json()["concours_en_nature"] == 0


# --- DSH-06 : le compteur et la liste qu'il ouvre comptent la même chose (M12) ---------------------------------


def test_dsh06_les_compteurs_ouvrent_une_liste_du_meme_nombre(client_agent, environnement):
    salle = EspaceFabrique(nom="Salle 1")
    reserver(salle, LUNDI + timedelta(days=14), "18:00", "20:00", statut="demande")
    instruction = reserver(salle, LUNDI + timedelta(days=15), "18:00", "20:00", statut="demande")
    Reservation.objects.filter(pk=instruction.pk).update(statut="en_instruction")
    proche = reserver(salle, LUNDI + timedelta(days=16), "18:00", "20:00", statut="demande")
    lointaine = reserver(salle, LUNDI + timedelta(days=17), "18:00", "20:00", statut="demande")
    maintenant = datetime(2026, 11, 16, 9, tzinfo=PARIS)
    Reservation.objects.filter(pk=proche.pk).update(statut="option", option_expire_le=maintenant + timedelta(hours=24))
    Reservation.objects.filter(pk=lointaine.pk).update(statut="option", option_expire_le=maintenant + timedelta(days=5))
    gestion = client_agent(agent("gestionnaire"))
    compteurs = {c["code"]: c for c in gestion.get("/api/gestion/pilotage/a-traiter").json()["compteurs"]}
    for code, attendu in (("demandes", 2), ("options", 1)):
        lien = compteurs[code]["lien"]
        assert lien.startswith("/reservations/dossiers?")
        liste = gestion.get("/api/gestion/reservations/dossiers?" + lien.split("?", 1)[1]).json()
        assert compteurs[code]["nombre"] == attendu == liste["count"], code


# --- IMP-01, IMP-03 : sous-espaces (M13) ; IMP-04 (B1, M5, m10) ----------------------------------------------------


def test_imp01_imp03_le_parent_montre_ses_moities_et_la_moitie_montre_le_parent(client_agent, environnement):
    gymnase = EspaceFabrique(nom="Gymnase Colette")
    moitie = EspaceFabrique(nom="Moitié nord", parent=gymnase, batiment=gymnase.batiment)
    reserver(
        moitie, LUNDI + timedelta(days=7), "18:00", "20:00", usager=usager_avec_contact(nom="Club de hand"), statut="validee"
    )
    reserver(
        gymnase, LUNDI + timedelta(days=8), "18:00", "20:00", usager=usager_avec_contact(nom="Club de volley"), statut="validee"
    )
    gestion = client_agent(agent("gestionnaire"))
    planning = gestion.get("/api/gestion/pilotage/planning.pdf", {"espace": gymnase.pk, "du": "2026-11-16", "au": "2026-11-22"})
    assert planning.status_code == 200 and "Club de hand" in _texte(environnement["convertis"][-1])
    feuille = gestion.get("/api/gestion/pilotage/feuille-de-salle.pdf", {"espace": moitie.pk, "jour": "2026-11-16"})
    assert feuille.status_code == 200 and "Club de volley" in _texte(environnement["convertis"][-1])


def test_imp04_destinataires_hors_domaine_refuses(client_agent):
    salle = EspaceFabrique(nom="Salle")
    reponse = client_agent(agent("gestionnaire")).post(
        "/api/gestion/pilotage/envois-planning",
        {"libelle": "Planning", "espace": salle.pk, "destinataires": ["perso@gmail.com"], "jour_semaine": 4, "heure": "16:00"},
        format="json",
    )
    assert reponse.status_code == 400 and "domaines de la Ville" in str(reponse.json())


def _envoi(espace, createur, **champs) -> EnvoiProgramme:
    envoi = EnvoiProgramme.objects.create(
        libelle=f"Planning {espace.nom}",
        espace=espace,
        destinataires=["gardiens@chatillon92.fr"],
        jour_semaine=6,
        heure=time(23, 30),
        cree_par=createur,
        **champs,
    )
    return impressions.programmer(envoi, acteur=createur)


def test_imp04_diffusion_minimisee_et_semaine_de_l_echeance(environnement, django_capture_on_commit_callbacks):
    """Échéance dimanche 22/11 23 h 30, traitée lundi 23/11 à 0 h 05 : la semaine envoyée est celle du 23/11 ; le
    particulier n'est pas nommé et l'objet de sa demande n'est pas repris."""
    salle = EspaceFabrique(nom="Salle polyvalente")
    privee = reserver(
        salle,
        date(2026, 11, 24),
        "18:00",
        "20:00",
        usager=usager_avec_contact(nom="Durand", type="particulier"),
        statut="validee",
    )
    type(privee.dossier).objects.filter(pk=privee.dossier_id).update(objet="Anniversaire de Léa, 8 ans")
    envoi = _envoi(salle, agent("gestionnaire"))
    assert envoi.prochain_envoi_le == datetime(2026, 11, 22, 23, 30, tzinfo=PARIS)
    environnement["horloge"].move_to(datetime(2026, 11, 23, 0, 5, tzinfo=PARIS))
    with django_capture_on_commit_callbacks(execute=True):
        assert impressions.envoyer_plannings_dus() == 1
    texte = _texte(environnement["convertis"][-1])
    assert "23/11/2026" in texte and "Réservation privée" in texte
    assert "Durand" not in texte and "Anniversaire" not in texte
    assert [m.attachments[0][0] for m in mail.outbox] == ["planning-20261123.pdf"]


def test_imp04_responsable_sans_droits_l_envoi_est_suspendu(environnement):
    salle = EspaceFabrique(nom="Salle")
    createur = agent("gestionnaire")
    envoi = _envoi(salle, createur)
    type(createur).objects.filter(pk=createur.pk).update(is_active=False)
    environnement["horloge"].move_to(datetime(2026, 11, 23, 0, 5, tzinfo=PARIS))
    assert impressions.envoyer_plannings_dus() == 0
    envoi.refresh_from_db()
    assert not envoi.actif and "responsable" in envoi.suspendu_motif and not mail.outbox


def test_imp04_un_envoi_en_echec_ne_bloque_pas_les_suivants(environnement, monkeypatch, django_capture_on_commit_callbacks):
    from apps.documents import impression

    createur = agent("gestionnaire")
    premier = _envoi(EspaceFabrique(nom="A — salle en échec"), createur)
    second = _envoi(EspaceFabrique(nom="B — salle"), createur)
    original = impression.imprimer

    def imprimer(edition):
        if "échec" in edition.titre:
            raise ValueError("caractère interdit")
        return original(edition)

    monkeypatch.setattr(impression, "imprimer", imprimer)
    environnement["horloge"].move_to(datetime(2026, 11, 23, 0, 5, tzinfo=PARIS))
    with django_capture_on_commit_callbacks(execute=True):
        assert impressions.envoyer_plannings_dus() == 1
    premier.refresh_from_db()
    second.refresh_from_db()
    assert premier.echecs == 1 and premier.actif and second.dernier_envoi_le is not None


def test_imp01_un_caractere_de_controle_saisi_n_empeche_pas_l_impression(client_agent):
    salle = EspaceFabrique(nom="Salle")
    reserver(
        salle, LUNDI + timedelta(days=7), "18:00", "20:00", usager=usager_avec_contact(nom="Club\x0b de judo"), statut="validee"
    )
    reponse = client_agent(agent("gestionnaire")).get(
        "/api/gestion/pilotage/planning.pdf", {"espace": salle.pk, "du": "2026-11-16"}
    )
    assert reponse.status_code == 200


# --- STA-04 : exports neutralisés (M6, m1 sécurité) --------------------------------------------------------------


def test_sta04_export_de_la_repartition_neutralise_et_sans_caractere_de_controle(client_agent):
    salle = EspaceFabrique(nom="Salle")
    for debut, fin, activite in (("18:00", "20:00", '=HYPERLINK("x")'), ("20:00", "21:00", "Yoga\x0b doux")):
        r = reserver(salle, LUNDI, debut, fin, usager=usager_avec_contact(), statut="validee")
        type(r.dossier).objects.filter(pk=r.dossier_id).update(activite=activite)
    reponse = client_agent(agent("direction")).get(
        "/api/gestion/pilotage/statistiques/repartition", {"du": "2026-11-09", "au": "2026-11-15", "export": "xlsx"}
    )
    assert reponse.status_code == 200
    feuille = load_workbook(io.BytesIO(reponse.content))["Activités"]
    valeurs = [feuille.cell(row=r, column=1).value for r in range(2, feuille.max_row + 1)]
    assert '\'=hyperlink("x")' in [str(v).lower() for v in valeurs] and "Yoga doux" in valeurs


def test_sta04_export_du_personnel(client_agent):
    reponse = client_agent(agent("planificateur")).get(
        "/api/gestion/pilotage/statistiques/personnel", {"du": "2026-11-01", "au": "2026-11-30", "export": "xlsx"}
    )
    assert reponse.status_code == 200 and load_workbook(io.BytesIO(reponse.content))["Personnel"]["A2"].value == "Agents (nombre)"


# --- Droits refusés (RG-14 ; règle 2 de CLAUDE.md) ----------------------------------------------------------------


def test_rg14_statistiques_et_tableau_de_bord_refuses_sans_le_droit(client_agent):
    periode = {"du": "2026-11-01", "au": "2026-11-30"}
    accueil = client_agent(agent("accueil"))
    for indicateur in ("occupation", "repartition", "personnel", "recettes"):
        assert accueil.get(f"/api/gestion/pilotage/statistiques/{indicateur}", periode).status_code == 403, indicateur
    gardien = client_agent(agent("gardien")).get("/api/gestion/pilotage/a-traiter").json()["compteurs"]
    assert not {"demandes", "options", "factures", "cautions", "attestations"} & {c["code"] for c in gardien}


def test_rg14_statistiques_d_un_autre_site_vides(client_agent):
    mien, autre = EspaceFabrique(nom="Mon gymnase"), EspaceFabrique(nom="Gymnase voisin")
    local = client_agent(agent("gestionnaire", mien.batiment.site))
    donnees = _occupation(local, du="2026-11-09", au="2026-11-15", site=autre.batiment.site_id)
    assert donnees == {"espaces": [], "sites": []}


def test_rg14_editions_et_envois_hors_perimetre_refuses(client_agent):
    mien, autre = EspaceFabrique(nom="Mon gymnase"), EspaceFabrique(nom="Gymnase voisin")
    local = client_agent(agent("gestionnaire", mien.batiment.site))
    assert local.get("/api/gestion/pilotage/feuille-de-salle.pdf", {"espace": autre.pk}).status_code == 403
    assert local.get("/api/gestion/pilotage/planning.pdf", {"site": autre.batiment.site_id}).status_code == 403
    base = {"libelle": "Planning", "destinataires": ["gardiens@chatillon92.fr"], "jour_semaine": 4, "heure": "16:00"}
    assert local.post("/api/gestion/pilotage/envois-planning", {**base, "espace": autre.pk}, format="json").status_code == 403
    envoi = _envoi(autre, agent("gestionnaire"))
    assert local.get("/api/gestion/pilotage/envois-planning").json()["count"] == 0
    assert local.patch(f"/api/gestion/pilotage/envois-planning/{envoi.pk}", {"libelle": "x"}, format="json").status_code == 404
    assert local.delete(f"/api/gestion/pilotage/envois-planning/{envoi.pk}").status_code == 404
    assert local.post("/api/gestion/pilotage/envois-planning", {**base, "espace": mien.pk}, format="json").status_code == 201
