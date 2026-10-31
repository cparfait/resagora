"""Point d'entrée ASGI : `uvicorn facade.asgi:application`."""

import logging

from .app import creer_application

logging.basicConfig(level=logging.INFO, format='{"niveau":"%(levelname)s","journal":"%(name)s","message":"%(message)s"}')

application = creer_application()
