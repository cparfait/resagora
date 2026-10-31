"""Point d'entrée ASGI : `uvicorn facade.asgi:application` ; journaux JSON échappés et masqués."""

import json
import logging
import re

from .app import creer_application

SENSIBLE = re.compile(
    r"((?:mot_de_passe|password|jeton|token|secret|authorization|cookie)[\"']?\s*[:=]\s*[\"']?)([^\s\"',&]+)", re.IGNORECASE
)


class FormatJson(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        message = SENSIBLE.sub(r"\1***", record.getMessage())
        return json.dumps({"niveau": record.levelname, "journal": record.name, "message": message}, ensure_ascii=False)


gestionnaire = logging.StreamHandler()
gestionnaire.setFormatter(FormatJson())
logging.basicConfig(level=logging.INFO, handlers=[gestionnaire], force=True)

application = creer_application()
