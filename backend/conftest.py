from __future__ import annotations

from collections.abc import Callable

import pytest
from django.core.cache import cache
from rest_framework.test import APIClient

from apps.habilitations.models import Utilisateur
from apps.habilitations.permissions import CLE_SESSION_TOTP


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
