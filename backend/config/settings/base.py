"""Réglages communs. Les secrets sont lus dans des fichiers (Docker secrets), jamais en clair (SEC-09)."""

from __future__ import annotations

import os
from datetime import timedelta
from pathlib import Path
from typing import Any

from django.utils.csp import CSP

from apps.noyau.secrets import booleen, entier, liste, secret

BASE_DIR = Path(__file__).resolve().parent.parent.parent

SECRET_KEY = secret("django_secret_key", defaut="")
DEBUG = False
ALLOWED_HOSTS = liste("DJANGO_ALLOWED_HOSTS", "localhost,127.0.0.1")

# Canal d'exposition de cette instance : « gestion » (LAN, agents et mobile option A) ou
# « portail » (instance mTLS 8443 joignable uniquement par la façade DMZ). SEC-01.
CANAL = os.environ.get("CANAL", "gestion")
ROOT_URLCONF = {"gestion": "config.urls_gestion", "portail": "config.urls_portail"}[CANAL]

# Accès mobile des gardiens (§6.7, SEC-10) : « A » = VPN, API mobile sur le LAN (canal gestion) ;
# « B » = API mobile relayée par la façade DMZ (canal portail) avec double facteur et certificat d'appareil.
MOBILE_OPTION = os.environ.get("MOBILE_OPTION", "A")

INSTALLED_APPS = [
    "django.contrib.contenttypes",
    "django.contrib.auth",
    "django.contrib.sessions",
    "django.contrib.postgres",
    "rest_framework",
    "django_filters",
    "drf_spectacular",
    "apps.noyau",
    "apps.audit",
    "apps.habilitations",
    "apps.referentiel",
]

MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",
    "django.middleware.csp.ContentSecurityPolicyMiddleware",
    "apps.noyau.middleware.EntetesSecuriteMiddleware",
    "apps.noyau.middleware.CanalMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
    "apps.audit.middleware.ContexteAuditMiddleware",
]

TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "DIRS": [BASE_DIR / "gabarits"],
        "APP_DIRS": True,
        "OPTIONS": {"context_processors": ["django.template.context_processors.request"]},
    }
]

WSGI_APPLICATION = "config.wsgi.application"

DATABASES = {
    "default": {
        "ENGINE": "django.db.backends.postgresql",
        "NAME": os.environ.get("POSTGRES_DB", "equipements"),
        "USER": os.environ.get("POSTGRES_USER", "equipements"),
        "PASSWORD": secret("postgres_password", defaut=""),
        "HOST": os.environ.get("POSTGRES_HOST", "postgres"),
        "PORT": os.environ.get("POSTGRES_PORT", "5432"),
        "CONN_MAX_AGE": 60,
        "CONN_HEALTH_CHECKS": True,
        "ATOMIC_REQUESTS": False,
    }
}
DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"

VALKEY_URL = secret("valkey_url", defaut=os.environ.get("VALKEY_URL", "redis://valkey:6379/0"))
CACHES = {"default": {"BACKEND": "django.core.cache.backends.redis.RedisCache", "LOCATION": VALKEY_URL}}

AUTH_USER_MODEL = "habilitations.Utilisateur"
AUTHENTICATION_BACKENDS = ["apps.habilitations.ldap.LdapBackend"]
PASSWORD_HASHERS = ["django.contrib.auth.hashers.Argon2PasswordHasher"]

LANGUAGE_CODE = "fr-fr"
TIME_ZONE = "Europe/Paris"
USE_I18N = True
USE_TZ = True

STATIC_URL = "/static/"
STATIC_ROOT = BASE_DIR / "static"
MEDIA_ROOT = Path(os.environ.get("STOCKAGE_FICHIERS", BASE_DIR / "stockage"))

# Sessions des agents : courtes, cookie sécurisé (SEC-02).
SESSION_ENGINE = "django.contrib.sessions.backends.cached_db"
SESSION_COOKIE_NAME = "__Host-session-agent"
SESSION_COOKIE_SECURE = True
SESSION_COOKIE_HTTPONLY = True
SESSION_COOKIE_SAMESITE = "Lax"
SESSION_COOKIE_AGE = entier("SESSION_DUREE_SECONDES", 8 * 3600)
SESSION_EXPIRE_AT_BROWSER_CLOSE = True
CSRF_COOKIE_NAME = "__Host-csrf-agent"
CSRF_COOKIE_SECURE = True
CSRF_COOKIE_SAMESITE = "Strict"
CSRF_TRUSTED_ORIGINS = liste("CSRF_TRUSTED_ORIGINS", "https://equipements.chatillon.local")

# En-têtes (SEC-05).
SECURE_CONTENT_TYPE_NOSNIFF = True
SECURE_REFERRER_POLICY = "same-origin"
SECURE_CROSS_ORIGIN_OPENER_POLICY = "same-origin"
SECURE_HSTS_SECONDS = 31536000
SECURE_HSTS_INCLUDE_SUBDOMAINS = True
SECURE_PROXY_SSL_HEADER = ("HTTP_X_FORWARDED_PROTO", "https")
X_FRAME_OPTIONS = "DENY"
SECURE_CSP = {
    "default-src": [CSP.SELF],
    "script-src": [CSP.SELF],
    "style-src": [CSP.SELF],
    "img-src": [CSP.SELF, "data:"],
    "object-src": [CSP.NONE],
    "base-uri": [CSP.NONE],
    "frame-ancestors": [CSP.NONE],
    "form-action": [CSP.SELF],
}
PERMISSIONS_POLICY = "camera=(), microphone=(), geolocation=(), payment=(), usb=()"

REST_FRAMEWORK: dict[str, Any] = {
    "DEFAULT_AUTHENTICATION_CLASSES": ["apps.habilitations.authentification.SessionAgentAuthentication"],
    "DEFAULT_PERMISSION_CLASSES": ["apps.habilitations.permissions.ActionPermission"],
    "DEFAULT_SCHEMA_CLASS": "drf_spectacular.openapi.AutoSchema",
    "DEFAULT_FILTER_BACKENDS": ["django_filters.rest_framework.DjangoFilterBackend"],
    "DEFAULT_PAGINATION_CLASS": "apps.noyau.pagination.Pagination",
    "DEFAULT_THROTTLE_CLASSES": ["apps.noyau.debit.LimiteDebit"],
    "DEFAULT_THROTTLE_RATES": {
        "connexion": os.environ.get("DEBIT_CONNEXION", "10/min"),
        "inscription": os.environ.get("DEBIT_INSCRIPTION", "5/hour"),
        "reinitialisation": os.environ.get("DEBIT_REINITIALISATION", "5/hour"),
        "depot": os.environ.get("DEBIT_DEPOT", "30/hour"),
        "televersement": os.environ.get("DEBIT_TELEVERSEMENT", "60/hour"),
        "public": os.environ.get("DEBIT_PUBLIC", "120/min"),
    },
    "NUM_PROXIES": entier("NOMBRE_PROXIES", 1),
    "EXCEPTION_HANDLER": "apps.noyau.exceptions.gestionnaire_exceptions",
    "UNAUTHENTICATED_USER": None,
    "DATETIME_FORMAT": "iso-8601",
    "COERCE_DECIMAL_TO_STRING": False,
}

SPECTACULAR_SETTINGS = {
    "TITLE": "API métier — équipements sportifs et associatifs de Châtillon",
    "VERSION": "1.0.0",
    "SERVE_INCLUDE_SCHEMA": False,
    "COMPONENT_SPLIT_REQUEST": True,
    "ENUM_NAME_OVERRIDES": {},
}

# Annuaire Active Directory (SEC-02, ADM-06). Paramètres réels : voir docs/a-brancher.md.
LDAP: dict[str, Any] = {
    "URI": os.environ.get("LDAP_URI", "ldaps://annuaire:636"),
    "STARTTLS": booleen("LDAP_STARTTLS", False),
    "FICHIER_AC": os.environ.get("LDAP_FICHIER_AC", "/run/secrets/ldap_ac.pem"),
    "VERIFIER_CERTIFICAT": booleen("LDAP_VERIFIER_CERTIFICAT", True),
    "COMPTE_SERVICE_DN": os.environ.get("LDAP_COMPTE_SERVICE_DN", ""),
    "COMPTE_SERVICE_MOT_DE_PASSE": secret("ldap_mot_de_passe", defaut=""),
    "BASE_UTILISATEURS": os.environ.get("LDAP_BASE_UTILISATEURS", ""),
    "FILTRE_UTILISATEUR": os.environ.get("LDAP_FILTRE_UTILISATEUR", "(&(objectClass=user)(sAMAccountName={identifiant}))"),
    "BASE_GROUPES": os.environ.get("LDAP_BASE_GROUPES", ""),
    "MODE_GROUPES": os.environ.get("LDAP_MODE_GROUPES", "ad_imbriques"),
    "ATTRIBUT_IDENTIFIANT": os.environ.get("LDAP_ATTRIBUT_IDENTIFIANT", "sAMAccountName"),
    "ATTRIBUT_PRENOM": os.environ.get("LDAP_ATTRIBUT_PRENOM", "givenName"),
    "ATTRIBUT_NOM": os.environ.get("LDAP_ATTRIBUT_NOM", "sn"),
    "ATTRIBUT_COURRIEL": os.environ.get("LDAP_ATTRIBUT_COURRIEL", "mail"),
    "ATTRIBUT_GROUPES": os.environ.get("LDAP_ATTRIBUT_GROUPES", "memberOf"),
    "DELAI_SECONDES": entier("LDAP_DELAI_SECONDES", 5),
}

# Double authentification (SEC-03) : clé de chiffrement des secrets TOTP.
CLE_CHIFFREMENT = secret("cle_chiffrement", defaut="")
TOTP_EMETTEUR = os.environ.get("TOTP_EMETTEUR", "Ville de Châtillon — Équipements")

# Celery
CELERY_BROKER_URL = VALKEY_URL
CELERY_RESULT_BACKEND = None
CELERY_TASK_ACKS_LATE = True
CELERY_TASK_REJECT_ON_WORKER_LOST = True
CELERY_WORKER_PREFETCH_MULTIPLIER = 1
CELERY_TIMEZONE = TIME_ZONE
CELERY_BEAT_SCHEDULE: dict[str, dict[str, object]] = {
    "verifier-journal-audit": {"task": "apps.audit.tasks.verifier_integrite", "schedule": timedelta(hours=6)},
}

# Journal d'audit (SEC-08) : conservation minimale 6 mois.
AUDIT_CONSERVATION_JOURS = max(183, entier("AUDIT_CONSERVATION_JOURS", 400))

LOGGING = {
    "version": 1,
    "disable_existing_loggers": False,
    "filters": {"masquer": {"()": "apps.noyau.journaux.FiltreDonneesSensibles"}},
    "formatters": {"json": {"()": "apps.noyau.journaux.FormatJson"}},
    "handlers": {"console": {"class": "logging.StreamHandler", "formatter": "json", "filters": ["masquer"]}},
    "root": {"handlers": ["console"], "level": os.environ.get("NIVEAU_JOURNAUX", "INFO")},
    "loggers": {"django.security": {"level": "WARNING"}},
}
