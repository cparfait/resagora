"""Limitation de débit par portée (connexion, inscription, réinitialisation, dépôt, téléversement) — SEC-06."""

from __future__ import annotations

from django.conf import settings
from rest_framework.throttling import ScopedRateThrottle


class LimiteDebit(ScopedRateThrottle):
    """Relit les taux dans les réglages à chaque requête (paramétrables sans redémarrage du code)."""

    def get_rate(self) -> str | None:
        taux: dict[str, str] = settings.REST_FRAMEWORK["DEFAULT_THROTTLE_RATES"]
        return taux.get(str(self.scope))
