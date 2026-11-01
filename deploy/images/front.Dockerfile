# syntax=docker/dockerfile:1
# Fronts statiques (back-office, portail, mobile) : construits sous Node.js 26 LTS, servis par nginx non root.
ARG APPLICATION=portail
FROM node:26.13.0-trixie-slim@sha256:e4db4c914bf8ad241bd24804fc25d272d89bad97e68cdc8a1414862790a02c39 AS construction
ARG APPLICATION
WORKDIR /src
COPY package.json package-lock.json ./
COPY backoffice/package.json backoffice/
COPY portail/package.json portail/
COPY mobile/package.json mobile/
COPY e2e/package.json e2e/
RUN npm ci --ignore-scripts --no-audit --no-fund
COPY ${APPLICATION}/ ${APPLICATION}/
COPY charte/ charte/
COPY tsconfig.base.json ./
RUN npm run build --workspace ${APPLICATION}

FROM nginxinc/nginx-unprivileged:1.30.6-trixie@sha256:ec0f7ecb1fbd84959ac114e65fb36074ffc97d4d51db0f18ee925162d889dcef
ARG APPLICATION
# Correctifs de sécurité Debian appliqués à la construction, sur l'image épinglée (D-074).
USER root
RUN apt-get update && apt-get upgrade -y && rm -rf /var/lib/apt/lists/*
COPY deploy/nginx/commun.inc /etc/nginx/conf.d/commun.inc
COPY deploy/nginx/${APPLICATION}.conf /etc/nginx/conf.d/default.conf
COPY --from=construction /src/${APPLICATION}/dist /usr/share/nginx/html
USER 101
EXPOSE 8080
