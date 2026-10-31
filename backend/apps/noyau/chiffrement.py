"""Chiffrement symétrique des secrets stockés en base (graines TOTP, jetons d'appareils)."""

from __future__ import annotations

import base64
import hashlib
import hmac

from cryptography.fernet import Fernet, InvalidToken
from django.conf import settings


def _fernet() -> Fernet:
    cle = hashlib.sha256(("chiffrement:" + settings.CLE_CHIFFREMENT).encode()).digest()
    return Fernet(base64.urlsafe_b64encode(cle))


def chiffrer(texte: str) -> str:
    return _fernet().encrypt(texte.encode()).decode()


def dechiffrer(jeton: str) -> str:
    try:
        return _fernet().decrypt(jeton.encode()).decode()
    except InvalidToken as erreur:
        raise ValueError("Donnée chiffrée illisible : clé de chiffrement modifiée ?") from erreur


def empreinte_hmac(valeur: str) -> str:
    """Empreinte non réversible d'un jeton (stockage des jetons portail, mobile, iCal)."""
    cle = hashlib.sha256(("hmac:" + settings.SECRET_KEY).encode()).digest()
    return hmac.new(cle, valeur.encode(), hashlib.sha256).hexdigest()
