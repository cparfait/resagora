"""En-têtes de sécurité complémentaires et cloisonnement des canaux d'exposition (SEC-01, SEC-05)."""

from __future__ import annotations

from collections.abc import Callable

from django.conf import settings
from django.http import HttpRequest, HttpResponse, JsonResponse

PREFIXES_PAR_CANAL = {
    "gestion": ("/api/gestion/", "/api/mobile/", "/sante", "/api/schema/"),
    "portail": ("/api/portail/", "/sante"),
}


class EntetesSecuriteMiddleware:
    def __init__(self, get_response: Callable[[HttpRequest], HttpResponse]):
        self.get_response = get_response

    def __call__(self, request: HttpRequest) -> HttpResponse:
        reponse = self.get_response(request)
        reponse.headers.setdefault("Permissions-Policy", settings.PERMISSIONS_POLICY)
        reponse.headers.setdefault("Cross-Origin-Resource-Policy", "same-origin")
        if request.path.startswith("/api/"):
            reponse.headers.setdefault("Cache-Control", "no-store")
        return reponse


class CanalMiddleware:
    """Une instance « portail » ne sert que /api/portail/* (et /api/mobile/* en option B) ;
    une instance « gestion » ne sert jamais /api/portail/*."""

    def __init__(self, get_response: Callable[[HttpRequest], HttpResponse]):
        self.get_response = get_response

    def __call__(self, request: HttpRequest) -> HttpResponse:
        prefixes = PREFIXES_PAR_CANAL[settings.CANAL]
        if settings.CANAL == "portail" and settings.MOBILE_OPTION == "B":
            prefixes = (*prefixes, "/api/mobile/")
        if settings.CANAL == "gestion" and settings.MOBILE_OPTION == "B":
            prefixes = tuple(p for p in prefixes if p != "/api/mobile/")
        if not request.path.startswith(prefixes):
            return JsonResponse({"code": "introuvable", "message": "Élément introuvable."}, status=404)
        return self.get_response(request)
