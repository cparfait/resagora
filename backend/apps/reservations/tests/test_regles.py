"""Règles de gestion des réservations, testées sans HTTP (skill metier-reservations)."""

from __future__ import annotations

import threading
from datetime import UTC, date, timedelta

import pytest
from django.core import mail
from django.db import connection
from django.utils import timezone
from freezegun import freeze_time

from apps.noyau.exceptions import AccesRefuse, ErreurMetier, ErreurValidation
from apps.noyau.models import Parametre
from apps.noyau.parametres import invalider
from apps.referentiel.models import Fermeture, HoraireOuverture
from apps.reservations import services
from apps.reservations.models import Occurrence, Reservation, Verrou
from apps.reservations.recurrence import PARIS, decrire, generer_plages
from apps.usagers.models import PieceJustificative, TypePiece
from apps.usagers.services import rang_priorite
from tests.fabriques import EspaceFabrique, UsagerFabrique, agent, saison_2026, usager_avec_contact

from .outils import paris, reserver, valider_systeme

pytestmark = pytest.mark.django_db
MARDIS_SAISON = "FREQ=WEEKLY;BYDAY=TU"


@pytest.fixture
def espace():
    return EspaceFabrique(nom="Gymnase Jean-Moulin")


@pytest.fixture
def gymnase():
    entier = EspaceFabrique(nom="Gymnase divisible")
    tiers = [EspaceFabrique(batiment=entier.batiment, parent=entier, nom=f"Tiers {i}") for i in (1, 2, 3)]
    return entier, tiers


# --- PLA-04 récurrences --------------------------------------------------------------------------


def test_pla04_recurrence_exclut_vacances_zone_c_et_feries(espace):
    saison_2026()
    r = reserver(espace, date(2026, 9, 1), "18:00", "20:00", recurrence=MARDIS_SAISON, date_fin=date(2026, 12, 31))
    jours = [timezone.localtime(o.debut, PARIS).date() for o in r.occurrences.all()]
    assert date(2026, 10, 20) not in jours and date(2026, 10, 27) not in jours  # Toussaint
    assert date(2026, 12, 22) not in jours and date(2026, 12, 29) not in jours  # Noël
    assert date(2026, 10, 13) in jours and date(2026, 11, 3) in jours
    assert all(timezone.localtime(o.debut, PARIS).weekday() == 1 for o in r.occurrences.all())


def test_pla04_changement_d_heure_d_octobre(espace):
    r = reserver(
        espace, date(2026, 10, 20), "18:00", "20:00", recurrence=MARDIS_SAISON, date_fin=date(2026, 11, 3), exclure_vacances=False
    )
    debuts = list(r.occurrences.values_list("debut", flat=True))
    assert [timezone.localtime(d, PARIS).hour for d in debuts] == [18, 18, 18]
    assert [d.astimezone(UTC).hour for d in debuts] == [16, 17, 17]  # passage à l'heure d'hiver le 25 octobre


def test_pla04_creneau_de_nuit_et_exdates(espace):
    plages = generer_plages(
        Reservation(
            espace=espace,
            date_debut=date(2026, 9, 4),
            date_fin=date(2026, 9, 25),
            heure_debut=paris(2026, 1, 1, 22).time(),
            heure_fin=paris(2026, 1, 1, 1).time(),
            recurrence="FREQ=WEEKLY;BYDAY=FR",
            exclure_vacances=False,
            exclure_feries=False,
            exdates=[date(2026, 9, 11)],
        )
    )
    assert len(plages) == 3 and all(f - d == timedelta(hours=3) for d, f in plages)


def test_pla04_description_lisible(espace):
    saison_2026()
    r = reserver(espace, date(2026, 9, 1), "18:00", "20:30", recurrence=MARDIS_SAISON, date_fin=date(2027, 6, 29))
    assert decrire(r).startswith(
        "tous les mardis de 18 h à 20 h 30, hors vacances scolaires et jours fériés, du 1 septembre 2026"
    )


def test_pla04_regle_inconnue_refusee(espace):
    with pytest.raises(ErreurValidation):
        reserver(espace, date(2026, 9, 1), "18:00", "20:00", recurrence="FREQ=SECONDLY")


def test_pla04_modifier_cette_seance_les_suivantes_ou_la_serie(espace):
    gestionnaire = agent("gestionnaire")
    r = valider_systeme(
        reserver(
            espace,
            date(2026, 11, 3),
            "18:00",
            "20:00",
            recurrence=MARDIS_SAISON,
            date_fin=date(2026, 12, 15),
            exclure_vacances=False,
        )
    )
    seances = list(r.occurrences.order_by("debut"))
    services.deplacer_occurrence(
        seances[0], acteur=gestionnaire, espace=espace, debut=paris(2026, 11, 4, 18), fin=paris(2026, 11, 4, 20)
    )
    suite = services.modifier_suivantes(
        seances[3], acteur=gestionnaire, heure_debut=paris(2026, 1, 1, 19).time(), heure_fin=paris(2026, 1, 1, 21).time()
    )
    r.refresh_from_db()
    assert r.date_fin == date(2026, 11, 23) and r.occurrences.count() == 3
    assert all(timezone.localtime(o.debut, PARIS).hour == 19 for o in suite.occurrences.all())
    services.modifier_serie(
        suite, acteur=gestionnaire, heure_debut=paris(2026, 1, 1, 17).time(), heure_fin=paris(2026, 1, 1, 18).time()
    )
    assert all(timezone.localtime(o.debut, PARIS).hour == 17 for o in suite.occurrences.all())
    assert timezone.localtime(Occurrence.objects.get(pk=seances[0].pk).debut, PARIS).day == 4


# --- RG-01, RG-02, REF-05, REF-07 ----------------------------------------------------------------


def test_rg02_demandes_et_options_ne_bloquent_pas(espace):
    a = reserver(espace, date(2026, 11, 10), "18:00", "20:00")
    reserver(espace, date(2026, 11, 10), "19:00", "21:00")
    services.mettre_en_option(a, acteur=agent("gestionnaire"))
    assert not Verrou.objects.exists()


def test_rg01_chevauchement_refuse_avec_message_clair(espace):
    valider_systeme(reserver(espace, date(2026, 11, 10), "18:00", "20:00"))
    concurrente = reserver(espace, date(2026, 11, 10), "19:30", "21:00")
    with pytest.raises(ErreurMetier) as erreur:
        services.valider(concurrente, acteur=agent("gestionnaire"))
    assert erreur.value.code == "conflit" and "déjà occupé" in erreur.value.message
    assert erreur.value.details["conflits"][0]["espace"] == espace.nom
    concurrente.refresh_from_db()
    assert concurrente.statut == "demande"


def test_rg01_contrainte_d_exclusion_en_base(espace):
    a = valider_systeme(reserver(espace, date(2026, 11, 10), "18:00", "20:00"))
    b = reserver(espace, date(2026, 11, 10), "19:00", "21:00")
    occurrence_b = b.occurrences.get()
    from django.db import IntegrityError, transaction

    with pytest.raises(IntegrityError), transaction.atomic():
        Verrou.objects.create(occurrence=occurrence_b, feuille=espace, plage=a.occurrences.get().verrous.get().plage)


def test_ref05_gymnase_entier_et_tiers_se_bloquent_mutuellement(gymnase):
    entier, (t1, t2, t3) = gymnase
    valider_systeme(reserver(t1, date(2026, 11, 10), "18:00", "20:00"))
    valider_systeme(reserver(t2, date(2026, 11, 10), "18:00", "20:00"))
    with pytest.raises(ErreurMetier):
        valider_systeme(reserver(entier, date(2026, 11, 10), "19:00", "21:00"))
    valider_systeme(reserver(entier, date(2026, 11, 12), "18:00", "20:00"))
    with pytest.raises(ErreurMetier):
        valider_systeme(reserver(t3, date(2026, 11, 12), "18:30", "19:00"))


def test_ref07_espace_partageable_dans_la_limite_de_sa_capacite():
    piste = EspaceFabrique(nom="Piste d'athlétisme", partageable=True, capacite_simultanee=2)
    valider_systeme(reserver(piste, date(2026, 11, 10), "18:00", "20:00"))
    valider_systeme(reserver(piste, date(2026, 11, 10), "18:00", "20:00"))
    with pytest.raises(ErreurMetier):
        valider_systeme(reserver(piste, date(2026, 11, 10), "19:00", "20:00"))


@pytest.mark.django_db(transaction=True, serialized_rollback=True)
def test_rg01_deux_validations_simultanees_une_seule_reussit():
    espace = EspaceFabrique()
    a = reserver(espace, date(2026, 11, 10), "18:00", "20:00")
    b = reserver(espace, date(2026, 11, 10), "19:00", "21:00")
    gestionnaire = agent("gestionnaire")
    barriere = threading.Barrier(2)
    resultats: list[str] = []

    def valider_en_parallele(reservation: Reservation) -> None:
        try:
            barriere.wait()
            services.valider(reservation, acteur=gestionnaire)
            resultats.append("ok")
        except ErreurMetier as erreur:
            resultats.append(erreur.code)
        finally:
            connection.close()

    fils = [threading.Thread(target=valider_en_parallele, args=(r,)) for r in (a, b)]
    for f in fils:
        f.start()
    for f in fils:
        f.join()
    assert sorted(resultats)[1] == "ok" and resultats.count("ok") == 1
    assert Verrou.objects.count() == 1


# --- REF-03 horaires -----------------------------------------------------------------------------


def test_ref03_demande_hors_horaires_refusee(espace):
    HoraireOuverture.objects.create(
        espace=espace, jour_semaine=1, debut=paris(2026, 1, 1, 8).time(), fin=paris(2026, 1, 1, 22).time()
    )
    with pytest.raises(ErreurValidation) as erreur:
        reserver(espace, date(2026, 11, 10), "21:00", "23:00")
    assert erreur.value.code == "hors_horaires"
    reserver(espace, date(2026, 11, 10), "20:00", "22:00")


# --- PLA-06, RG-06 statuts et confirmation ---------------------------------------------------------


def test_pla06_cycle_de_statuts_complet(espace):
    gestionnaire = agent("gestionnaire")
    with freeze_time("2026-11-01 10:00"):
        r = reserver(espace, date(2026, 11, 10), "18:00", "20:00", type_code="scolaire")
        services.instruire(r, acteur=gestionnaire)
        services.valider(r, acteur=gestionnaire)
        services.confirmer(r, acteur=gestionnaire)
    with freeze_time("2026-11-11 10:00"):
        services.saisir_presence(r.occurrences.get(), acteur=gestionnaire, presence="present")
        r = services.cloturer(r, acteur=gestionnaire)
    assert r.statut == "cloturee"
    with pytest.raises(ErreurMetier):
        services.annuler(r, acteur=gestionnaire, motif="trop tard")


def test_rg06_confirmation_sans_pieces_valides_refusee(espace):
    gestionnaire = agent("gestionnaire")
    usager = usager_avec_contact()
    r = valider_systeme(reserver(espace, date(2026, 11, 10), "18:00", "20:00", usager=usager))
    with pytest.raises(ErreurMetier) as erreur:
        services.confirmer(r, acteur=gestionnaire)
    assert erreur.value.code == "conditions_non_remplies" and "Statuts" in erreur.value.message
    from apps.noyau.models import Fichier

    for type_piece in TypePiece.objects.filter(types_usager__contains=["association"], obligatoire=True):
        fichier = Fichier.objects.create(
            nom_origine="p.pdf", type_mime="application/pdf", taille=1, sha256="0" * 64, chemin=f"x/{type_piece.code}"
        )
        PieceJustificative.objects.create(usager=usager, type_piece=type_piece, fichier=fichier, statut="valide")
    assert services.confirmer(r, acteur=gestionnaire).statut == "confirmee"


def test_rg14_transition_refusee_hors_perimetre(espace):
    from apps.noyau.exceptions import AccesRefuse
    from tests.fabriques import SiteFabrique

    r = reserver(espace, date(2026, 11, 10), "18:00", "20:00")
    with pytest.raises(AccesRefuse):
        services.valider(r, acteur=agent("gestionnaire", SiteFabrique()))


def test_pla06_refus_motive_et_notifie(espace, django_capture_on_commit_callbacks):
    r = reserver(espace, date(2026, 11, 10), "18:00", "20:00")
    with pytest.raises(ErreurValidation):
        services.refuser(r, acteur=agent("gestionnaire"), motif=" ")
    with django_capture_on_commit_callbacks(execute=True):
        services.refuser(r, acteur=agent("gestionnaire"), motif="Créneau réservé aux scolaires")
    assert "Créneau réservé aux scolaires" in mail.outbox[-1].body


# --- RG-07 options -------------------------------------------------------------------------------


def test_pla08_option_avec_date_d_expiration_parametrable(espace):
    Parametre.objects.update_or_create(cle="options.duree_jours", defaults={"valeur": 10})
    invalider()
    with freeze_time("2026-11-01 09:00"):
        r = services.mettre_en_option(reserver(espace, date(2026, 12, 10), "18:00", "20:00"), acteur=agent("gestionnaire"))
        assert r.statut == "option" and r.option_expire_le == timezone.now() + timedelta(days=10)
        autre = reserver(espace, date(2026, 12, 10), "18:00", "20:00")
        assert valider_systeme(autre).statut == "validee"
    with pytest.raises(AccesRefuse):
        services.mettre_en_option(reserver(espace, date(2026, 12, 11), "18:00", "20:00"), acteur=agent("accueil"))


def test_rg07_option_relancee_puis_liberee(espace, django_capture_on_commit_callbacks):
    with freeze_time("2026-11-01 09:00"):
        r = services.mettre_en_option(
            reserver(espace, date(2026, 12, 10), "18:00", "20:00"), acteur=agent("gestionnaire"), jours=7
        )
    with freeze_time("2026-11-06 09:00"), django_capture_on_commit_callbacks(execute=True):
        assert services.traiter_options() == {"relancees": 1, "liberees": 0}
        assert services.traiter_options() == {"relancees": 0, "liberees": 0}
    assert "expire le" in mail.outbox[-1].body
    with freeze_time("2026-11-08 10:00"), django_capture_on_commit_callbacks(execute=True):
        assert services.traiter_options() == {"relancees": 0, "liberees": 1}
    r.refresh_from_db()
    assert r.statut == "annulee" and "Option expirée" in r.motif_annulation


# --- PLA-10 annulation, PLA-09 liste d'attente ------------------------------------------------------


def test_pla10_annulation_tardive_par_l_usager(espace):
    with freeze_time("2026-11-09 10:00"):
        r = valider_systeme(reserver(espace, date(2026, 11, 10), "18:00", "20:00"))
        contact = r.dossier.usager.rattachements.first().contact
        occurrence = services.annuler_occurrence(r.occurrences.get(), acteur=contact, motif="Match reporté", par_usager=True)
    assert occurrence.annulation_tardive and not occurrence.verrous.exists()
    with pytest.raises(AccesRefuse):
        services.annuler_occurrence(r.occurrences.get(), acteur="portail", motif="x", par_usager=False)
    with freeze_time("2026-11-01 10:00"):
        autre = valider_systeme(reserver(espace, date(2026, 11, 20), "18:00", "20:00"))
        assert not services.annuler_occurrence(
            autre.occurrences.get(), acteur=autre.dossier.usager.rattachements.first().contact, motif="x", par_usager=True
        ).annulation_tardive


def test_pla09_liste_d_attente_prevenue_a_la_liberation(espace, django_capture_on_commit_callbacks):
    with freeze_time("2026-11-01 10:00"):
        occupant = valider_systeme(reserver(espace, date(2026, 11, 20), "18:00", "20:00"))
        demandeur = usager_avec_contact()
        attente = services.inscrire_liste_attente(
            acteur=demandeur.rattachements.first().contact,
            espace=espace,
            debut=paris(2026, 11, 20, 18),
            fin=paris(2026, 11, 20, 20),
            usager=demandeur,
            portail=True,
        )
        with django_capture_on_commit_callbacks(execute=True):
            services.annuler_occurrence(occupant.occurrences.get(), acteur=agent("gestionnaire"), motif="Désistement")
    attente.refresh_from_db()
    assert attente.statut == "proposee" and any("libéré" in m.subject for m in mail.outbox)


# --- PLA-11 présence -----------------------------------------------------------------------------


def test_pla11_presence_et_absence_non_signalee(espace):
    with freeze_time("2026-11-01 10:00"):
        r = valider_systeme(reserver(espace, date(2026, 11, 10), "18:00", "20:00", type_code="scolaire"))
    with pytest.raises(ErreurMetier), freeze_time("2026-11-02 10:00"):
        services.saisir_presence(r.occurrences.get(), acteur=agent("gestionnaire"), presence="present")
    with freeze_time("2026-11-11 10:00"):
        o = services.saisir_presence(r.occurrences.get(), acteur=agent("gestionnaire"), presence="absent_non_signale")
    assert o.statut == "realisee" and o.presence == "absent_non_signale"


def test_pla06_seance_validee_non_confirmee_reste_a_regulariser(espace):
    """Une location validée mais jamais confirmée (RG-06) ne devient pas « réalisée » ni clôturable."""
    with freeze_time("2026-11-01 10:00"):
        r = valider_systeme(reserver(espace, date(2026, 11, 10), "18:00", "20:00", type_code="location"))
    with freeze_time("2026-11-11 10:00"):
        o = services.saisir_presence(r.occurrences.get(), acteur=agent("gestionnaire"), presence="present")
        assert o.statut == "validee" and "sans confirmation" in o.signalement
        assert services.marquer_realisees() == 0
        with pytest.raises(ErreurMetier) as refus:
            services.cloturer(r, acteur=agent("gestionnaire"))
    assert refus.value.code == "conditions_non_remplies"


# --- PLA-07 alternatives, PLA-12 priorité municipale, REF-06 fermeture --------------------------------


def test_pla07_alternatives_proposees_en_cas_de_conflit(espace):
    voisin = EspaceFabrique(batiment=espace.batiment, famille=espace.famille, nom="Gymnase annexe")
    with freeze_time("2026-11-01 10:00"):
        valider_systeme(reserver(espace, date(2026, 11, 10), "18:00", "20:00"))
        propositions = services.alternatives(espace, paris(2026, 11, 10, 18), paris(2026, 11, 10, 20))
    assert len(propositions) == 3
    assert any(p["espace"] == voisin.pk for p in propositions) or all(p["espace"] == espace.pk for p in propositions)
    assert all(
        not services.conflits(
            espace if p["espace"] == espace.pk else voisin, *(timezone.datetime.fromisoformat(p[k]) for k in ("debut", "fin"))
        )
        for p in propositions
    )


def test_pla12_priorite_municipale_deplace_et_notifie(espace, django_capture_on_commit_callbacks):
    autre_salle = EspaceFabrique(batiment=espace.batiment, famille=espace.famille)
    with freeze_time("2026-11-01 10:00"):
        club = valider_systeme(reserver(espace, date(2026, 11, 14), "14:00", "18:00"))
        seance = club.occurrences.get()
        ville = reserver(
            espace,
            date(2026, 11, 14),
            "10:00",
            "19:00",
            usager=UsagerFabrique(type="service_municipal", nom="Service des sports"),
        )
        with django_capture_on_commit_callbacks(execute=True):
            services.imposer_priorite_municipale(
                ville,
                acteur=agent("gestionnaire"),
                motif="Forum des associations",
                deplacements={seance.pk: (autre_salle, paris(2026, 11, 14, 14), paris(2026, 11, 14, 18))},
            )
    seance.refresh_from_db()
    assert seance.espace == autre_salle and seance.statut == "validee"
    ville.refresh_from_db()
    assert ville.statut == "validee"
    assert any("Forum des associations" in m.body for m in mail.outbox)


def test_pla12_reservee_aux_services_municipaux(espace):
    with pytest.raises(ErreurMetier):
        services.imposer_priorite_municipale(
            reserver(espace, date(2026, 11, 14), "10:00", "12:00"), acteur=agent("gestionnaire"), motif="x"
        )


def test_ref06_fermeture_signale_les_seances_et_previent_les_usagers(espace, django_capture_on_commit_callbacks):
    with freeze_time("2026-11-01 10:00"):
        r = valider_systeme(
            reserver(
                espace,
                date(2026, 11, 3),
                "18:00",
                "20:00",
                recurrence=MARDIS_SAISON,
                date_fin=date(2026, 11, 24),
                exclure_vacances=False,
            )
        )
        fermeture = Fermeture.objects.create(
            espace=espace, debut=paris(2026, 11, 9, 0), fin=paris(2026, 11, 18, 0), motif="Réfection du sol"
        )
        with django_capture_on_commit_callbacks(execute=True):
            touchees = services.enregistrer_fermeture(fermeture, acteur=agent("gestionnaire"))
    assert len(touchees) == 2 and all("Réfection" in o.signalement for o in touchees)
    assert len([m for m in mail.outbox if "Fermeture" in m.subject]) == 1
    assert r.occurrences.exclude(signalement="").count() == 2


# --- RG-03 priorités, ADM-02 paramètres ---------------------------------------------------------------


def test_rg03_ordre_des_priorites():
    saison_2026()
    seance = paris(2026, 11, 10, 10)
    ville = UsagerFabrique(type="service_municipal")
    ecole = UsagerFabrique(type="ecole")
    conventionnee = UsagerFabrique(type="association", local=True, conventionne=True)
    association = UsagerFabrique(type="association", local=False)
    entreprise = UsagerFabrique(type="entreprise")
    rangs = [rang_priorite(u, seance) for u in (ville, ecole, conventionnee, association, entreprise)]
    assert rangs == sorted(rangs) and len(set(rangs)) == 5
    assert rang_priorite(ecole, paris(2026, 11, 10, 19)) == rang_priorite(entreprise, seance)  # hors temps scolaire


def test_adm02_parametre_modifie_pris_en_compte(espace):
    Parametre.objects.create(cle="options.duree_jours", valeur=2)
    invalider()
    with freeze_time("2026-11-01 10:00"):
        r = services.mettre_en_option(reserver(espace, date(2026, 12, 10), "18:00", "20:00"), acteur=agent("gestionnaire"))
    assert r.option_expire_le == timezone.datetime(2026, 11, 3, 10, tzinfo=UTC)
