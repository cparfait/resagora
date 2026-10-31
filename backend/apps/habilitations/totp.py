"""Double authentification TOTP (RFC 6238) des agents (SEC-03).

- graine chiffrée en base, codes non rejouables dans leur fenêtre de validité ;
- verrouillage après `TOTP_ECHECS_MAX` échecs successifs, durée doublée à chaque récidive ;
- après une réinitialisation par l'administrateur, le réenrôlement exige un code à usage unique
  remis hors ligne (téléphone, en main propre) : le mot de passe seul ne suffit plus.
"""

from __future__ import annotations

import secrets
from datetime import timedelta

import pyotp
import segno
from django.conf import settings
from django.contrib.sessions.models import Session
from django.core.cache import cache
from django.utils import timezone

from apps.noyau.chiffrement import chiffrer, dechiffrer, empreinte_hmac

from .models import Utilisateur

FENETRE_TOLERANCE = 1  # ±30 s de dérive d'horloge
DUREE_JETON_ENROLEMENT = timedelta(hours=72)


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


def secondes_verrou(utilisateur: Utilisateur) -> int:
    """Temps restant avant de pouvoir réessayer (0 si non verrouillé)."""
    fin = cache.get(f"totp-verrou:{utilisateur.pk}")
    return max(0, int(fin - timezone.now().timestamp())) if fin else 0


def enregistrer_echec(utilisateur: Utilisateur) -> bool:
    """Compte un échec ; renvoie vrai si le compte vient d'être verrouillé."""
    cle = f"totp-echecs:{utilisateur.pk}"
    cache.add(cle, 0, timeout=settings.TOTP_VERROU_MINUTES * 60)
    echecs = cache.incr(cle)
    if echecs < settings.TOTP_ECHECS_MAX:
        return False
    recidive = cache.get(f"totp-recidive:{utilisateur.pk}", 0) + 1
    cache.set(f"totp-recidive:{utilisateur.pk}", recidive, timeout=24 * 3600)
    duree = settings.TOTP_VERROU_MINUTES * 60 * (2 ** (recidive - 1))
    cache.set(f"totp-verrou:{utilisateur.pk}", timezone.now().timestamp() + duree, timeout=duree)
    cache.delete(cle)
    return True


def reinitialiser_echecs(utilisateur: Utilisateur) -> None:
    cache.delete_many([f"totp-echecs:{utilisateur.pk}", f"totp-recidive:{utilisateur.pk}"])


def activer(utilisateur: Utilisateur, graine: str, code: str) -> bool:
    if not verifier_code(graine, code) or _code_deja_utilise(utilisateur, code):
        return False
    utilisateur.totp_secret_chiffre = chiffrer(graine)
    utilisateur.totp_actif = True
    utilisateur.totp_reinitialise = False
    utilisateur.jeton_enrolement_empreinte = ""
    utilisateur.jeton_enrolement_expire = None
    utilisateur.save(
        update_fields=[
            "totp_secret_chiffre",
            "totp_actif",
            "totp_reinitialise",
            "jeton_enrolement_empreinte",
            "jeton_enrolement_expire",
        ]
    )
    return True


def verifier_utilisateur(utilisateur: Utilisateur, code: str) -> bool:
    if not utilisateur.totp_actif or not utilisateur.totp_secret_chiffre:
        return False
    return verifier_code(dechiffrer(utilisateur.totp_secret_chiffre), code) and not _code_deja_utilise(utilisateur, code)


def deconnecter_partout(utilisateur: Utilisateur) -> int:
    """Ferme toutes les sessions ouvertes de l'agent (après réinitialisation ou désactivation)."""
    fermees = 0
    for session in Session.objects.filter(expire_date__gt=timezone.now()).iterator():
        if session.get_decoded().get("_auth_user_id") == str(utilisateur.pk):
            cache.delete(f"django.contrib.sessions.cached_db{session.session_key}")
            session.delete()
            fermees += 1
    return fermees


def reinitialiser(utilisateur: Utilisateur) -> str:
    """Retire l'appareil enrôlé et renvoie le code à usage unique de réenrôlement (affiché une seule fois)."""
    jeton = f"{secrets.randbelow(10**8):08d}"
    utilisateur.totp_secret_chiffre = ""
    utilisateur.totp_actif = False
    utilisateur.totp_reinitialise = True
    utilisateur.jeton_enrolement_empreinte = empreinte_hmac(f"enrolement:{utilisateur.pk}:{jeton}")
    utilisateur.jeton_enrolement_expire = timezone.now() + DUREE_JETON_ENROLEMENT
    utilisateur.save(
        update_fields=[
            "totp_secret_chiffre",
            "totp_actif",
            "totp_reinitialise",
            "jeton_enrolement_empreinte",
            "jeton_enrolement_expire",
        ]
    )
    deconnecter_partout(utilisateur)
    reinitialiser_echecs(utilisateur)
    return jeton


def verifier_jeton_enrolement(utilisateur: Utilisateur, jeton: str) -> bool:
    if not utilisateur.totp_reinitialise or not utilisateur.jeton_enrolement_empreinte:
        return False
    if utilisateur.jeton_enrolement_expire is None or utilisateur.jeton_enrolement_expire < timezone.now():
        return False
    attendu = empreinte_hmac(f"enrolement:{utilisateur.pk}:{(jeton or '').strip()}")
    return secrets.compare_digest(attendu, utilisateur.jeton_enrolement_empreinte)


def graine_en_session(graine: str) -> str:
    return chiffrer(graine)


def graine_depuis_session(valeur: str | None) -> str | None:
    return dechiffrer(valeur) if valeur else None
