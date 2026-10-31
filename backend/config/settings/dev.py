import os

os.environ.setdefault("ENVIRONNEMENT", "dev")

from .base import *

DEBUG = True
SECRET_KEY = SECRET_KEY or "dev-uniquement-cle-non-secrete-0123456789abcdef"
CLE_CHIFFREMENT = CLE_CHIFFREMENT or "ZGV2LXVuaXF1ZW1lbnQtY2xlLWNoaWZmcmVtZW50LTAx"
DATABASES["default"]["PASSWORD"] = DATABASES["default"]["PASSWORD"] or "dev-uniquement"
DATABASES["default"]["HOST"] = os.environ.get("POSTGRES_HOST", "127.0.0.1")
DATABASES["default"]["PORT"] = os.environ.get("POSTGRES_PORT", "55432")
SESSION_COOKIE_SECURE = os.environ.get("COOKIES_SECURISES", "1") == "1"
CSRF_COOKIE_SECURE = SESSION_COOKIE_SECURE
if not SESSION_COOKIE_SECURE:
    SESSION_COOKIE_NAME = "session-agent"
    CSRF_COOKIE_NAME = "csrf-agent"
CSRF_TRUSTED_ORIGINS = [*CSRF_TRUSTED_ORIGINS, "http://localhost:5173", "http://127.0.0.1:5173"]
ALLOWED_HOSTS = ["*"]
