"""Point d'entrée ASGI : `uvicorn facade.asgi:application` ; journaux JSON échappés et masqués."""

from .app import creer_application
from .journaux import installer

installer()

application = creer_application()
