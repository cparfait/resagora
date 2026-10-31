"""Déconnexion des agents après inactivité, plus courte pour les rôles à double authentification (SEC-03)."""

from __future__ import annotations

import time
from collections.abc import Callable

from django.conf import settings
from django.contrib.auth import logout
from django.http import HttpRequest, HttpResponse

CLE_ACTIVITE = "derniere_activite"


class InactiviteMiddleware:
    def __init__(self, get_response: Callable[[HttpRequest], HttpResponse]):
        self.get_response = get_response

    def __call__(self, request: HttpRequest) -> HttpResponse:
        utilisateur = getattr(request, "user", None)
        if utilisateur is not None and utilisateur.is_authenticated and hasattr(utilisateur, "exige_double_authentification"):
            maintenant = time.time()
            minutes = (
                settings.SESSION_INACTIVITE_SENSIBLE_MINUTES
                if utilisateur.exige_double_authentification()
                else settings.SESSION_INACTIVITE_MINUTES
            )
            derniere = request.session.get(CLE_ACTIVITE)
            if derniere is not None and maintenant - float(derniere) > minutes * 60:
                logout(request)
            else:
                request.session[CLE_ACTIVITE] = maintenant
        return self.get_response(request)
