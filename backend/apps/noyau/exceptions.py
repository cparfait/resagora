"""Erreurs : message neutre et en français côté client, détail dans les journaux (SEC-05)."""

from __future__ import annotations

import logging
from typing import Any

from django.core.exceptions import PermissionDenied
from django.core.exceptions import ValidationError as DjangoValidationError
from django.db import IntegrityError
from django.http import Http404
from rest_framework import exceptions, status
from rest_framework.response import Response

journal = logging.getLogger(__name__)


class ErreurMetier(Exception):
    """Règle de gestion non respectée : message lisible par l'agent ou l'usager."""

    statut_http: int = status.HTTP_409_CONFLICT

    def __init__(self, message: str, code: str = "regle_metier", details: dict[str, Any] | None = None):
        super().__init__(message)
        self.message = message
        self.code = code
        self.details = details or {}


class ErreurValidation(ErreurMetier):
    statut_http: int = status.HTTP_400_BAD_REQUEST


class AccesRefuse(ErreurMetier):
    statut_http: int = status.HTTP_403_FORBIDDEN


MESSAGES = {
    401: "Vous devez vous connecter.",
    403: "Vous n'avez pas les droits pour cette action.",
    404: "Élément introuvable.",
    405: "Action non autorisée.",
    429: "Trop de tentatives. Réessayez dans quelques minutes.",
}


def gestionnaire_exceptions(exc: Exception, contexte: dict[str, Any]) -> Response | None:
    from rest_framework.views import exception_handler

    if isinstance(exc, ErreurMetier):
        return Response({"code": exc.code, "message": exc.message, "details": exc.details}, status=exc.statut_http)
    if isinstance(exc, DjangoValidationError):
        return Response({"code": "validation", "message": " ".join(exc.messages)}, status=400)
    if isinstance(exc, IntegrityError):
        journal.warning("Contrainte d'intégrité : %s", exc)
        return Response({"code": "conflit", "message": "L'opération entre en conflit avec des données existantes."}, status=409)
    if isinstance(exc, Http404):
        exc = exceptions.NotFound()
    elif isinstance(exc, PermissionDenied):
        exc = exceptions.PermissionDenied()
    reponse = exception_handler(exc, contexte)
    if reponse is None:
        journal.exception("Erreur non gérée", exc_info=exc)
        return Response({"code": "erreur", "message": "Une erreur est survenue. Réessayez plus tard."}, status=500)
    if isinstance(exc, exceptions.ValidationError):
        reponse.data = {"code": "validation", "message": "Certains champs sont invalides.", "champs": reponse.data}
    elif isinstance(exc, exceptions.APIException):
        codes = exc.get_codes()
        code = codes if isinstance(codes, str) else "erreur"
        message = MESSAGES.get(reponse.status_code, str(exc.detail))
        if reponse.status_code == 403 and code not in {"permission_denied", "not_authenticated"}:
            message = str(exc.detail)
        reponse.data = {"code": code, "message": message}
    return reponse
