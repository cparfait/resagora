#!/bin/sh
# EXP-01 — Restauration d'une sauvegarde dans des volumes VIDES (procédure : docs/sauvegarde-restauration.md).
#
#   CIBLE        instant à atteindre AVEC son fuseau, ex. « 2026-11-01 10:00:00+01 » ; vide = rejouer tous les WAL
#   SAUVEGARDE   nom d'une sauvegarde de base (/sauvegardes/base/<nom>) ; par défaut la plus récente antérieure à CIBLE
#   FICHIERS     1 = restaurer aussi les fichiers déposés dans /stockage, qui doit être vide : instantané de la
#                sauvegarde de base retenue, complété par les fichiers ajoutés depuis (miroir le plus récent)
#
# La clé privée de déchiffrement (/run/secrets/sauvegarde_cle_privee) n'est fournie que le temps de la restauration.
# Les volumes d'origine ne sont jamais modifiés : on restaure dans de nouveaux volumes (VOLUME_PGDATA, VOLUME_STOCKAGE).
set -eu
umask 077

RACINE=/sauvegardes
ARCHIVES=/archives
DONNEES=${PGDATA:-/var/lib/postgresql/18/docker}
# Les WAL déchiffrés attendent le rejeu à côté des données, dans le même volume.
WAL_RESTAURES="$(dirname "$(dirname "$DONNEES")")/restauration-wal"
CLE=/run/secrets/sauvegarde_cle_privee

echec() {
	printf 'restauration : %s\n' "$*" >&2
	exit 1
}

dechiffrer() {
	openssl cms -decrypt -binary -inform DER -in "$1" -inkey "$CLE"
}

# Vrai si $1 précède strictement $2 dans l'ordre lexicographique (horodatages, noms de segments WAL).
avant() {
	[ "$1" != "$2" ] && [ "$(printf '%s\n%s\n' "$1" "$2" | sort | head -n 1)" = "$1" ]
}

# Concatène les morceaux déchiffrés d'un fichier sauvegardé ($1 = préfixe) ; un morceau illisible est signalé.
dechiffrer_morceaux() {
	for morceau in "$1".*.cms; do
		[ -f "$morceau" ] || {
			touch /tmp/morceau-illisible
			return 0
		}
		dechiffrer "$morceau" || {
			touch /tmp/morceau-illisible
			return 0
		}
	done
}

[ -r "$CLE" ] || echec "clé privée de déchiffrement absente (secret sauvegarde_cle_privee)"

# L'instant cible est écrit dans la configuration : format strict, une seule ligne, fuseau obligatoire (sans fuseau,
# PostgreSQL le lirait en UTC et rejouerait une ou deux heures de trop).
cible_utc=""
if [ -n "${CIBLE:-}" ]; then
	if [ "$(printf '%s' "$CIBLE" | wc -l)" -ne 0 ] ||
		! printf '%s' "$CIBLE" | grep -Eqx '[0-9]{4}-[0-9]{2}-[0-9]{2}[ T][0-9]{2}:[0-9]{2}(:[0-9]{2}(\.[0-9]+)?)?([+-][0-9]{2}(:?[0-9]{2})?|Z)'; then
		echec "instant cible invalide : « $CIBLE ». Format attendu : 2026-11-01 10:00:00+01 (fuseau obligatoire)"
	fi
	cible_utc=$(date -u -d "$CIBLE" +%Y%m%dT%H%M%SZ) || echec "instant cible invalide : « $CIBLE »"
fi

if [ -n "${SAUVEGARDE:-}" ]; then
	case "$SAUVEGARDE" in *[!0-9TZ]*) echec "nom de sauvegarde invalide : $SAUVEGARDE" ;; esac
	source_base="$RACINE/base/$SAUVEGARDE"
else
	# La plus récente sauvegarde commencée avant l'instant cible (ou la plus récente tout court).
	source_base=""
	for chemin in "$RACINE"/base/2*; do
		[ -d "$chemin" ] || continue
		if [ -z "$cible_utc" ] || avant "$(basename "$chemin")" "$cible_utc"; then
			source_base=$chemin
		fi
	done
fi
[ -n "$source_base" ] && [ -f "$source_base/premier_wal" ] ||
	echec "aucune sauvegarde de base utilisable (${SAUVEGARDE:-antérieure à l'instant cible})"
nom_base=$(basename "$source_base")

[ -z "$(ls -A "$DONNEES" 2>/dev/null)" ] || echec "$DONNEES n'est pas vide : restaurer dans un nouveau volume (VOLUME_PGDATA)"
if [ "${FICHIERS:-0}" = "1" ]; then
	[ -z "$(ls -A /stockage 2>/dev/null)" ] || echec "/stockage n'est pas vide : restaurer dans un nouveau volume (VOLUME_STOCKAGE)"
fi

printf 'restauration : déchiffrement de la sauvegarde %s\n' "$nom_base"
mkdir -p "$DONNEES/pg_wal" "$WAL_RESTAURES"
chmod 700 "$DONNEES"
rm -f /tmp/morceau-illisible
dechiffrer_morceaux "$source_base/backup_manifest" >/tmp/backup_manifest
dechiffrer_morceaux "$source_base/base.tar.gz" | tar -xz -C "$DONNEES" || touch /tmp/morceau-illisible
dechiffrer_morceaux "$source_base/pg_wal.tar.gz" | tar -xz -C "$DONNEES/pg_wal" || touch /tmp/morceau-illisible
[ ! -e /tmp/morceau-illisible ] || echec "sauvegarde illisible : clé privée incorrecte ou fichier altéré"
pg_verifybackup -q -n -m /tmp/backup_manifest "$DONNEES" || echec "la sauvegarde ne correspond pas à son manifeste"

# WAL nécessaires au rejeu : ceux de la cible depuis le début de la sauvegarde, puis ceux pas encore expédiés.
premier=$(cat "$source_base/premier_wal")
for chiffre in "$RACINE"/wal/*.gz.cms; do
	[ -f "$chiffre" ] || continue
	nom=$(basename "$chiffre" .gz.cms)
	case "$nom" in
	*.history) ;;
	*) avant "$(printf '%.24s' "$nom")" "$premier" && continue ;;
	esac
	dechiffrer "$chiffre" | gunzip >"$WAL_RESTAURES/$nom" || echec "WAL illisible : $nom"
done
for clair in "$ARCHIVES"/*; do
	[ -f "$clair" ] || continue
	case "$(basename "$clair")" in archtemp*) continue ;; esac
	[ -e "$WAL_RESTAURES/$(basename "$clair")" ] || cp "$clair" "$WAL_RESTAURES/"
done

{
	printf "restore_command = 'cp %s/%%f %%p'\n" "$WAL_RESTAURES"
	if [ -n "${CIBLE:-}" ]; then
		printf "recovery_target_time = '%s'\n" "$CIBLE"
		printf "recovery_target_action = 'promote'\n"
	fi
} >>"$DONNEES/postgresql.auto.conf"
touch "$DONNEES/recovery.signal"
chown 999:999 "$(dirname "$DONNEES")"
chown -R 999:999 "$DONNEES" "$WAL_RESTAURES"
printf 'restauration : base prête (%s%s) ; PostgreSQL rejouera les WAL au démarrage\n' \
	"$nom_base" "${CIBLE:+, jusqu'au $CIBLE}"

if [ "${FICHIERS:-0}" = "1" ]; then
	instantane="$RACINE/fichiers/$nom_base"
	[ -d "$instantane" ] || echec "instantané des fichiers $nom_base absent"
	for source in "$instantane" "$RACINE/fichiers/courant"; do
		(cd "$source" && find . -type f) | while IFS= read -r f; do
			[ -e "/stockage/$f" ] && continue
			mkdir -p "/stockage/$(dirname "$f")" && dechiffrer "$source/$f" >"/stockage/$f" || exit 1
		done || echec "fichier déposé illisible dans $source"
	done
	# Propriétaire et droits des fichiers : ceux de l'application (deploy/lan/compose.yaml, x-durci).
	find /stockage -type d -exec chmod 755 {} + && find /stockage -type f -exec chmod 644 {} +
	chown -R 10001:10001 /stockage
	printf 'restauration : fichiers déposés restaurés (%s fichiers)\n' "$(find /stockage -type f | wc -l)"
fi
