"""Production et recette (mêmes images, paramètres par variables et secrets)."""

import os

from .base import *

if not SECRET_KEY or len(SECRET_KEY) < 50:
    raise RuntimeError("Le secret django_secret_key est absent ou trop court (50 caractères minimum).")
if not CLE_AUDIT:
    raise RuntimeError("Le secret audit_cle_hmac (clé HMAC du journal d'audit) est absent.")
if not CLE_CHIFFREMENT or len(CLE_CHIFFREMENT) < 32 or len(set(CLE_CHIFFREMENT)) < 16:
    raise RuntimeError("Le secret cle_chiffrement est absent ou trop faible (32 caractères aléatoires minimum).")

ENVIRONNEMENT = os.environ.get("ENVIRONNEMENT", "prod")
RECETTE = ENVIRONNEMENT == "recette"
