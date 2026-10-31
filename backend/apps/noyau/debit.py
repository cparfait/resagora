"""Limitation de débit par portée (connexion, inscription, réinitialisation, dépôt, téléversement) — SEC-06."""

from __future__ import annotations

import time

from django.conf import settings
from rest_framework.throttling import ScopedRateThrottle


class LimiteDebit(ScopedRateThrottle):
    """Relit les taux dans les réglages à chaque requête (paramétrables sans redémarrage du code)."""

    def timer(self) -> float:  # type: ignore[override]
        """Méthode (et non attribut de classe) : l'horloge reste remplaçable dans les tests de dates."""
        return time.time()

    def get_rate(self) -> str | None:
        taux: dict[str, str] = settings.REST_FRAMEWORK["DEFAULT_THROTTLE_RATES"]
        return taux.get(str(self.scope))
