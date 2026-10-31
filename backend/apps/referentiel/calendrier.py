"""Calendrier des saisons (ADM-01) : vacances scolaires de la zone C et jours fériés.

- Vacances : jeu de données national « fr-en-calendrier-scolaire » (data.education.gouv.fr, API
  Explore v2.1), filtré sur la zone et l'académie paramétrées ; import possible depuis un fichier
  JSON de même format (poste sans accès Internet).
- Jours fériés : API calendrier.api.gouv.fr ; à défaut, calcul local (comput de Pâques), identique
  pour la métropole.
Les dates de fin publiées sont les dates de reprise des cours (exclues) ; un « pont » d'une journée
a des dates de début et de fin identiques.
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

import httpx
from django.conf import settings
from django.db import transaction

from apps.audit.services import journaliser
from apps.noyau.exceptions import ErreurValidation
from apps.noyau.parametres import parametre

from .models import PeriodeCalendrier, Saison

journal = logging.getLogger(__name__)
PARIS = ZoneInfo("Europe/Paris")
URL_VACANCES = "https://data.education.gouv.fr/api/explore/v2.1/catalog/datasets/fr-en-calendrier-scolaire/records"
URL_FERIES = "https://calendrier.api.gouv.fr/jours-feries/metropole/{annee}.json"


@dataclass(frozen=True)
class Periode:
    libelle: str
    debut: date
    fin: date  # incluse


def paques(annee: int) -> date:
    """Dimanche de Pâques (algorithme de Meeus/Jones/Butcher, calendrier grégorien)."""
    a, b, c = annee % 19, annee // 100, annee % 100
    d, e = b // 4, b % 4
    f = (b + 8) // 25
    g = (b - f + 1) // 3
    h = (19 * a + b - d - g + 15) % 30
    i, k = c // 4, c % 4
    ell = (32 + 2 * e + 2 * i - h - k) % 7
    m = (a + 11 * h + 22 * ell) // 451
    mois = (h + ell - 7 * m + 114) // 31
    jour = ((h + ell - 7 * m + 114) % 31) + 1
    return date(annee, mois, jour)


def feries_calcules(annee: int) -> dict[date, str]:
    p = paques(annee)
    return {
        date(annee, 1, 1): "1er janvier",
        p + timedelta(days=1): "Lundi de Pâques",
        date(annee, 5, 1): "1er mai",
        date(annee, 5, 8): "8 mai",
        p + timedelta(days=39): "Ascension",
        p + timedelta(days=50): "Lundi de Pentecôte",
        date(annee, 7, 14): "14 juillet",
        date(annee, 8, 15): "Assomption",
        date(annee, 11, 1): "Toussaint",
        date(annee, 11, 11): "11 novembre",
        date(annee, 12, 25): "Jour de Noël",
    }


class ClientCalendrier:
    def __init__(self, transport: httpx.BaseTransport | None = None):
        self.client = httpx.Client(timeout=15, transport=transport, follow_redirects=False)

    def feries(self, annee: int) -> dict[date, str]:
        url = getattr(settings, "URL_JOURS_FERIES", URL_FERIES).format(annee=annee)
        try:
            reponse = self.client.get(url)
            reponse.raise_for_status()
            return {date.fromisoformat(j): libelle for j, libelle in reponse.json().items()}
        except (httpx.HTTPError, ValueError) as erreur:
            journal.warning("Jours fériés : API indisponible (%s), calcul local", type(erreur).__name__)
            return feries_calcules(annee)

    def vacances(self, annee_scolaire: str) -> list[Periode]:
        zone, academie = parametre("calendrier.zone"), parametre("calendrier.academie")
        filtre = f'annee_scolaire="{annee_scolaire}" and zones="{zone}" and location="{academie}"'
        reponse = self.client.get(
            getattr(settings, "URL_CALENDRIER_SCOLAIRE", URL_VACANCES),
            params={"where": filtre, "limit": 100, "select": "description,start_date,end_date,population"},
        )
        reponse.raise_for_status()
        return periodes_depuis_open_data(reponse.json().get("results", []))


def _jour_local(horodatage: str) -> date:
    return datetime.fromisoformat(horodatage).astimezone(PARIS).date()


def periodes_depuis_open_data(enregistrements: list[dict[str, Any]]) -> list[Periode]:
    """Convertit les enregistrements open data ; pour l'été, la population « Élèves » prévaut."""
    par_libelle: dict[str, Periode] = {}
    for e in enregistrements:
        population = (e.get("population") or "-").strip()
        if population not in {"-", "Élèves"}:
            continue
        debut, reprise = _jour_local(e["start_date"]), _jour_local(e["end_date"])
        fin = debut if reprise <= debut else reprise - timedelta(days=1)
        libelle = str(e["description"]).strip()
        actuelle = par_libelle.get(libelle)
        if actuelle is None or population == "Élèves":
            par_libelle[libelle] = Periode(libelle, debut, fin)
    return sorted(par_libelle.values(), key=lambda p: p.debut)


def periodes_depuis_fichier(contenu: bytes) -> list[Periode]:
    """Lit un export JSON du jeu « fr-en-calendrier-scolaire » (objet `{"results": [...]}` ou liste d'enregistrements)."""
    try:
        donnees = json.loads(contenu.decode("utf-8"))
        enregistrements = donnees.get("results", []) if isinstance(donnees, dict) else donnees
        if not isinstance(enregistrements, list):
            raise TypeError
        return periodes_depuis_open_data(enregistrements)
    except (UnicodeDecodeError, json.JSONDecodeError, TypeError, KeyError, ValueError, AttributeError) as erreur:
        raise ErreurValidation(
            "Le fichier n'est pas un export JSON du calendrier scolaire (champs description, start_date, end_date attendus)."
        ) from erreur


@transaction.atomic
def importer_saison(
    saison: Saison, client: ClientCalendrier | None = None, fichier: Path | bytes | None = None, acteur: Any = None
) -> int:
    """Remplace les vacances et jours fériés importés de la saison ; les fermetures saisies sont conservées.

    `fichier` : export JSON du jeu open data (chemin ou contenu déposé), pour un poste sans accès Internet.
    """
    client = client or ClientCalendrier()
    if fichier is not None:
        contenu = fichier.read_bytes() if isinstance(fichier, Path) else fichier
        vacances = periodes_depuis_fichier(contenu)
    else:
        vacances = client.vacances(saison.annee_scolaire)
    saison.periodes.filter(source__in=["import", "calcul"]).delete()
    nombre = 0
    for periode in vacances:
        if periode.fin < saison.debut or periode.debut > saison.fin:
            continue
        PeriodeCalendrier.objects.create(
            saison=saison,
            nature="vacances",
            libelle=periode.libelle,
            debut=periode.debut,
            fin=periode.fin,
            source="import",
            zone=parametre("calendrier.zone"),
        )
        nombre += 1
    for annee in range(saison.debut.year, saison.fin.year + 1):
        for jour, libelle in client.feries(annee).items():
            if saison.debut <= jour <= saison.fin:
                PeriodeCalendrier.objects.create(
                    saison=saison, nature="ferie", libelle=libelle, debut=jour, fin=jour, source="calcul"
                )
                nombre += 1
    journaliser("importer_calendrier", saison, apres={"periodes": nombre}, acteur=acteur)
    return nombre


def jours_exclus(saison: Saison, vacances: bool = True, feries: bool = True) -> set[date]:
    """Jours sans occupation récurrente : vacances (zone C), fériés et fermetures de la Ville."""
    natures = ["fermeture_ville"] + (["vacances"] if vacances else []) + (["ferie"] if feries else [])
    jours: set[date] = set()
    for periode in saison.periodes.filter(nature__in=natures):
        courant = periode.debut
        while courant <= periode.fin:
            jours.add(courant)
            courant += timedelta(days=1)
    return jours


def est_vacances(jour: date) -> bool:
    return PeriodeCalendrier.objects.filter(nature="vacances", debut__lte=jour, fin__gte=jour).exists()


def est_ferie(jour: date) -> bool:
    return PeriodeCalendrier.objects.filter(nature="ferie", debut__lte=jour, fin__gte=jour).exists() or jour in feries_calcules(
        jour.year
    )
