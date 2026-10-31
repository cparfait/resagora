"""Journaux techniques au format JSON, sans mot de passe, jeton ni donnée sensible (SEC-09)."""

from __future__ import annotations

import json
import logging
import re
from datetime import UTC, datetime

CLES_SENSIBLES = re.compile(r"(mot_de_passe|password|jeton|token|secret|authorization|cookie|iban|totp)", re.IGNORECASE)
VALEURS_SENSIBLES = re.compile(
    r"((?:mot_de_passe|password|jeton|token|secret|authorization|cookie)[\"']?\s*[:=]\s*[\"']?)([^\s\"',&]+)",
    re.IGNORECASE,
)


AUTORISATION = re.compile(r"(authorization[\"']?\s*[:=]\s*)([^\n\"']+)", re.IGNORECASE)


def masquer(texte: str) -> str:
    return VALEURS_SENSIBLES.sub(r"\1***", AUTORISATION.sub(r"\1***", texte))


class FiltreDonneesSensibles(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:
        if isinstance(record.msg, str):
            record.msg = masquer(record.msg)
        if isinstance(record.args, dict):
            record.args = {k: ("***" if CLES_SENSIBLES.search(str(k)) else v) for k, v in record.args.items()}
        elif isinstance(record.args, tuple):
            record.args = tuple(masquer(a) if isinstance(a, str) else a for a in record.args)
        return True


class FormatJson(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        contenu = {
            "horodatage": datetime.fromtimestamp(record.created, UTC).isoformat(),
            "niveau": record.levelname,
            "journal": record.name,
            "message": masquer(record.getMessage()),
        }
        if record.exc_info:
            contenu["exception"] = masquer(self.formatException(record.exc_info))
        return json.dumps(contenu, ensure_ascii=False)
