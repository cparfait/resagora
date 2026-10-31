"""Amorçage des correspondances groupes AD → rôle × périmètre (ADM-06) depuis un fichier JSON.

Sert à la mise en service (premier administrateur) et à la recette ; ensuite, les correspondances se
gèrent dans l'écran « Groupes de l'annuaire ». Format :
[{"dn": "CN=...", "libelle": "...", "role": "gestionnaire", "perimetre": "Ville entière" | ["code-site", ...]}]
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any

from django.core.management.base import BaseCommand, CommandError
from django.db import transaction

from apps.audit.services import journaliser
from apps.habilitations.models import GroupeAD, Perimetre, Role
from apps.referentiel.models import Site


class Command(BaseCommand):
    help = "Crée ou met à jour les correspondances groupes AD → rôles à partir d'un fichier JSON."

    def add_arguments(self, parser: Any) -> None:
        parser.add_argument("fichier", help="Chemin du fichier JSON, ou « - » pour l'entrée standard.")

    @transaction.atomic
    def handle(self, *args: Any, **options: Any) -> None:
        if options["fichier"] == "-":
            contenu = sys.stdin.read()
        else:
            chemin = Path(options["fichier"])
            if not chemin.is_file():
                raise CommandError(f"Fichier introuvable : {chemin}")
            contenu = chemin.read_text(encoding="utf-8")
        for entree in json.loads(contenu):
            role = Role.objects.filter(code=entree["role"]).first()
            if role is None:
                raise CommandError(f"Rôle inconnu : {entree['role']}")
            perimetre_brut = entree["perimetre"]
            if isinstance(perimetre_brut, str):
                perimetre = Perimetre.objects.get(nom=perimetre_brut)
            else:
                sites = list(Site.objects.filter(code__in=perimetre_brut))
                if len(sites) != len(perimetre_brut):
                    raise CommandError(f"Sites inconnus dans {perimetre_brut}")
                perimetre, _ = Perimetre.objects.get_or_create(
                    nom=entree.get("nom_perimetre") or " + ".join(sorted(perimetre_brut))
                )
                perimetre.sites.set(sites)
            groupe, cree = GroupeAD.objects.update_or_create(
                dn=entree["dn"],
                defaults={"libelle": entree.get("libelle", ""), "role": role, "perimetre": perimetre, "actif": True},
            )
            journaliser(
                "amorcer_groupe_ad",
                groupe,
                apres={"role": role.code, "perimetre": perimetre.nom},
                acteur="commande amorcer_groupes_ad",
            )
            self.stdout.write(f"{'Créé' if cree else 'Mis à jour'} : {groupe.dn} → {role.libelle} sur {perimetre.nom}")
