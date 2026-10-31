from __future__ import annotations

from django.db import connection
from django.http import HttpRequest, JsonResponse
from django.views.decorators.http import require_GET


@require_GET
def sante(request: HttpRequest) -> JsonResponse:
    """Sonde de santé des conteneurs : vérifie l'accès à la base."""
    try:
        with connection.cursor() as curseur:
            curseur.execute("SELECT 1")
    except Exception:
        return JsonResponse({"etat": "indisponible"}, status=503)
    return JsonResponse({"etat": "ok"})
