"""Réglages communs. Les secrets sont lus dans des fichiers (Docker secrets), jamais en clair (SEC-09)."""

from __future__ import annotations

import os
from datetime import timedelta
from pathlib import Path
from typing import Any

from celery.schedules import crontab
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
    "apps.usagers",
    "apps.communication",
    "apps.comptes",
    "apps.reservations",
    "apps.documents",
    "apps.finances",
    "apps.personnel",
    "apps.portail",
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
    "apps.habilitations.middleware.InactiviteMiddleware",
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
# Déconnexion après inactivité (minutes) ; plus courte pour les rôles à double authentification.
SESSION_INACTIVITE_MINUTES = entier("SESSION_INACTIVITE_MINUTES", 60)
SESSION_INACTIVITE_SENSIBLE_MINUTES = entier("SESSION_INACTIVITE_SENSIBLE_MINUTES", 20)
# Verrouillage de la double authentification après échecs successifs (SEC-03).
TOTP_ECHECS_MAX = entier("TOTP_ECHECS_MAX", 5)
TOTP_VERROU_MINUTES = entier("TOTP_VERROU_MINUTES", 15)
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

# « recette » (poste ou serveur de recette), « dev », « test » : seuls environnements où les adresses de
# simulateurs et les seuils de débit élargis sont admis (`verifier_deploiement`, adaptateur SMS).
ENVIRONNEMENT = os.environ.get("ENVIRONNEMENT", "prod")
RECETTE = ENVIRONNEMENT in {"dev", "test", "recette"}
DEBITS_PAR_DEFAUT = {
    "connexion": "10/min",
    "inscription": "5/hour",
    "reinitialisation": "5/hour",
    "depot": "30/hour",
    "televersement": "60/hour",
    "public": "120/min",
}

REST_FRAMEWORK: dict[str, Any] = {
    "DEFAULT_AUTHENTICATION_CLASSES": ["apps.habilitations.authentification.SessionAgentAuthentication"],
    "DEFAULT_PERMISSION_CLASSES": ["apps.habilitations.permissions.ActionPermission"],
    "DEFAULT_SCHEMA_CLASS": "drf_spectacular.openapi.AutoSchema",
    "DEFAULT_FILTER_BACKENDS": ["django_filters.rest_framework.DjangoFilterBackend"],
    "DEFAULT_PAGINATION_CLASS": "apps.noyau.pagination.Pagination",
    "DEFAULT_THROTTLE_CLASSES": ["apps.noyau.debit.LimiteDebit"],
    "DEFAULT_THROTTLE_RATES": {cle: os.environ.get(f"DEBIT_{cle.upper()}", defaut) for cle, defaut in DEBITS_PAR_DEFAUT.items()},
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
    "SERVE_PERMISSIONS": ["rest_framework.permissions.IsAuthenticated"],
    "SERVE_AUTHENTICATION": ["apps.habilitations.authentification.SessionAgentAuthentication"],
    "COMPONENT_SPLIT_REQUEST": True,
    "ENUM_NAME_OVERRIDES": {
        "StatutReservationEnum": "apps.reservations.models.STATUTS",
        "StatutCampagneEnum": "apps.reservations.models.Campagne.STATUTS",
        "StatutUsagerEnum": "apps.usagers.models.Usager.STATUTS",
        "StatutPieceEnum": "apps.usagers.models.PieceJustificative.STATUTS",
        "StatutListeAttenteEnum": "apps.reservations.models.ListeAttente.STATUTS",
        "TypeUsagerEnum": "apps.usagers.models.TYPES_USAGER",
    },
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
    "ATTRIBUT_GUID": os.environ.get("LDAP_ATTRIBUT_GUID", "objectGUID"),
    "DELAI_SECONDES": entier("LDAP_DELAI_SECONDES", 5),
}

# Double authentification (SEC-03) : clé de chiffrement des secrets TOTP.
CLE_CHIFFREMENT = secret("cle_chiffrement", defaut="")
TOTP_EMETTEUR = os.environ.get("TOTP_EMETTEUR", "Ville de Châtillon — Équipements")

# Messagerie électronique (COM-01) : Mailpit en recette, serveur SMTP de la Ville en production.
# Réglage MAILERS de Django 6.1 (les réglages EMAIL_* sont dépréciés).
MAILERS = {
    "default": {
        "BACKEND": "django.core.mail.backends.smtp.EmailBackend",
        "OPTIONS": {
            "host": os.environ.get("SMTP_HOTE", "mailpit"),
            "port": entier("SMTP_PORT", 1025),
            "username": os.environ.get("SMTP_UTILISATEUR", ""),
            "password": secret("smtp_mot_de_passe", defaut=""),
            "use_tls": booleen("SMTP_STARTTLS", False),
            "use_ssl": booleen("SMTP_TLS", False),
            "timeout": entier("SMTP_DELAI_SECONDES", 20),
        },
    }
}
DEFAULT_FROM_EMAIL = os.environ.get(
    "COURRIEL_EXPEDITEUR", "Équipements sportifs — Ville de Châtillon <equipements@chatillon.test>"
)
PORTAIL_URL = os.environ.get("PORTAIL_URL", "https://equipements.chatillon.test")
BACKOFFICE_URL = os.environ.get("BACKOFFICE_URL", "https://equipements.chatillon.local")

# Documents et signature (DOC-04, SIG-01) : Gotenberg (LAN) et DocuSeal (DMZ) ou simulateur de recette.
GOTENBERG_URL = os.environ.get("GOTENBERG_URL", "http://gotenberg:3000")
GOTENBERG_DELAI_SECONDES = entier("GOTENBERG_DELAI_SECONDES", 120)
SIGNATURE_MODE = os.environ.get("SIGNATURE_MODE", "docuseal")  # docuseal | manuel
# Adresse interne de l'API DocuSeal (DMZ), jointe par le worker en HTTPS : à renseigner (docs/a-brancher.md).
DOCUSEAL_URL = os.environ.get("DOCUSEAL_URL", "")
DOCUSEAL_URL_PUBLIQUE = os.environ.get("DOCUSEAL_URL_PUBLIQUE", "https://signature.chatillon.test")
DOCUSEAL_JETON = secret("docuseal_api_jeton", defaut="")
DOCUSEAL_VERIFIER_TLS = booleen("DOCUSEAL_VERIFIER_TLS", True)

# Calendrier national (ADM-01)
URL_CALENDRIER_SCOLAIRE = os.environ.get(
    "URL_CALENDRIER_SCOLAIRE",
    "https://data.education.gouv.fr/api/explore/v2.1/catalog/datasets/fr-en-calendrier-scolaire/records",
)
URL_JOURS_FERIES = os.environ.get("URL_JOURS_FERIES", "https://calendrier.api.gouv.fr/jours-feries/metropole/{annee}.json")

# Celery
CELERY_BROKER_URL = VALKEY_URL
CELERY_RESULT_BACKEND = None
CELERY_TASK_ACKS_LATE = True
CELERY_TASK_REJECT_ON_WORKER_LOST = True
CELERY_WORKER_PREFETCH_MULTIPLIER = 1
CELERY_TIMEZONE = TIME_ZONE
CELERY_BEAT_SCHEDULE: dict[str, dict[str, object]] = {
    "verifier-journal-audit": {"task": "apps.audit.tasks.verifier_integrite", "schedule": timedelta(hours=6)},
    "ancrer-journal-audit": {"task": "apps.audit.tasks.ancrer_journal", "schedule": timedelta(hours=1)},
    "traiter-options": {"task": "apps.reservations.tasks.traiter_options", "schedule": timedelta(hours=1)},
    "marquer-realisees": {"task": "apps.reservations.tasks.marquer_realisees", "schedule": timedelta(hours=6)},
    "relancer-notifications": {"task": "apps.communication.tasks.relancer_echecs", "schedule": timedelta(minutes=30)},
    "relancer-pieces": {"task": "apps.usagers.tasks.relancer_pieces", "schedule": timedelta(hours=24)},
    "anonymiser-inactifs": {"task": "apps.usagers.tasks.anonymiser_inactifs", "schedule": timedelta(days=7)},
    "purger-pieces-expirees": {"task": "apps.usagers.tasks.purger_pieces_expirees", "schedule": timedelta(days=7)},
    "purger-archives-echues": {"task": "apps.usagers.tasks.purger_archives_echues", "schedule": timedelta(days=30)},
    "rappeler-seances": {"task": "apps.reservations.tasks.rappeler_seances", "schedule": crontab(hour=17, minute=0)},
    "synchroniser-signatures": {"task": "apps.documents.tasks.synchroniser_signatures", "schedule": timedelta(minutes=15)},
    "relancer-signatures": {"task": "apps.documents.tasks.relancer_signatures", "schedule": timedelta(hours=6)},
    "expirer-devis": {"task": "apps.finances.tasks.expirer_devis", "schedule": crontab(hour=1, minute=15)},
}

# Journal d'audit (SEC-08) : clé HMAC de la chaîne et conservation minimale 6 mois.
CLE_AUDIT = secret("audit_cle_hmac", defaut="")
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
