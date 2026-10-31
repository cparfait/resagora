"""Double authentification TOTP (RFC 6238) des agents (SEC-03)."""

from __future__ import annotations

import pyotp
import segno
from django.conf import settings
from django.core.cache import cache

from apps.noyau.chiffrement import chiffrer, dechiffrer

from .models import Utilisateur

FENETRE_TOLERANCE = 1  # ±30 s de dérive d'horloge


def nouvelle_graine() -> str:
    return pyotp.random_base32()


def uri_enrolement(utilisateur: Utilisateur, graine: str) -> str:
    return pyotp.TOTP(graine).provisioning_uri(name=utilisateur.username, issuer_name=settings.TOTP_EMETTEUR)


def qr_svg(uri: str) -> str:
    return segno.make(uri, error="m").svg_inline(scale=4, title="Code QR d'enrôlement de l'application d'authentification")


def _code_deja_utilise(utilisateur: Utilisateur, code: str) -> bool:
    """Empêche le rejeu d'un code dans sa fenêtre de validité."""
    return not cache.add(f"totp-utilise:{utilisateur.pk}:{code}", True, timeout=120)


def verifier_code(graine: str, code: str) -> bool:
    code = (code or "").strip().replace(" ", "")
    return code.isdigit() and len(code) == 6 and pyotp.TOTP(graine).verify(code, valid_window=FENETRE_TOLERANCE)


def activer(utilisateur: Utilisateur, graine: str, code: str) -> bool:
    if not verifier_code(graine, code) or _code_deja_utilise(utilisateur, code):
        return False
    utilisateur.totp_secret_chiffre = chiffrer(graine)
    utilisateur.totp_actif = True
    utilisateur.save(update_fields=["totp_secret_chiffre", "totp_actif"])
    return True


def verifier_utilisateur(utilisateur: Utilisateur, code: str) -> bool:
    if not utilisateur.totp_actif or not utilisateur.totp_secret_chiffre:
        return False
    return verifier_code(dechiffrer(utilisateur.totp_secret_chiffre), code) and not _code_deja_utilise(utilisateur, code)


def reinitialiser(utilisateur: Utilisateur) -> None:
    utilisateur.totp_secret_chiffre = ""
    utilisateur.totp_actif = False
    utilisateur.save(update_fields=["totp_secret_chiffre", "totp_actif"])
