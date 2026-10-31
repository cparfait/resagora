"""Description OpenAPI de l'authentification des agents (cookie de session HttpOnly + jeton CSRF)."""

from __future__ import annotations

from typing import Any

from drf_spectacular.extensions import OpenApiAuthenticationExtension


class SessionAgentSchema(OpenApiAuthenticationExtension):
    target_class = "apps.habilitations.authentification.SessionAgentAuthentication"
    name = "sessionAgent"

    def get_security_definition(self, auto_schema: Any) -> dict[str, str]:
        return {"type": "apiKey", "in": "cookie", "name": "__Host-session-agent"}
