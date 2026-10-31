"""Point d'entrée : `uvicorn simulateurs.asgi:application` (recette uniquement)."""

import logging

from .app import creer_application

logging.basicConfig(level=logging.INFO, force=True)
application = creer_application()
