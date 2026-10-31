"""Contrôles avant mise en service (job de migration) : base, migrations, réglages de sécurité, secrets."""

from __future__ import annotations

from typing import Any

from django.conf import settings
from django.core.management import call_command
from django.core.management.base import BaseCommand, CommandError
from django.db import connection
from django.db.migrations.executor import MigrationExecutor


class Command(BaseCommand):
    help = "Vérifie que l'instance est prête : base joignable, migrations appliquées, réglages sûrs."

    def handle(self, *args: Any, **options: Any) -> None:
        erreurs: list[str] = []
        with connection.cursor() as curseur:
            curseur.execute("SELECT extname FROM pg_extension")
            extensions = {ligne[0] for ligne in curseur.fetchall()}
        if "btree_gist" not in extensions:
            erreurs.append("Extension PostgreSQL btree_gist absente (contrainte anti-chevauchement RG-01).")
        executeur = MigrationExecutor(connection)
        if executeur.migration_plan(executeur.loader.graph.leaf_nodes()):
            erreurs.append("Des migrations ne sont pas appliquées.")
        if settings.DEBUG:
            erreurs.append("DEBUG est actif.")
        if len(settings.SECRET_KEY) < 50:
            erreurs.append("Secret django_secret_key trop court.")
        if not settings.SESSION_COOKIE_SECURE or not settings.CSRF_COOKIE_SECURE:
            erreurs.append("Cookies non sécurisés.")
        if not settings.LDAP["VERIFIER_CERTIFICAT"]:
            erreurs.append("La vérification du certificat de l'annuaire est désactivée (LDAP_VERIFIER_CERTIFICAT).")
        if not str(settings.LDAP["URI"]).startswith("ldaps://") and not settings.LDAP["STARTTLS"]:
            erreurs.append("L'annuaire doit être joint en LDAPS ou en StartTLS.")
        erreurs += controles_production()
        call_command("check", "--deploy", "--fail-level", "ERROR")
        if erreurs:
            raise CommandError(" ; ".join(erreurs))
        self.stdout.write(self.style.SUCCESS("Instance prête."))


def _https_hors_simulateur(nom: str, url: str) -> str | None:
    if not url.startswith("https://"):
        return f"{nom} doit être une adresse HTTPS ({url or 'absente'})."
    if "simulateur" in url:
        return f"{nom} vise un simulateur de recette."
    return None


def controles_production() -> list[str]:
    """Revue sécurité du lot 2 (M9) : aucun réglage de recette n'arrive en production sans erreur."""
    import os

    if settings.RECETTE:
        return []
    erreurs = []
    debits = settings.REST_FRAMEWORK["DEFAULT_THROTTLE_RATES"]
    erreurs += [
        f"Seuil de débit « {cle} » modifié ({debits.get(cle)} au lieu de {defaut}) : réservé à la recette."
        for cle, defaut in settings.DEBITS_PAR_DEFAUT.items()
        if debits.get(cle) != defaut
    ]
    if settings.SIGNATURE_MODE == "docuseal":
        erreurs.append(_https_hors_simulateur("DOCUSEAL_URL", settings.DOCUSEAL_URL) or "")
        erreurs.append(_https_hors_simulateur("DOCUSEAL_URL_PUBLIQUE", settings.DOCUSEAL_URL_PUBLIQUE) or "")
        if not settings.DOCUSEAL_VERIFIER_TLS:
            erreurs.append("DOCUSEAL_VERIFIER_TLS est désactivé.")
    if os.environ.get("SMS_ADAPTATEUR", "desactive") == "http":
        erreurs.append(_https_hors_simulateur("SMS_URL", os.environ.get("SMS_URL", "")) or "")
    erreurs.append(_https_hors_simulateur("PORTAIL_URL", settings.PORTAIL_URL) or "")
    return [e for e in erreurs if e]
