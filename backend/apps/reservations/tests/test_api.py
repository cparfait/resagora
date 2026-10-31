"""API des réservations : succès, validation, 401, 403/404 hors périmètre (CLAUDE.md règle 2)."""

from __future__ import annotations

from datetime import date

import pytest
from freezegun import freeze_time

from apps.reservations.models import Occurrence, Reservation, TypeReservation, VueEnregistree
from tests.fabriques import EspaceFabrique, SiteFabrique, UsagerFabrique, agent, saison_2026, usager_avec_contact

from .outils import paris, reserver, valider_systeme

pytestmark = pytest.mark.django_db
DOSSIERS = "/api/gestion/reservations/dossiers"


@pytest.fixture
def contexte():
    site_a, site_b = SiteFabrique(nom="Site A"), SiteFabrique(nom="Site B")
    return {
        "site_a": site_a,
        "site_b": site_b,
        "espace_a": EspaceFabrique(batiment__site=site_a),
        "espace_b": EspaceFabrique(batiment__site=site_b),
        "gestionnaire_a": agent("gestionnaire", site_a),
        "usager": usager_avec_contact(),
    }


def creer_dossier(client, usager, type_code="ponctuelle"):
    reponse = client.post(
        DOSSIERS,
        {"usager": usager.pk, "type_reservation": TypeReservation.objects.get(code=type_code).pk, "objet": "Tournoi"},
        format="json",
    )
    assert reponse.status_code == 201, reponse.json()
    return reponse.json()


def corps_reservation(espace, **autres):
    return {
        "espace": espace.pk,
        "date_debut": "2026-11-10",
        "date_fin": "2026-11-10",
        "heure_debut": "18:00",
        "heure_fin": "20:00",
        **autres,
    }


def test_pla06_parcours_api_dossier_reservation_validation(client_agent, contexte):
    client = client_agent(contexte["gestionnaire_a"])
    dossier = creer_dossier(client, contexte["usager"])
    assert dossier["numero"].startswith("D") and dossier["statut"] == "demande"
    reservation = client.post(f"{DOSSIERS}/{dossier['id']}/reservations", corps_reservation(contexte["espace_a"]), format="json")
    assert reservation.status_code == 201 and reservation.json()["nombre_occurrences"] == 1
    validee = client.post(f"/api/gestion/reservations/reservations/{reservation.json()['id']}/valider")
    assert validee.status_code == 200 and validee.json()["statut"] == "validee"
    assert "fournir des pièces" in validee.json()["conditions_manquantes"][0]


def test_rg14_reservation_sur_un_espace_hors_perimetre_refusee(client_agent, contexte):
    client = client_agent(contexte["gestionnaire_a"])
    dossier = creer_dossier(client, contexte["usager"])
    reponse = client.post(f"{DOSSIERS}/{dossier['id']}/reservations", corps_reservation(contexte["espace_b"]), format="json")
    assert reponse.status_code == 403


def test_rg14_dossiers_et_reservations_d_un_autre_site_invisibles(client_agent, contexte):
    autre = reserver(contexte["espace_b"], date(2026, 11, 10), "18:00", "20:00")
    client = client_agent(contexte["gestionnaire_a"])
    assert all(d["id"] != autre.dossier_id for d in client.get(DOSSIERS).json()["results"])
    assert client.get(f"{DOSSIERS}/{autre.dossier_id}").status_code == 404
    assert client.post(f"/api/gestion/reservations/reservations/{autre.pk}/valider").status_code == 404
    seance = autre.occurrences.get()
    assert client.post(f"/api/gestion/reservations/seances/{seance.pk}/annuler", {"motif": "x"}, format="json").status_code == 404


def test_rg14_api_reservations_non_authentifie(client_api):
    for chemin in (
        DOSSIERS,
        "/api/gestion/reservations/planning?debut=2026-11-01T00:00:00&fin=2026-11-08T00:00:00",
        "/api/gestion/reservations/seances",
    ):
        assert client_api.get(chemin).status_code == 401


def test_rg01_api_conflit_detaille(client_agent, contexte):
    valider_systeme(reserver(contexte["espace_a"], date(2026, 11, 10), "18:00", "20:00"))
    concurrente = reserver(contexte["espace_a"], date(2026, 11, 10), "19:00", "21:00")
    reponse = client_agent(contexte["gestionnaire_a"]).post(f"/api/gestion/reservations/reservations/{concurrente.pk}/valider")
    assert reponse.status_code == 409 and reponse.json()["code"] == "conflit"
    assert reponse.json()["details"]["conflits"][0]["dossier"]


def test_pla04_apercu_avant_enregistrement(client_agent, contexte):
    saison_2026()
    client = client_agent(contexte["gestionnaire_a"])
    corps = corps_reservation(
        contexte["espace_a"], date_debut="2026-09-01", date_fin="2026-12-31", recurrence="FREQ=WEEKLY;BYDAY=TU"
    )
    apercu = client.post(f"{DOSSIERS}/apercu", corps, format="json").json()
    assert apercu["description"].startswith("tous les mardis de 18 h à 20 h")
    assert len(apercu["seances"]) == 14 and apercu["conflits"] == []
    assert not Reservation.objects.exists()


def test_pla04_validation_des_champs(client_agent, contexte):
    client = client_agent(contexte["gestionnaire_a"])
    dossier = creer_dossier(client, contexte["usager"])
    reponse = client.post(
        f"{DOSSIERS}/{dossier['id']}/reservations", corps_reservation(contexte["espace_a"], date_fin="2026-11-01"), format="json"
    )
    assert reponse.status_code == 400 and "date_fin" in reponse.json()["champs"]


def test_pla01_planning_filtre_par_perimetre_et_periode(client_agent, contexte):
    a = reserver(contexte["espace_a"], date(2026, 11, 10), "18:00", "20:00")
    reserver(contexte["espace_b"], date(2026, 11, 10), "18:00", "20:00")
    reserver(contexte["espace_a"], date(2026, 12, 10), "18:00", "20:00")
    client = client_agent(contexte["gestionnaire_a"])
    reponse = client.get(
        "/api/gestion/reservations/planning", {"debut": "2026-11-09T00:00:00+01:00", "fin": "2026-11-16T00:00:00+01:00"}
    )
    assert reponse.status_code == 200 and [s["reservation"] for s in reponse.json()] == [a.pk]
    assert (
        client.get(
            "/api/gestion/reservations/planning", {"debut": "2026-01-01T00:00:00", "fin": "2026-12-31T00:00:00"}
        ).status_code
        == 400
    )


def test_pla02_controle_de_deplacement_puis_deplacement(client_agent, contexte):
    with freeze_time("2026-11-01 10:00"):
        occupee = valider_systeme(reserver(contexte["espace_a"], date(2026, 11, 10), "18:00", "20:00"))
        a_deplacer = valider_systeme(reserver(contexte["espace_a"], date(2026, 11, 11), "18:00", "20:00")).occurrences.get()
        client = client_agent(contexte["gestionnaire_a"])
        cible = {
            "espace": contexte["espace_a"].pk,
            "debut": paris(2026, 11, 10, 19).isoformat(),
            "fin": paris(2026, 11, 10, 21).isoformat(),
        }
        controle = client.post(
            f"/api/gestion/reservations/seances/{a_deplacer.pk}/controle-deplacement", cible, format="json"
        ).json()
        assert controle["possible"] is False and controle["conflits"][0]["reservation"] == occupee.pk and controle["alternatives"]
        assert client.post(f"/api/gestion/reservations/seances/{a_deplacer.pk}/deplacer", cible, format="json").status_code == 409
        libre = {**cible, "debut": paris(2026, 11, 10, 20).isoformat(), "fin": paris(2026, 11, 10, 22).isoformat()}
        assert (
            client.post(f"/api/gestion/reservations/seances/{a_deplacer.pk}/controle-deplacement", libre, format="json").json()[
                "possible"
            ]
            is True
        )
        assert client.post(f"/api/gestion/reservations/seances/{a_deplacer.pk}/deplacer", libre, format="json").status_code == 200
    assert Occurrence.objects.get(pk=a_deplacer.pk).debut == paris(2026, 11, 10, 20)


def test_pla02_deplacement_vers_un_espace_hors_perimetre_refuse(client_agent, contexte):
    seance = valider_systeme(reserver(contexte["espace_a"], date(2026, 11, 11), "18:00", "20:00")).occurrences.get()
    cible = {
        "espace": contexte["espace_b"].pk,
        "debut": paris(2026, 11, 11, 18).isoformat(),
        "fin": paris(2026, 11, 11, 20).isoformat(),
    }
    assert (
        client_agent(contexte["gestionnaire_a"])
        .post(f"/api/gestion/reservations/seances/{seance.pk}/deplacer", cible, format="json")
        .status_code
        == 403
    )


def test_pla10_annulation_et_presence_par_l_api(client_agent, contexte):
    with freeze_time("2026-11-01 10:00"):
        client = client_agent(contexte["gestionnaire_a"])
        seance = valider_systeme(reserver(contexte["espace_a"], date(2026, 11, 10), "18:00", "20:00")).occurrences.get()
        assert client.post(f"/api/gestion/reservations/seances/{seance.pk}/annuler", {}, format="json").status_code == 400
    with freeze_time("2026-11-11 10:00"):
        client = client_agent(contexte["gestionnaire_a"])
        reponse = client.post(f"/api/gestion/reservations/seances/{seance.pk}/presence", {"presence": "present"}, format="json")
    assert reponse.status_code == 200 and reponse.json()["statut"] == "realisee"


def test_pla03_vues_enregistrees_propres_a_chaque_agent(client_agent, contexte):
    client = client_agent(contexte["gestionnaire_a"])
    cree = client.post(
        "/api/gestion/reservations/vues",
        {"nom": "Gymnases le soir", "mode": "chronologie", "filtres": {"famille": 1}, "par_defaut": True},
        format="json",
    )
    assert cree.status_code == 201
    autre = client_agent(agent("gestionnaire"))
    assert autre.get("/api/gestion/reservations/vues").json() == []
    assert autre.delete(f"/api/gestion/reservations/vues/{cree.json()['id']}").status_code == 404
    assert VueEnregistree.objects.get().par_defaut is True


def test_pla05_campagne_par_l_api(client_agent):
    saison = saison_2026()
    gestionnaire, elu = agent("gestionnaire"), agent("elu_commission")
    espace = EspaceFabrique()
    client = client_agent(gestionnaire)
    campagne = client.post(
        "/api/gestion/reservations/campagnes",
        {"saison": saison.pk, "nom": "Créneaux 2026-2027", "ouverture": "2026-05-01", "cloture": "2026-06-15"},
        format="json",
    )
    assert campagne.status_code == 201
    identifiant = campagne.json()["id"]
    assert (
        client.post(f"/api/gestion/reservations/campagnes/{identifiant}/statut", {"statut": "ouverte"}, format="json").status_code
        == 200
    )
    from apps.reservations.models import Campagne, Dossier

    demandes = []
    for usager in (UsagerFabrique(type="association", local=True, conventionne=True), UsagerFabrique(type="entreprise")):
        r = reserver(
            espace,
            date(2026, 9, 1),
            "18:00",
            "20:00",
            usager=usager,
            type_code="creneau_annuel",
            recurrence="FREQ=WEEKLY;BYDAY=TU",
            date_fin=date(2027, 6, 29),
        )
        Dossier.objects.filter(pk=r.dossier_id).update(campagne_id=identifiant, saison=saison)
        demandes.append(r)
    for statut in ("instruction", "commission"):
        assert (
            client.post(
                f"/api/gestion/reservations/campagnes/{identifiant}/statut", {"statut": statut}, format="json"
            ).status_code
            == 200
        )
    analyse = client.get(f"/api/gestion/reservations/campagnes/{identifiant}/analyse").json()
    assert [c["proposition"] for c in analyse[0]["candidats"]] == ["attribuer", "refuser"]
    assert analyse[0]["candidats"][0]["reservation_id"] == demandes[0].pk
    decisions = {
        str(demandes[0].pk): {"decision": "attribuer"},
        str(demandes[1].pk): {"decision": "refuser", "motif": "Créneau attribué à un club local"},
    }
    assert (
        client.post(
            f"/api/gestion/reservations/campagnes/{identifiant}/attribution", {"decisions": decisions}, format="json"
        ).status_code
        == 403
    )
    reponse = client_agent(elu).post(
        f"/api/gestion/reservations/campagnes/{identifiant}/attribution", {"decisions": decisions}, format="json"
    )
    assert reponse.status_code == 200 and reponse.json() == {"attribuees": 1, "refusees": 1}
    assert Campagne.objects.get(pk=identifiant).statut == "commission"


def test_pla09_inscription_liste_attente_par_l_api(client_agent, contexte):
    corps = {
        "espace": contexte["espace_a"].pk,
        "debut": paris(2026, 11, 20, 18).isoformat(),
        "fin": paris(2026, 11, 20, 20).isoformat(),
        "usager": contexte["usager"].pk,
    }
    assert (
        client_agent(contexte["gestionnaire_a"]).post("/api/gestion/reservations/liste-attente", corps, format="json").status_code
        == 201
    )
    corps["espace"] = contexte["espace_b"].pk
    assert (
        client_agent(contexte["gestionnaire_a"]).post("/api/gestion/reservations/liste-attente", corps, format="json").status_code
        == 403
    )
