"""PER-08, IMP-05 : flux iCalendar acceptés par Outlook (abonnement « à partir du web »)."""

from __future__ import annotations

from datetime import UTC, datetime

from apps.noyau import ical


def test_per08_flux_compatible_outlook_actualisation_et_disponibilite():
    contenu = ical.calendrier(
        "Planning — Camille Martin",
        [
            ical.Evenement(
                uid="v-1@equipements",
                debut=datetime(2026, 11, 10, 17, tzinfo=UTC),
                fin=datetime(2026, 11, 10, 21, tzinfo=UTC),
                resume="Gardiennage",
            ),
            ical.Evenement(
                uid="v-2@equipements",
                debut=datetime(2026, 11, 11, 17, tzinfo=UTC),
                fin=datetime(2026, 11, 11, 21, tzinfo=UTC),
                resume="Option",
                provisoire=True,
            ),
            ical.Evenement(
                uid="v-3@equipements",
                debut=datetime(2026, 11, 12, 17, tzinfo=UTC),
                fin=datetime(2026, 11, 12, 21, tzinfo=UTC),
                resume="Annulée",
                annule=True,
            ),
        ],
    ).decode()
    assert "METHOD:PUBLISH" in contenu and "X-WR-CALNAME:Planning — Camille Martin" in contenu
    assert "REFRESH-INTERVAL;VALUE=DURATION:PT1H" in contenu and "X-PUBLISHED-TTL:PT1H" in contenu
    assert "DTSTART:20261110T170000Z" in contenu, "heures en UTC : Outlook les affiche dans le fuseau du poste"
    for statut, occupation in (("CONFIRMED", "BUSY"), ("TENTATIVE", "TENTATIVE"), ("CANCELLED", "FREE")):
        assert f"STATUS:{statut}" in contenu and f"X-MICROSOFT-CDO-BUSYSTATUS:{occupation}" in contenu
