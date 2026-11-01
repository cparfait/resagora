"""Jeu de démonstration : les données d'exemple de CityResa (sites, espaces, usagers, réservations — voir
`cityresa.py`), la saison 2026-2027 et son calendrier scolaire.

Aucune donnée personnelle réelle : les contacts des associations sont générés (graine fixe), ceux des usagers
inventés par CityResa sont fictifs. Chaque lot ajoute sa partie (finances, personnel, matériel, valorisation).
"""

from __future__ import annotations

import json
import random
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import date, timedelta
from pathlib import Path
from typing import Any

from django.utils import timezone

from apps.noyau import fichiers
from apps.noyau.demo import cityresa
from apps.referentiel.calendrier import feries_calcules, periodes_depuis_open_data
from apps.referentiel.models import Espace, PeriodeCalendrier, Saison, Site
from apps.reservations import services
from apps.reservations.models import Campagne
from apps.usagers.models import Contact, PieceJustificative, TypePiece, Usager

PRENOMS = [
    "Camille",
    "Dominique",
    "Claude",
    "Alix",
    "Sacha",
    "Lou",
    "Noa",
    "Eden",
    "Maxime",
    "Charlie",
    "Andrea",
    "Jordan",
    "Morgan",
    "Alexis",
    "Lilou",
    "Hugo",
    "Inès",
    "Léo",
    "Manon",
    "Nathan",
    "Chloé",
    "Louis",
    "Emma",
    "Jules",
    "Léa",
    "Gabriel",
    "Sarah",
    "Adam",
]
NOMS = [
    "Martin",
    "Bernard",
    "Thomas",
    "Petit",
    "Robert",
    "Richard",
    "Durand",
    "Dubois",
    "Moreau",
    "Laurent",
    "Simon",
    "Michel",
    "Lefebvre",
    "Leroy",
    "Roux",
    "David",
    "Bertrand",
    "Morel",
    "Fournier",
    "Girard",
    "Bonnet",
    "Dupont",
    "Lambert",
    "Fontaine",
    "Rousseau",
    "Vincent",
]
VOIES = [
    "rue des Tilleuls",
    "avenue des Peupliers",
    "rue du Moulin",
    "allée des Acacias",
    "rue de la Fontaine",
    "boulevard des Sports",
    "rue des Écoles",
]


class Generateur:
    """Coordonnées fictives reproductibles (aucune donnée réelle)."""

    def __init__(self, graine: int):
        self.alea = random.Random(graine)

    def first_name(self) -> str:
        return self.alea.choice(PRENOMS)

    def last_name(self) -> str:
        return self.alea.choice(NOMS)

    def street_address(self) -> str:
        return f"{self.alea.randint(1, 120)} {self.alea.choice(VOIES)}"

    def phone_number(self) -> str:
        return "01 99 " + " ".join(f"{self.alea.randint(0, 99):02d}" for _ in range(3))


SYSTEME = services.SYSTEME
#: Parties du jeu ajoutées par les lots suivants (finances, personnel, matériel, valorisation).
EXTENSIONS: list[Callable[[dict[str, Any]], dict[str, int]]] = []
PDF_DEMO = b"%PDF-1.4\n1 0 obj<</Type/Catalog/Pages 2 0 R>>endobj 2 0 obj<</Type/Pages/Kids[]/Count 0>>endobj\ntrailer<</Root 1 0 R>>\n%%EOF\n"


@dataclass
class Bilan:
    compteurs: dict[str, int] = field(default_factory=dict)

    def ajouter(self, cle: str, nombre: int = 1) -> None:
        self.compteurs[cle] = self.compteurs.get(cle, 0) + nombre


def deja_charge() -> bool:
    return Site.objects.filter(code__startswith="demo-").exists()


def _luhn_valide(numero: str) -> bool:
    total = 0
    for rang, chiffre in enumerate(reversed(numero)):
        valeur = int(chiffre) * (2 if rang % 2 else 1)
        total += valeur - 9 if valeur > 9 else valeur
    return total % 10 == 0


def siret_fictif() -> str:
    """SIRET de démonstration volontairement invalide (clé de Luhn fausse) : jamais celui d'une entreprise réelle."""
    while True:
        numero = f"99{random.randint(10**11, 10**12 - 1)}"
        if not _luhn_valide(numero):
            return numero


def saison(bilan: Bilan) -> Saison:
    s = Saison.objects.create(nom="2026-2027", debut=date(2026, 9, 1), fin=date(2027, 7, 3), active=True)
    donnees = json.loads((Path(__file__).parent / "calendrier-zone-c-2026-2027.json").read_text(encoding="utf-8"))
    for p in periodes_depuis_open_data(donnees["results"]):
        if p.fin >= s.debut and p.debut <= s.fin:
            PeriodeCalendrier.objects.create(
                saison=s, nature="vacances", libelle=p.libelle, debut=p.debut, fin=p.fin, source="import", zone="Zone C"
            )
    for annee in (2026, 2027):
        for jour, libelle in feries_calcules(annee).items():
            if s.debut <= jour <= s.fin:
                PeriodeCalendrier.objects.create(saison=s, nature="ferie", libelle=libelle, debut=jour, fin=jour, source="calcul")
    Saison.objects.create(nom="2027-2028", debut=date(2027, 9, 1), fin=date(2028, 7, 1), active=False)
    bilan.ajouter("periodes_calendrier", s.periodes.count())
    return s


def _contact(faux: Generateur, domaine: str) -> Contact:
    prenom, nom = faux.first_name(), faux.last_name()
    identifiant = f"{prenom}.{nom}".lower().replace(" ", "-").replace("'", "")
    return Contact.objects.create(prenom=prenom, nom=nom, courriel=f"{identifiant}@{domaine}", telephone=faux.phone_number())


def _pieces_valides(usager: Usager) -> None:
    for type_piece in TypePiece.objects.filter(types_usager__contains=[usager.type], obligatoire=True):
        fichier = fichiers.enregistrer_genere(
            f"{type_piece.code}.pdf", PDF_DEMO, "application/pdf", depose_par="jeu de démonstration"
        )
        fin = date(2027, 9, 30) if type_piece.validite_mois else None
        PieceJustificative.objects.create(
            usager=usager, type_piece=type_piece, fichier=fichier, statut="valide", valide_jusqu_au=fin, verifie_le=timezone.now()
        )


def existant() -> dict[str, Any]:
    """Jeu déjà chargé : mêmes clés que `charger`, relues en base, pour compléter avec les lots suivants."""
    sites = Site.objects.filter(code__startswith="demo-")
    espaces = {e.code: e for e in Espace.objects.filter(batiment__site__in=sites).select_related("famille")}
    par_type: dict[str, list[Usager]] = {
        t: [] for t in ("association", "ecole", "entreprise", "particulier", "service_municipal")
    }
    for u in Usager.objects.filter(dossiers__reservations__espace__in=espaces.values()).distinct().order_by("pk"):
        par_type.setdefault(u.type, []).append(u)
    return {"bilan": {}, "espaces": espaces, "usagers": par_type, "saison": Saison.objects.get(nom="2026-2027")}


def charger(graine: int = 92320) -> dict[str, Any]:
    random.seed(graine)
    faux = Generateur(graine)
    bilan = Bilan()
    d = cityresa.donnees()
    espaces = cityresa.referentiel(d, bilan)
    s = saison(bilan)
    par_type, par_cle = cityresa.usagers(d, bilan, faux, _contact, _pieces_valides)
    materiels = cityresa.reservations(d, bilan, espaces, par_cle, s)
    aujourd_hui = timezone.localdate()
    Campagne.objects.create(
        saison=Saison.objects.get(nom="2027-2028"),
        nom="Créneaux annuels 2027-2028",
        ouverture=aujourd_hui,
        cloture=aujourd_hui + timedelta(days=60),
        statut="ouverte",
    )
    return {
        "bilan": bilan.compteurs,
        "espaces": espaces,
        "usagers": par_type,
        "saison": s,
        "cityresa": d,
        "materiels_demandes": materiels,
    }
