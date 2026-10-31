import os

os.environ.setdefault("ENVIRONNEMENT", "test")

from .base import *

SECRET_KEY = "test-uniquement-cle-non-secrete-0123456789abcdef"
CLE_CHIFFREMENT = "dGVzdC11bmlxdWVtZW50LWNsZS1jaGlmZnJlbWVudC0w"
DATABASES["default"].update(
    {
        "PASSWORD": os.environ.get("POSTGRES_PASSWORD", "dev-uniquement"),
        "HOST": os.environ.get("POSTGRES_HOST", "127.0.0.1"),
        "PORT": os.environ.get("POSTGRES_PORT", "55432"),
        "CONN_MAX_AGE": 0,
    }
)
CACHES = {"default": {"BACKEND": "django.core.cache.backends.locmem.LocMemCache"}}
PASSWORD_HASHERS = ["django.contrib.auth.hashers.MD5PasswordHasher"]
CELERY_TASK_ALWAYS_EAGER = True
CELERY_TASK_EAGER_PROPAGATES = True
MEDIA_ROOT = BASE_DIR / ".stockage-tests"
REST_FRAMEWORK = {**REST_FRAMEWORK, "NUM_PROXIES": 0}
ALLOWED_HOSTS = ["testserver", "localhost"]
LOGGING = {"version": 1, "disable_existing_loggers": False, "root": {"level": "WARNING"}}

MAILERS = {"default": {"BACKEND": "django.core.mail.backends.locmem.EmailBackend"}}
URL_CALENDRIER_SCOLAIRE = "https://calendrier-scolaire.test/records"
URL_JOURS_FERIES = "https://jours-feries.test/{annee}.json"
