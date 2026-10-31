from __future__ import annotations

import uuid
from collections.abc import Callable

from django.conf import settings
from django.http import HttpRequest, HttpResponse

from .contexte import ContexteAudit, definir_contexte, reinitialiser


def adresse_client(request: HttpRequest) -> str | None:
    """Adresse du client : la dernière adresse ajoutée par le proxy de confiance, sinon REMOTE_ADDR."""
    transmise = request.META.get("HTTP_X_FORWARDED_FOR", "")
    nombre_proxies = int(settings.REST_FRAMEWORK.get("NUM_PROXIES") or 0)
    if transmise and nombre_proxies:
        adresses = [a.strip() for a in transmise.split(",") if a.strip()]
        if adresses:
            return adresses[-min(int(nombre_proxies), len(adresses))]
    return request.META.get("REMOTE_ADDR")


class ContexteAuditMiddleware:
    def __init__(self, get_response: Callable[[HttpRequest], HttpResponse]):
        self.get_response = get_response

    def __call__(self, request: HttpRequest) -> HttpResponse:
        utilisateur = getattr(request, "user", None)
        authentifie = bool(utilisateur and utilisateur.is_authenticated)
        jeton = definir_contexte(
            ContexteAudit(
                acteur_id=utilisateur.pk if authentifie and utilisateur else None,
                acteur_libelle=str(utilisateur) if authentifie else "",
                adresse_ip=adresse_client(request),
                canal=settings.CANAL,
                identifiant_requete=request.headers.get("X-Request-Id", "")[:64] or uuid.uuid4().hex,
            )
        )
        try:
            return self.get_response(request)
        finally:
            reinitialiser(jeton)
