"""Flux iCalendar (RFC 5545) des plannings : abonnement personnel des agents (PER-08) et export du planning d'un
espace (IMP-05). Bibliothèque `icalendar` : échappement et pliage des lignes conformes."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime

from django.utils import timezone
from icalendar import Calendar, Event


@dataclass
class Evenement:
    uid: str
    debut: datetime
    fin: datetime
    resume: str
    lieu: str = ""
    description: str = ""
    annule: bool = False


def calendrier(nom: str, evenements: list[Evenement]) -> bytes:
    cal = Calendar()
    cal.add("prodid", "-//Ville de Chatillon//Planning des equipements//FR")
    cal.add("version", "2.0")
    cal.add("calscale", "GREGORIAN")
    cal.add("method", "PUBLISH")
    cal.add("x-wr-calname", nom)
    cal.add("x-wr-timezone", "Europe/Paris")
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
        evenement.add("status", "CANCELLED" if e.annule else "CONFIRMED")
        cal.add_component(evenement)
    return cal.to_ical()
