# syntax=docker/dockerfile:1
# Simulateurs de recette (SMS, DocuSeal, PayFiP) : jamais déployés en production.
FROM ghcr.io/astral-sh/uv:0.13.6@sha256:af22a52f5eafef3d78e551599d405c02df61919d18028f0cea8eda93bc9986d0 AS uv

FROM python:3.14.10-slim-trixie@sha256:3cabfd7d7aaf394e6040e79fa1eec6ca1c52b74ed9188650472695d9a9326999 AS construction
COPY --from=uv /uv /bin/uv
ENV UV_COMPILE_BYTECODE=1 UV_LINK_MODE=copy UV_PROJECT_ENVIRONMENT=/app/.venv
WORKDIR /app
COPY simulateurs/pyproject.toml simulateurs/uv.lock ./
RUN uv sync --frozen --no-dev --no-install-project

FROM python:3.14.10-slim-trixie@sha256:3cabfd7d7aaf394e6040e79fa1eec6ca1c52b74ed9188650472695d9a9326999
RUN apt-get update && apt-get upgrade -y && rm -rf /var/lib/apt/lists/* \
    && useradd --uid 10001 --create-home --shell /usr/sbin/nologin app
WORKDIR /app
COPY --from=construction /app/.venv /app/.venv
COPY --chown=10001:10001 simulateurs/simulateurs ./simulateurs
ENV PATH="/app/.venv/bin:$PATH" PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1
USER 10001
EXPOSE 8090
HEALTHCHECK --interval=30s --timeout=5s CMD ["python", "-c", "import urllib.request;urllib.request.urlopen('http://127.0.0.1:8090/sante', timeout=4)"]
CMD ["uvicorn", "simulateurs.asgi:application", "--host", "0.0.0.0", "--port", "8090", "--no-server-header"]
