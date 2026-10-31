# syntax=docker/dockerfile:1
# API métier Django (canaux gestion et portail, tâches Celery). Image durcie (fiche ANSSI).
FROM ghcr.io/astral-sh/uv:0.13.6@sha256:af22a52f5eafef3d78e551599d405c02df61919d18028f0cea8eda93bc9986d0 AS uv

FROM python:3.14.10-slim-trixie@sha256:3cabfd7d7aaf394e6040e79fa1eec6ca1c52b74ed9188650472695d9a9326999 AS construction
COPY --from=uv /uv /bin/uv
ENV UV_COMPILE_BYTECODE=1 UV_LINK_MODE=copy UV_PROJECT_ENVIRONMENT=/app/.venv
RUN apt-get update \
    && apt-get install -y --no-install-recommends build-essential libldap-dev libsasl2-dev \
    && rm -rf /var/lib/apt/lists/*
WORKDIR /app
COPY backend/pyproject.toml backend/uv.lock ./
RUN uv sync --frozen --no-dev --no-install-project

FROM python:3.14.10-slim-trixie@sha256:3cabfd7d7aaf394e6040e79fa1eec6ca1c52b74ed9188650472695d9a9326999
RUN apt-get update \
    && apt-get install -y --no-install-recommends libldap2 libsasl2-2 fonts-dejavu-core \
    && apt-get upgrade -y \
    && rm -rf /var/lib/apt/lists/* \
    && useradd --uid 10001 --create-home --shell /usr/sbin/nologin app \
    && mkdir -p /stockage /app/static && chown 10001:10001 /stockage /app/static
WORKDIR /app
COPY --from=construction /app/.venv /app/.venv
COPY --chown=10001:10001 backend/ .
# FORWARDED_ALLOW_IPS : adresse du seul proxy de confiance (Traefik LAN), fixée par le compose.
ENV PATH="/app/.venv/bin:$PATH" PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 \
    DJANGO_SETTINGS_MODULE=config.settings.prod STOCKAGE_FICHIERS=/stockage \
    FORWARDED_ALLOW_IPS=127.0.0.1
RUN rm -rf tests conftest.py && find /app/apps -type d -name tests -prune -exec rm -rf {} + && python -m compileall -q /app/apps /app/config
USER 10001
EXPOSE 8000 8443
HEALTHCHECK --interval=30s --timeout=5s CMD ["python", "-c", "import urllib.request;urllib.request.urlopen('http://127.0.0.1:8000/sante', timeout=4)"]
CMD ["gunicorn", "config.wsgi", "--bind", "0.0.0.0:8000", "--control-socket", "/tmp/gunicorn.ctl", "--workers", "4", "--timeout", "60"]
