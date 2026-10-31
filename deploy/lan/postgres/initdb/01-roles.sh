#!/bin/sh
# Cree le role applicatif sans privilege d'administration (ADR 0005). Les droits sur les tables sont
# accordes apres chaque migration par `manage.py accorder_droits equipements_app`.
set -eu
MDP=$(tr -d '\r\n' < /run/secrets/postgres_app_password)
psql -v ON_ERROR_STOP=1 --username "$POSTGRES_USER" --dbname "$POSTGRES_DB" -v mdp="$MDP" <<'SQL'
CREATE ROLE equipements_app LOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE NOINHERIT NOREPLICATION PASSWORD :'mdp';
GRANT CONNECT ON DATABASE equipements TO equipements_app;
GRANT USAGE ON SCHEMA public TO equipements_app;
REVOKE CREATE ON SCHEMA public FROM PUBLIC;
SQL
