"""SEC-08 : journal d'audit à intégrité protégée ; ADM-05 : consultation et export."""

from __future__ import annotations

import pytest
from django.db import DatabaseError, connection, transaction

from apps.audit.models import JournalAudit
from apps.audit.services import audite, instantane, journaliser, verifier_chaine
from tests.fabriques import EspaceFabrique, SiteFabrique, agent

pytestmark = pytest.mark.django_db


def test_sec08_chaine_integre():
    site = SiteFabrique()
    for i in range(5):
        journaliser("essai", site, apres={"i": i})
    resultat = verifier_chaine()
    assert resultat.integre and resultat.entrees_verifiees >= 5


def test_sec08_modification_interdite_par_la_base():
    entree = journaliser("essai", SiteFabrique())
    with pytest.raises(DatabaseError), transaction.atomic():
        JournalAudit.objects.filter(pk=entree.pk).update(action="effacer_les_traces")
    with pytest.raises(DatabaseError), transaction.atomic():
        JournalAudit.objects.filter(pk=entree.pk).delete()


def test_sec08_alteration_detectee_meme_en_contournant_le_declencheur():
    site = SiteFabrique()
    premiere = journaliser("essai", site)
    journaliser("essai", site)
    with connection.cursor() as curseur:
        curseur.execute("SET LOCAL session_replication_role = replica")
        curseur.execute("UPDATE audit_journalaudit SET action = 'falsifie' WHERE id = %s", [premiere.pk])
        curseur.execute("SET LOCAL session_replication_role = origin")
    resultat = verifier_chaine()
    assert not resultat.integre
    assert any(str(premiere.pk) in anomalie for anomalie in resultat.anomalies)


def test_sec08_suppression_detectee():
    site = SiteFabrique()
    journaliser("essai", site)
    milieu = journaliser("essai", site)
    journaliser("essai", site)
    with connection.cursor() as curseur:
        curseur.execute("SET LOCAL session_replication_role = replica")
        curseur.execute("DELETE FROM audit_journalaudit WHERE id = %s", [milieu.pk])
        curseur.execute("SET LOCAL session_replication_role = origin")
    assert "chaînage rompu" in " ".join(verifier_chaine().anomalies)


def test_sec08_decorateur_audite_et_champs_sensibles_exclus():
    gestionnaire = agent("gestionnaire")

    @audite("renommer_site")
    def renommer(site, nom, acteur):
        site.nom = nom
        site.save()
        return site

    site = renommer(SiteFabrique(), "Stade municipal", acteur=gestionnaire)
    entree = JournalAudit.objects.filter(action="renommer_site").get()
    assert entree.acteur == gestionnaire and entree.apres["nom"] == "Stade municipal" and entree.objet_id == str(site.pk)
    journaliser("modifier_agent", gestionnaire, apres=instantane(gestionnaire))
    assert "password" not in (JournalAudit.objects.filter(action="modifier_agent").get().apres or {})


def test_sec08_ecritures_api_journalisees_avec_avant_apres(client_agent):
    gestionnaire = agent("gestionnaire")
    espace = EspaceFabrique(nom="Ancien nom")
    client_agent(gestionnaire).patch(f"/api/gestion/referentiel/espaces/{espace.pk}", {"nom": "Nouveau nom"}, format="json")
    entree = JournalAudit.objects.filter(action="modifier_espace").get()
    assert entree.avant["nom"] == "Ancien nom" and entree.apres["nom"] == "Nouveau nom"
    assert entree.acteur == gestionnaire and entree.canal == "gestion"


def test_adm05_consultation_filtree_et_export(client_agent):
    admin = agent("administrateur")
    gestionnaire = agent("gestionnaire")
    journaliser("action_du_gestionnaire", SiteFabrique(), acteur=gestionnaire)
    journaliser("action_de_l_admin", SiteFabrique(), acteur=admin)
    client = client_agent(admin)
    reponse = client.get("/api/gestion/audit/journal", {"acteur": gestionnaire.pk})
    assert reponse.status_code == 200
    assert {e["action"] for e in reponse.json()["results"]} == {"action_du_gestionnaire"}
    export = client.get("/api/gestion/audit/journal/export")
    assert export.status_code == 200 and export["Content-Type"].startswith("text/csv")
    assert "action_de_l_admin" in b"".join(export.streaming_content).decode()
    verification = client.get("/api/gestion/audit/journal/verification").json()
    assert verification["integre"] is True


def test_adm05_journal_refuse_sans_droit(client_agent):
    assert client_agent(agent("gestionnaire")).get("/api/gestion/audit/journal").status_code == 403
