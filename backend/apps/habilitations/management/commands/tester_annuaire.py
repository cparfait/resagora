"""Diagnostic de raccordement à l'Active Directory (docs/a-brancher.md) : liaison du compte de service,
puis recherche facultative d'un agent et affichage de ses groupes et des rôles correspondants."""

from __future__ import annotations

from typing import Any

from django.core.management.base import BaseCommand, CommandError

from apps.habilitations.ldap import Annuaire, AnnuaireIndisponible
from apps.habilitations.models import GroupeAD


class Command(BaseCommand):
    help = "Teste la connexion LDAPS à l'annuaire et, si un identifiant est donné, la lecture de ses groupes."

    def add_arguments(self, parser: Any) -> None:
        parser.add_argument("--identifiant", default="")

    def handle(self, *args: Any, **options: Any) -> None:
        annuaire = Annuaire()
        try:
            etat = annuaire.tester()
        except AnnuaireIndisponible as erreur:
            raise CommandError(f"Annuaire injoignable : {erreur}") from erreur
        self.stdout.write(f"Serveur {etat['serveur']} : liaison du compte de service réussie ({etat['qui']}).")
        if options["identifiant"]:
            entree = annuaire.rechercher(options["identifiant"])
            if entree is None:
                raise CommandError("Agent introuvable avec le filtre configuré.")
            self.stdout.write(f"Agent : {entree.dn} ({entree.prenom} {entree.nom}, {entree.courriel})")
            correspondances = {g.dn.lower(): g for g in GroupeAD.objects.filter(actif=True).select_related("role", "perimetre")}
            for dn in entree.groupes:
                groupe = correspondances.get(dn.lower())
                role = f"→ {groupe.role.libelle} sur {groupe.perimetre.nom}" if groupe else "(aucun rôle associé)"
                self.stdout.write(f"  groupe {dn} {role}")
