"""Fabriques de test : aucune donnée personnelle réelle (Faker fr_FR)."""

from __future__ import annotations

import factory
from factory.django import DjangoModelFactory

from apps.habilitations.models import Habilitation, Perimetre, Role, Utilisateur
from apps.referentiel.models import Batiment, Espace, FamilleEspace, Site

factory.Faker._DEFAULT_LOCALE = "fr_FR"


class SiteFabrique(DjangoModelFactory):
    class Meta:
        model = Site

    code = factory.Sequence(lambda n: f"site-{n}")
    nom = factory.Sequence(lambda n: f"Complexe sportif {n}")
    adresse = factory.Faker("street_address")


class BatimentFabrique(DjangoModelFactory):
    class Meta:
        model = Batiment

    site = factory.SubFactory(SiteFabrique)
    nom = factory.Sequence(lambda n: f"Bâtiment {n}")


class EspaceFabrique(DjangoModelFactory):
    class Meta:
        model = Espace

    batiment = factory.SubFactory(BatimentFabrique)
    famille = factory.LazyFunction(lambda: FamilleEspace.objects.get(code="gymnase"))
    code = factory.Sequence(lambda n: f"espace-{n}")
    nom = factory.Sequence(lambda n: f"Salle {n}")
    capacite = 100
    surface_m2 = 400


class UtilisateurFabrique(DjangoModelFactory):
    class Meta:
        model = Utilisateur
        django_get_or_create = ("username",)

    username = factory.Sequence(lambda n: f"agent{n}")
    first_name = factory.Faker("first_name")
    last_name = factory.Faker("last_name")
    email = factory.LazyAttribute(lambda o: f"{o.username}@exemple.test")


def perimetre_sites(*sites: Site, nom: str | None = None) -> Perimetre:
    perimetre = Perimetre.objects.create(nom=nom or "Périmètre " + "-".join(str(s.pk) for s in sites))
    perimetre.sites.set(sites)
    return perimetre


def ville_entiere() -> Perimetre:
    return Perimetre.objects.get(nom="Ville entière")


def agent(role: str, *sites: Site, username: str | None = None, **champs: object) -> Utilisateur:
    """Agent habilité sur les sites donnés (ou toute la Ville si aucun site)."""
    utilisateur = UtilisateurFabrique(**({"username": username} if username else {}), **champs)
    perimetre = perimetre_sites(*sites) if sites else ville_entiere()
    Habilitation.objects.create(utilisateur=utilisateur, role=Role.objects.get(code=role), perimetre=perimetre)
    utilisateur.vider_cache_habilitations()
    return utilisateur


# --- Lot 1 : usagers, saisons, réservations -------------------------------------------------------

import datetime as _dt  # noqa: E402

from apps.referentiel.models import PeriodeCalendrier, Saison  # noqa: E402
from apps.usagers.models import Contact, Rattachement, Usager  # noqa: E402


class UsagerFabrique(DjangoModelFactory):
    class Meta:
        model = Usager

    type = "association"
    nom = factory.Sequence(lambda n: f"Association sportive {n}")
    commune = "Châtillon"
    local = True
    statut = "valide"


class ContactFabrique(DjangoModelFactory):
    class Meta:
        model = Contact

    prenom = factory.Faker("first_name")
    nom = factory.Faker("last_name")
    courriel = factory.Sequence(lambda n: f"contact{n}@exemple.test")


def usager_avec_contact(**champs: object) -> Usager:
    usager = UsagerFabrique(**champs)
    Rattachement.objects.create(usager=usager, contact=ContactFabrique(), role="president", principal=True, peut_signer=True)
    return usager


def saison_2026(vacances: bool = True) -> Saison:
    """Saison 2026-2027 avec les vacances de la zone C (académie de Versailles) publiées en open data."""
    saison, _ = Saison.objects.get_or_create(nom="2026-2027", defaults={"debut": _dt.date(2026, 9, 1), "fin": _dt.date(2027, 6, 30), "active": True})
    if vacances and not saison.periodes.exists():
        for libelle, debut, fin in [
            ("Vacances de la Toussaint", _dt.date(2026, 10, 17), _dt.date(2026, 11, 1)),
            ("Vacances de Noël", _dt.date(2026, 12, 19), _dt.date(2027, 1, 3)),
            ("Vacances d'Hiver", _dt.date(2027, 2, 6), _dt.date(2027, 2, 21)),
            ("Vacances de Printemps", _dt.date(2027, 4, 3), _dt.date(2027, 4, 18)),
            ("Pont de l'Ascension", _dt.date(2027, 5, 7), _dt.date(2027, 5, 7)),
        ]:
            PeriodeCalendrier.objects.create(saison=saison, nature="vacances", libelle=libelle, debut=debut, fin=fin, source="import", zone="Zone C")
    return saison
