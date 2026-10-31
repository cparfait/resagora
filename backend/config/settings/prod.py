"""Production et recette (mêmes images, paramètres par variables et secrets)."""

import os

from .base import *

if not SECRET_KEY or len(SECRET_KEY) < 50:
    raise RuntimeError("Le secret django_secret_key est absent ou trop court (50 caractères minimum).")
if not CLE_CHIFFREMENT:
    raise RuntimeError("Le secret cle_chiffrement est absent.")

ENVIRONNEMENT = os.environ.get("ENVIRONNEMENT", "prod")
