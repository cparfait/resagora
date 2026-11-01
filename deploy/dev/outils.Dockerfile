# syntax=docker/dockerfile:1
# Conteneur d'outillage (CI et postes Windows sans GNU Make, D-005) : Python 3.14, uv, Node.js 26 LTS, make.
FROM node:26.13.0-trixie-slim@sha256:e4db4c914bf8ad241bd24804fc25d272d89bad97e68cdc8a1414862790a02c39 AS node

FROM python:3.14.10-slim-trixie@sha256:3cabfd7d7aaf394e6040e79fa1eec6ca1c52b74ed9188650472695d9a9326999
COPY --from=node /usr/local/bin/node /usr/local/bin/node
COPY --from=node /usr/local/lib/node_modules /usr/local/lib/node_modules
RUN ln -s /usr/local/lib/node_modules/npm/bin/npm-cli.js /usr/local/bin/npm \
    && ln -s /usr/local/lib/node_modules/npm/bin/npx-cli.js /usr/local/bin/npx \
    && apt-get update && apt-get install -y --no-install-recommends make git ca-certificates libatomic1 build-essential libldap-dev libsasl2-dev \
    && rm -rf /var/lib/apt/lists/* \
    && pip install --no-cache-dir uv==0.13.6 \
    && useradd --uid 1000 --create-home --shell /bin/bash outils \
    && mkdir -p /depot/node_modules /depot/outils/codegen/node_modules /depot/backoffice/node_modules /depot/portail/node_modules \
       /depot/mobile/node_modules /depot/e2e/node_modules /venvs \
    && chown -R 1000:1000 /depot /venvs
# Utilisateur non root (D-074) : les volumes de dépendances, créés vides, prennent le propriétaire des dossiers de
# l'image (un volume déjà créé par une version antérieure se recrée : docker volume rm equipements-dev_outils-*).
USER 1000
WORKDIR /depot
ENV UV_LINK_MODE=copy PYTHONIOENCODING=utf-8
CMD ["make", "lint", "test"]
