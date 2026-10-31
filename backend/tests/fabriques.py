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
