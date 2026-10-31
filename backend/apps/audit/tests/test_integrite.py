"""SEC-08 : HMAC, troncature, vidage, purge tracée au-delà de 6 mois, ancrage ; ADM-05 : export sûr."""

from __future__ import annotations

from datetime import timedelta

import pytest
from django.db import DatabaseError, connection, transaction
from django.utils import timezone

from apps.audit.api import cellule_sure
from apps.audit.models import AncrageJournal, JournalAudit, PointControleJournal
from apps.audit.services import ancrer, journaliser, purger, verifier_chaine
from tests.fabriques import SiteFabrique, agent

pytestmark = pytest.mark.django_db


def _sql_sans_declencheur(requete: str, parametres: list[object]) -> None:
    with connection.cursor() as curseur:
        curseur.execute("SET LOCAL session_replication_role = replica")
        curseur.execute(requete, parametres)
        curseur.execute("SET LOCAL session_replication_role = origin")


def test_sec08_libelle_modifie_detecte():
    entree = journaliser("essai", SiteFabrique())
    _sql_sans_declencheur("UPDATE audit_journalaudit SET objet_libelle = 'autre' WHERE id = %s", [entree.pk])
    assert not verifier_chaine().integre


def test_sec08_chaine_non_recalculable_sans_la_cle(settings):
    journaliser("essai", SiteFabrique())
    settings.CLE_AUDIT = "une-autre-cle-que-celle-du-journal"
    assert not verifier_chaine().integre


def test_sec08_truncate_interdit_hors_base_de_test():
    journaliser("essai", SiteFabrique())
    with pytest.raises(DatabaseError), transaction.atomic(), connection.cursor() as curseur:
        curseur.execute("SET LOCAL equipements.truncate_autorise = 'non'")
        curseur.execute("TRUNCATE audit_journalaudit CASCADE")


def test_sec08_troncature_de_fin_detectee_par_l_ancrage():
    site = SiteFabrique()
    journaliser("essai", site)
    derniere = journaliser("essai", site)
    ancrer()
    assert verifier_chaine().integre
    _sql_sans_declencheur("DELETE FROM audit_journalaudit WHERE id = %s", [derniere.pk])
    resultat = verifier_chaine()
    assert not resultat.integre and "troncature" in " ".join(resultat.anomalies)


def test_sec08_ancrage_ecrit_dans_les_journaux_techniques(caplog):
    journaliser("essai", SiteFabrique())
    with caplog.at_level("INFO", logger="audit.ancrage"):
        ancrage = ancrer()
    assert ancrage is not None and f"id={ancrage.dernier_id}" in caplog.text
    with pytest.raises(DatabaseError), transaction.atomic():
        AncrageJournal.objects.filter(pk=ancrage.pk).delete()


def test_sec08_purge_respecte_six_mois_et_laisse_une_chaine_verifiable(tmp_path, settings):
    settings.AUDIT_CONSERVATION_JOURS = 183
    admin = agent("administrateur")
    with pytest.raises(ValueError):
        purger(timezone.now() - timedelta(days=30), admin, tmp_path)
    ancienne = journaliser("ancienne", SiteFabrique())
    _sql_sans_declencheur(
        "UPDATE audit_journalaudit SET horodatage = %s WHERE id = %s", [timezone.now() - timedelta(days=400), ancienne.pk]
    )
    # L'horodatage fait partie de l'empreinte : on recalcule celle de l'entrée « vieillie » pour simuler un journal ancien.
    from apps.audit.services import calculer_empreinte

    vieillie = JournalAudit.objects.get(pk=ancienne.pk)
    _sql_sans_declencheur(
        "UPDATE audit_journalaudit SET empreinte = %s WHERE id = %s", [calculer_empreinte(vieillie), ancienne.pk]
    )
    suivante = journaliser("recente", SiteFabrique())
    _sql_sans_declencheur(
        "UPDATE audit_journalaudit SET empreinte_precedente = %s WHERE id = %s", [calculer_empreinte(vieillie), suivante.pk]
    )
    recalculee = JournalAudit.objects.get(pk=suivante.pk)
    _sql_sans_declencheur(
        "UPDATE audit_journalaudit SET empreinte = %s WHERE id = %s", [calculer_empreinte(recalculee), suivante.pk]
    )
    point = purger(timezone.now() - timedelta(days=200), admin, tmp_path)
    assert point is not None and point.nombre == 1 and (tmp_path / f"journal-audit-{ancienne.pk}-{ancienne.pk}.jsonl").exists()
    assert not JournalAudit.objects.filter(pk=ancienne.pk).exists()
    assert PointControleJournal.objects.count() == 1
    assert verifier_chaine().integre


def test_adm05_export_neutralise_les_formules_et_est_journalise(client_agent):
    journaliser("essai", SiteFabrique(nom='=HYPERLINK("http://pirate")'))
    client = client_agent(agent("administrateur"))
    export = b"".join(client.get("/api/gestion/audit/journal/export").streaming_content).decode()
    assert "'=HYPERLINK" in export
    assert JournalAudit.objects.filter(action="exporter_journal_audit").exists()
    assert cellule_sure("+33") == "'+33" and cellule_sure("Stade") == "Stade"


def test_adm05_journal_exige_un_perimetre_ville_entiere(client_agent):
    from apps.habilitations.models import Habilitation, Role

    controleur = agent("controle_interne", SiteFabrique())
    assert client_agent(controleur).get("/api/gestion/audit/journal").status_code == 403
    Habilitation.objects.create(utilisateur=controleur, role=Role.objects.get(code="controle_interne"), perimetre_id=1)
    controleur.vider_cache_habilitations()
