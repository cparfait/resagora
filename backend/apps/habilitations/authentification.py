from __future__ import annotations

from rest_framework.authentication import SessionAuthentication
from rest_framework.request import Request

from .models import Utilisateur


class SessionAgentAuthentication(SessionAuthentication):
    """Session Django des agents (cookie HttpOnly), CSRF imposé sur les écritures."""

    def authenticate(self, request: Request) -> tuple[Utilisateur, None] | None:
        resultat = super().authenticate(request)
        if resultat is None:
            return None
        utilisateur = resultat[0]
        if not isinstance(utilisateur, Utilisateur) or not utilisateur.is_active:
            return None
        return utilisateur, None

    def authenticate_header(self, request: Request) -> str:
        return 'Session realm="gestion"'


def agent_courant(request: Request) -> Utilisateur:
    """Agent authentifié de la requête (lève 401 sinon) ; typé pour le reste du code."""
    utilisateur = request.user
    if not isinstance(utilisateur, Utilisateur) or not utilisateur.is_authenticated:
        from rest_framework.exceptions import NotAuthenticated

        raise NotAuthenticated()
    return utilisateur
