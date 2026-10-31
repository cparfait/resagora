"""IMP-02 (planning PDF d'un agent ou d'un site) et IMP-05 (planning d'un espace en iCal), droits compris."""

from __future__ import annotations

import io
from datetime import date, datetime, time

import pytest
from docx import Document as DocumentWord

from apps.documents import gotenberg, impression
from apps.personnel import services
from apps.personnel.models import Vacation
from apps.reservations.recurrence import PARIS
from tests.fabriques import agent

from .outils import gardien, seance, site_gardienne

pytestmark = pytest.mark.django_db
JOUR = date(2026, 11, 10)
PDF = b"%PDF-1.7 planning"


@pytest.fixture
def documents_convertis(monkeypatch):
    convertis: list[bytes] = []

    def convertir(nom, docx, transport=None):
        convertis.append(docx)
        return PDF

    monkeypatch.setattr(gotenberg, "convertir_en_pdfa", convertir)
    return convertis


def _texte(docx: bytes) -> str:
    document = DocumentWord(io.BytesIO(docx))
    morceaux = [p.text for p in document.paragraphs]
    for table in document.tables:
        morceaux += [c.text for ligne in table.rows for c in ligne.cells]
    return "\n".join(morceaux)


def _vacation(site, debut: int, fin: int) -> Vacation:
    return Vacation.objects.create(
        site=site,
        debut=datetime.combine(JOUR, time(debut), tzinfo=PARIS),
        fin=datetime.combine(JOUR, time(fin), tzinfo=PARIS),
    )


def test_imp02_planning_pdf_d_un_gardien(client_agent, documents_convertis):
    site, _espace = site_gardienne()
    martin = gardien(site)
    services.affecter(_vacation(site, 17, 22), martin, acteur="système")
    reponse = client_agent(agent("planificateur", site)).get(
        "/api/gestion/personnel/vacations/planning-pdf", {"agent": martin.pk, "du": "2026-11-09", "au": "2026-11-15"}
    )
    assert reponse.status_code == 200 and reponse["Content-Type"] == "application/pdf" and reponse.content == PDF
    texte = _texte(documents_convertis[0])
    assert "Camille Martin" in texte and "Mardi 10/11/2026" in texte and "17:00 – 22:00" in texte
    assert "Édité le" in texte and "version en ligne" in texte.lower()


def test_imp02_planning_pdf_d_un_site_signale_les_vacations_non_couvertes(client_agent, documents_convertis):
    site, _espace = site_gardienne()
    _vacation(site, 8, 12)
    reponse = client_agent(agent("planificateur")).get(
        "/api/gestion/personnel/vacations/planning-pdf", {"site": site.pk, "du": "2026-11-09", "au": "2026-11-15", "papier": "A3"}
    )
    assert reponse.status_code == 200
    assert "NON COUVERTE" in _texte(documents_convertis[0])


def test_imp02_planning_pdf_refuse_hors_perimetre_et_sans_cible(client_agent, documents_convertis):
    site, _espace = site_gardienne()
    autre, _ = site_gardienne()
    martin = gardien(site)
    hors = client_agent(agent("planificateur", autre))
    assert (
        hors.get(
            "/api/gestion/personnel/vacations/planning-pdf", {"site": site.pk, "du": "2026-11-09", "au": "2026-11-15"}
        ).status_code
        == 403
    )
    assert (
        hors.get(
            "/api/gestion/personnel/vacations/planning-pdf", {"agent": martin.pk, "du": "2026-11-09", "au": "2026-11-15"}
        ).status_code
        == 403
    )
    assert (
        client_agent(agent("accueil"))
        .get("/api/gestion/personnel/vacations/planning-pdf", {"site": site.pk, "du": "2026-11-09", "au": "2026-11-15"})
        .status_code
        == 403
    )
    assert (
        client_agent(agent("planificateur"))
        .get("/api/gestion/personnel/vacations/planning-pdf", {"du": "2026-11-09", "au": "2026-11-15"})
        .status_code
        == 400
    )
    assert not documents_convertis


def test_imp_format_inconnu_refuse():
    with pytest.raises(Exception, match="A4 ou A3"):
        impression.construire_docx(impression.Edition(titre="t", sous_titre="s", entetes=["a"], lignes=[], format_papier="A0"))


def test_imp05_planning_d_un_espace_en_ical(client_agent):
    site, espace = site_gardienne()
    occurrence = seance(espace, JOUR, "18:00", "20:00")
    reponse = client_agent(agent("gestionnaire", site)).get(
        "/api/gestion/reservations/planning.ics", {"espace": espace.pk, "du": "2026-11-01", "au": "2026-11-30"}
    )
    assert reponse.status_code == 200 and reponse["Content-Type"].startswith("text/calendar")
    assert f"UID:seance-{occurrence.pk}@equipements.chatillon".encode() in reponse.content
    assert b"DTSTART:20261110T170000Z" in reponse.content
    autre, _ = site_gardienne()
    refus = client_agent(agent("gestionnaire", autre)).get("/api/gestion/reservations/planning.ics", {"espace": espace.pk})
    assert refus.status_code == 403
