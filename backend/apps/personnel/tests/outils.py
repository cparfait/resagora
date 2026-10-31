"""Aides de test du personnel : site gardienné, agent habilité SSIAP 1, séance validée."""

from __future__ import annotations

from datetime import date

from apps.personnel.models import Agent, HabilitationAgent, TypeHabilitation
from apps.referentiel.models import Site
from apps.reservations.tests.outils import reserver, valider_systeme
from tests.fabriques import EspaceFabrique, SiteFabrique, agent


def site_gardienne() -> tuple[Site, object]:
    site = SiteFabrique(nom="Complexe sportif du Parc")
    espace = EspaceFabrique(
        batiment__site=site, nom="Gymnase A", gardiennage_requis=True, temps_ouverture_min=15, temps_fermeture_min=15
    )
    return site, espace


def gardien(
    site: Site, *, nom: str = "Martin", habilite: bool = True, matricule: str | None = None, avec_compte: bool = True
) -> Agent:
    utilisateur = agent("gardien", username=f"gardien.{nom.lower()}") if avec_compte else None
    fiche = Agent.objects.create(
        utilisateur=utilisateur,
        matricule=matricule or f"M{nom.upper()[:6]}",
        prenom="Camille",
        nom=nom,
        courriel=f"{nom.lower()}@chatillon.test",
    )
    fiche.sites.add(site)
    if habilite:
        HabilitationAgent.objects.create(
            agent=fiche,
            type=TypeHabilitation.objects.get(code="ssiap1"),
            obtenue_le=date(2024, 1, 1),
            valide_jusqu_au=date(2027, 12, 31),
        )
    return fiche


def seance(espace, jour: date, debut: str = "18:00", fin: str = "20:00"):
    return valider_systeme(reserver(espace, jour, debut, fin)).occurrences.get()
