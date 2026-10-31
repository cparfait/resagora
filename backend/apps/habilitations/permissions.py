"""Permission DRF rôle × périmètre (RG-14) et double authentification obligatoire (SEC-03)."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from rest_framework import exceptions
from rest_framework.permissions import SAFE_METHODS, BasePermission
from rest_framework.request import Request

from .models import Utilisateur
from .services import peut

if TYPE_CHECKING:
    from rest_framework.views import APIView

CLE_SESSION_TOTP = "double_authentification_validee"


class DoubleAuthentificationRequise(exceptions.PermissionDenied):
    default_detail = "La double authentification est requise pour votre rôle."
    default_code = "double_authentification_requise"


def action_de_la_vue(vue: APIView, request: Request) -> str | None:
    """Action exigée : par nom d'action de viewset ou de méthode, sinon « lecture » / « ecriture »."""
    actions: dict[str, str] = getattr(vue, "actions_requises", {})
    nom = getattr(vue, "action", None) or (request.method or "get").lower()
    if nom in actions:
        return actions[nom]
    return actions.get("lecture" if request.method in SAFE_METHODS else "ecriture")


class ActionPermission(BasePermission):
    """La vue déclare `actions_requises` ; une action absente refuse par défaut."""

    def has_permission(self, request: Request, view: APIView) -> bool:
        utilisateur = request.user
        if not isinstance(utilisateur, Utilisateur) or not utilisateur.is_authenticated:
            raise exceptions.NotAuthenticated()
        if getattr(view, "sans_double_authentification", False) is False and utilisateur.exige_double_authentification():
            if not request.session.get(CLE_SESSION_TOTP):
                raise DoubleAuthentificationRequise()
        if getattr(view, "authentifie_seulement", False):
            return True
        action = action_de_la_vue(view, request)
        return action is not None and peut(utilisateur, action)

    def has_object_permission(self, request: Request, view: APIView, obj: Any) -> bool:
        if getattr(view, "authentifie_seulement", False):
            return True
        action = action_de_la_vue(view, request)
        utilisateur = request.user
        return action is not None and isinstance(utilisateur, Utilisateur) and peut(utilisateur, action, obj)
