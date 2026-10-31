from __future__ import annotations

from collections.abc import Callable

import pytest
from django.core.cache import cache
from rest_framework.test import APIClient

from apps.habilitations.models import Utilisateur
from apps.habilitations.permissions import CLE_SESSION_TOTP


@pytest.fixture(scope="session")
def django_db_setup(django_db_setup, django_db_blocker):  # type: ignore[no-untyped-def]
    """Base de test : le vidage des tables immuables est autorisé (jamais en recette ni en production)."""
    from django.db import connection

    with django_db_blocker.unblock(), connection.cursor() as curseur:
        curseur.execute("SELECT current_database()")
        nom = curseur.fetchone()[0]
        curseur.execute(f"ALTER DATABASE \"{nom}\" SET equipements.truncate_autorise = 'oui'")
        curseur.execute("SET equipements.truncate_autorise = 'oui'")
    with django_db_blocker.unblock():
        from apps.noyau.amorcage import amorcer_donnees_de_reference

        # Une base réutilisée peut avoir été vidée par un test transactionnel : on recrée la référence.
        amorcer_donnees_de_reference()


@pytest.fixture(autouse=True)
def _vider_cache() -> None:
    cache.clear()


@pytest.fixture(autouse=True)
def _stockage(settings, tmp_path) -> None:  # type: ignore[no-untyped-def]
    settings.MEDIA_ROOT = tmp_path / "stockage"


@pytest.fixture
def client_api() -> APIClient:
    return APIClient()


@pytest.fixture
def client_agent() -> Callable[[Utilisateur], APIClient]:
    """Client connecté comme l'agent donné, double authentification validée."""

    def fabriquer(utilisateur: Utilisateur, totp_valide: bool = True) -> APIClient:
        client = APIClient()
        client.force_login(utilisateur, backend="apps.habilitations.ldap.LdapBackend")
        session = client.session
        session[CLE_SESSION_TOTP] = totp_valide
        session.save()
        return client

    return fabriquer
