"""Journaux de la façade : JSON, sans mot de passe ni jeton (SEC-09).

Le journal d'accès d'uvicorn a son propre gestionnaire : le masquage s'y applique par un filtre posé sur le
journal `uvicorn.access` lui-même. Les chemins des flux d'agenda (POR-05) portent leur jeton : il est masqué.
"""

from __future__ import annotations

import json
import logging
import re

SENSIBLE = re.compile(
    r"((?:mot_de_passe|password|jeton|token|secret|authorization|cookie)[\"']?\s*[:=]\s*[\"']?)([^\s\"',&]+)", re.IGNORECASE
)
CHEMIN_AGENDA = re.compile(r"(/agenda/)[A-Za-z0-9_-]+(\.ics)")


def masquer(texte: str) -> str:
    return CHEMIN_AGENDA.sub(r"\1***\2", SENSIBLE.sub(r"\1***", texte))


class FiltreMasquage(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:
        if isinstance(record.msg, str):
            record.msg = masquer(record.msg)
        if isinstance(record.args, tuple):
            record.args = tuple(masquer(a) if isinstance(a, str) else a for a in record.args)
        return True


class FormatJson(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        message = masquer(record.getMessage())
        return json.dumps({"niveau": record.levelname, "journal": record.name, "message": message}, ensure_ascii=False)


def installer() -> None:
    gestionnaire = logging.StreamHandler()
    gestionnaire.setFormatter(FormatJson())
    logging.basicConfig(level=logging.INFO, handlers=[gestionnaire], force=True)
    for nom in ("uvicorn.access", "uvicorn.error"):
        journal = logging.getLogger(nom)
        if not any(isinstance(f, FiltreMasquage) for f in journal.filters):
            journal.addFilter(FiltreMasquage())
