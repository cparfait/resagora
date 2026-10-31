"""Sécurité du canal portail : vues servies uniquement par l'instance mTLS (SEC-01)."""

from __future__ import annotations

from typing import Any

from django.conf import settings
from rest_framework.permissions import BasePermission
from rest_framework.request import Request
from rest_framework.views import APIView


class CanalPortail(BasePermission):
    """Refuse toute vue portail servie hors de l'instance « portail » (défense en profondeur)."""

    def has_permission(self, request: Request, view: Any) -> bool:
        return settings.CANAL == "portail"


class VuePublique(APIView):
    """Base des vues publiques du portail : pas d'authentification, débit limité."""

    authentication_classes = ()
    permission_classes = (CanalPortail,)
    throttle_scope = "public"


class VueContact(APIView):
    """Base des vues réservées à un contact connecté (jeton de session relayé par la façade)."""

    permission_classes = (CanalPortail,)
    throttle_scope = "public"

    def get_authenticators(self) -> list[Any]:
        from .authentification import AuthentificationPortail

        return [AuthentificationPortail()]

    def get_permissions(self) -> list[Any]:
        from .authentification import ContactConnecte

        return [CanalPortail(), ContactConnecte()]
