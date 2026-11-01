#!/bin/sh
# EXP-01 — Role de sauvegarde (ADR 0010, ADR 0005). Le droit REPLICATION permet de copier physiquement tout le cluster
# (pg_basebackup) : c'est un role sensible, limite a la replication et a la base « postgres » (etat de l'archivage),
# connexions refusees sur toute autre base.
# Execute a la creation de la base. Idempotent : sur une base existante, lancer une fois
#   docker compose -f deploy/lan/compose.yaml exec -u postgres postgres sh /docker-entrypoint-initdb.d/02-sauvegarde.sh
set -eu
MDP=$(tr -d '\r\n' < /run/secrets/postgres_sauvegarde_password)
psql -v ON_ERROR_STOP=1 --username "${POSTGRES_USER:-equipements}" --dbname postgres -v mdp="$MDP" <<'SQL'
SELECT 'CREATE ROLE equipements_sauvegarde LOGIN REPLICATION NOSUPERUSER NOCREATEDB NOCREATEROLE NOINHERIT'
WHERE NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'equipements_sauvegarde') \gexec
ALTER ROLE equipements_sauvegarde PASSWORD :'mdp';
-- Segments en attente d'archivage, pour la surveillance (sans le role pg_monitor, qui lirait les requetes en cours).
GRANT EXECUTE ON FUNCTION pg_ls_archive_statusdir() TO equipements_sauvegarde;
SQL
# Regles placees AVANT la ligne generique « host all all all » de l'image : replication et base postgres depuis le
# reseau lan_data seulement, tout le reste refuse pour ce role.
if ! grep -q '^# EXP-01' "$PGDATA/pg_hba.conf"; then
	{
		printf '%s\n' "# EXP-01 sauvegarde"
		printf '%s\n' "host replication equipements_sauvegarde samenet scram-sha-256"
		printf '%s\n' "host postgres equipements_sauvegarde samenet scram-sha-256"
		printf '%s\n' "host all equipements_sauvegarde all reject"
		cat "$PGDATA/pg_hba.conf"
	} > "$PGDATA/pg_hba.conf.nouveau"
	mv "$PGDATA/pg_hba.conf.nouveau" "$PGDATA/pg_hba.conf"
fi
psql -v ON_ERROR_STOP=1 --username "${POSTGRES_USER:-equipements}" --dbname postgres -Atc 'SELECT pg_reload_conf()' > /dev/null
