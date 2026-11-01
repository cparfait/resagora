"""Flux iCalendar (RFC 5545) des plannings, au format qu'Outlook importe et auquel il s'abonne (« Ajouter un
calendrier → S'abonner à partir du web ») : abonnement personnel des agents (PER-08), plannings d'un espace, d'un
site ou d'un usager (IMP-05). Heures en UTC (Outlook les affiche dans le fuseau du poste), statut confirmé,
provisoire ou annulé, disponibilité « occupé » ou « provisoire » pour Outlook, intervalle d'actualisation d'une heure.
Bibliothèque `icalendar` : échappement et pliage des lignes conformes."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from django.utils import timezone
from icalendar import Calendar, Event, vDuration

ACTUALISATION = timedelta(hours=1)


@dataclass
class Evenement:
    uid: str
    debut: datetime
    fin: datetime
    resume: str
    lieu: str = ""
    description: str = ""
    annule: bool = False
    provisoire: bool = False
    categorie: str = ""


def calendrier(nom: str, evenements: list[Evenement], *, description: str = "") -> bytes:
    cal = Calendar()
    cal.add("prodid", "-//Ville de Chatillon//Planning des equipements//FR")
    cal.add("version", "2.0")
    cal.add("calscale", "GREGORIAN")
    cal.add("method", "PUBLISH")
    cal.add("x-wr-calname", nom)
    cal.add("x-wr-timezone", "Europe/Paris")
    if description:
        cal.add("x-wr-caldesc", description)
    # Outlook, Google Agenda et Thunderbird relisent l'abonnement à cet intervalle.
    cal.add("refresh-interval", vDuration(ACTUALISATION), parameters={"VALUE": "DURATION"})
    cal.add("x-published-ttl", vDuration(ACTUALISATION))
    horodatage = timezone.now().astimezone(UTC)
    for e in evenements:
        evenement = Event()
        evenement.add("uid", e.uid)
        evenement.add("dtstamp", horodatage)
        evenement.add("dtstart", e.debut.astimezone(UTC))
        evenement.add("dtend", e.fin.astimezone(UTC))
        evenement.add("summary", e.resume)
        if e.lieu:
            evenement.add("location", e.lieu)
        if e.description:
            evenement.add("description", e.description)
        if e.categorie:
            evenement.add("categories", [e.categorie])
        statut = "CANCELLED" if e.annule else "TENTATIVE" if e.provisoire else "CONFIRMED"
        evenement.add("status", statut)
        evenement.add("transp", "TRANSPARENT" if e.annule else "OPAQUE")
        evenement.add("x-microsoft-cdo-busystatus", "FREE" if e.annule else "TENTATIVE" if e.provisoire else "BUSY")
        cal.add_component(evenement)
    return cal.to_ical()
