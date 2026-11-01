#!/bin/sh
# EXP-01 — Sauvegarde chiffrée de la base et des fichiers déposés, RPO 1 h (ADR 0010).
#
# Volumes : /archives (WAL archivés par PostgreSQL, seul volume de sauvegarde qu'il voit), /travail (préparation locale
# de la sauvegarde de base), /sauvegardes (cible, ni montée dans postgres ni dans l'API), /stockage (lecture seule).
#
# - WAL : PostgreSQL les archive en continu dans /archives (`basic_archive`, `archive_timeout` 15 min). À chaque cycle
#   (30 min), ils sont compressés, chiffrés et expédiés dans /sauvegardes/wal, puis retirés de /archives.
# - Sauvegarde de base toutes les SAUVEGARDE_BASE_HEURES heures : `pg_basebackup` dans /travail, vérification du
#   manifeste SHA-256, chiffrement par morceaux de 64 Mo dans /sauvegardes/base/<horodatage UTC>.
# - Fichiers déposés : miroir chiffré fichier par fichier (fichiers/courant), et instantané par liens physiques à chaque
#   sauvegarde de base (fichiers/<horodatage>).
# - Chiffrement : CMS, AES-256-GCM, pour le certificat /run/secrets/sauvegarde_certificat ; la clé privée n'est jamais
#   sur l'hôte en fonctionnement normal (coffre de la DSI) : elle ne sert qu'à la restauration.
# - Rotation par l'horodatage du nom : sauvegardes et instantanés de plus de SAUVEGARDE_RETENTION_JOURS jours supprimés
#   (la plus récente est toujours gardée), puis WAL antérieurs à la plus ancienne sauvegarde conservée. Un fichier
#   effacé au titre du RGPD disparaît donc des sauvegardes au bout de la durée de rétention.
#
# Santé : /tmp/derniere-reussite est mis à jour après chaque cycle sans erreur (healthcheck du service).
# SAUVEGARDE_UNE_FOIS=1 : un seul cycle avec sauvegarde de base forcée (tests, sauvegarde manuelle) ;
# avec SAUVEGARDE_SANS_BASE=1, un seul cycle sans sauvegarde de base (expédition des WAL et des fichiers).
set -eu
umask 077

RACINE=/sauvegardes
ARCHIVES=/archives
TRAVAIL=/travail
SOURCE_FICHIERS=${SAUVEGARDE_SOURCE_FICHIERS:-/stockage}
CERTIFICAT=/run/secrets/sauvegarde_certificat
RETENTION_JOURS=${SAUVEGARDE_RETENTION_JOURS:-14}
BASE_HEURES=${SAUVEGARDE_BASE_HEURES:-24}
INTERVALLE=${SAUVEGARDE_INTERVALLE_SECONDES:-1800}
export PGPASSFILE=/tmp/.pgpass

journal() {
	printf '%s sauvegarde %s\n' "$(date -u +%Y-%m-%dT%H:%M:%SZ)" "$*"
}

preparer() {
	printf '%s:*:*:%s:%s\n' "$PGHOST" "$PGUSER" "$(tr -d '\r\n' </run/secrets/postgres_sauvegarde_password)" >"$PGPASSFILE"
	mkdir -p "$RACINE/wal" "$RACINE/base" "$RACINE/fichiers/courant"
	openssl x509 -in "$CERTIFICAT" -noout -checkend 2592000 >/dev/null ||
		journal "ATTENTION le certificat de chiffrement des sauvegardes expire dans moins de 30 jours"
}

# Chiffre l'entrée standard dans le fichier $1 (écriture atomique).
chiffrer() {
	openssl cms -encrypt -binary -stream -aes-256-gcm -outform DER -out "$1.partiel" "$CERTIFICAT" && mv "$1.partiel" "$1"
}

# Chiffre un gros fichier par morceaux de 64 Mo ($1 source, $2 préfixe de destination) : le déchiffrement CMS charge
# chaque morceau en mémoire.
chiffrer_par_morceaux() {
	split -b 64M -d -a 5 --filter="openssl cms -encrypt -binary -aes-256-gcm -outform DER -out \"\$FILE.cms\" $CERTIFICAT" \
		"$1" "$2."
}

# Vrai si l'horodatage $1 précède strictement $2 (noms AAAAMMJJTHHMMSSZ, ordre lexicographique).
avant() {
	[ "$1" != "$2" ] && [ "$(printf '%s
%s
' "$1" "$2" | sort | head -n 1)" = "$1" ]
}

requete() {
	psql -d postgres -AtX -v ON_ERROR_STOP=1 -c "$1"
}

# L'archivage des WAL est fait par le serveur : il doit être actif, sans échec, et sans segment en attente depuis
# plus d'une heure.
verifier_archivage() {
	[ "$(requete "SELECT current_setting('archive_mode')")" = "on" ] || {
		journal "ERREUR archivage des WAL désactivé (archive_mode)"
		return 1
	}
	[ "$(requete "SELECT coalesce(last_failed_time > coalesce(last_archived_time, '-infinity'), false) FROM pg_stat_archiver")" = "f" ] || {
		journal "ERREUR archivage des WAL en échec ($(requete 'SELECT last_failed_wal FROM pg_stat_archiver'))"
		return 1
	}
	en_attente=$(requete "SELECT count(*) FROM pg_ls_archive_statusdir() WHERE name LIKE '%.ready' AND modification < now() - interval '1 hour'") || return 1
	[ "$en_attente" = "0" ] || {
		journal "ERREUR $en_attente segment(s) WAL en attente d'archivage depuis plus d'une heure"
		return 1
	}
}

# WAL archivés par le serveur → copie compressée et chiffrée dans la cible, puis retrait du volume d'archivage.
expedier_wal() {
	for source in "$ARCHIVES"/*; do
		[ -f "$source" ] || continue
		nom=$(basename "$source")
		case "$nom" in archtemp* | *.partiel) continue ;; esac
		cible="$RACINE/wal/$nom.gz.cms"
		if [ ! -e "$cible" ]; then
			gzip -c "$source" | chiffrer "$cible" || return 1
		fi
		rm -f "$source"
	done
}

# Miroir chiffré des fichiers déposés. Les fichiers de moins de 2 minutes attendent le cycle suivant (écriture en
# cours). Un fichier modifié est rechiffré sous un nouvel inode pour ne pas altérer les instantanés ; la date de
# modification de la source est reportée sur la copie pour détecter les modifications suivantes.
copier_fichiers() {
	courant="$RACINE/fichiers/courant"
	(cd "$SOURCE_FICHIERS" && find . -type f -mmin +1) | while IFS= read -r f; do
		if [ ! -e "$courant/$f" ] || [ "$SOURCE_FICHIERS/$f" -nt "$courant/$f" ]; then
			mkdir -p "$courant/$(dirname "$f")" && rm -f "$courant/$f" &&
				chiffrer "$courant/$f" <"$SOURCE_FICHIERS/$f" && touch -r "$SOURCE_FICHIERS/$f" "$courant/$f" || exit 1
		fi
	done || return 1
	# Fichiers supprimés de la source (purge RGPD, éditions temporaires) : retirés du miroir ; les instantanés les
	# gardent jusqu'à leur rotation.
	(cd "$courant" && find . -type f) | while IFS= read -r f; do
		[ -e "$SOURCE_FICHIERS/$f" ] || rm -f "$courant/$f" || exit 1
	done || return 1
}

base_attendue() {
	[ "${SAUVEGARDE_SANS_BASE:-0}" = "1" ] && return 1
	[ "${SAUVEGARDE_UNE_FOIS:-0}" = "1" ] && return 0
	derniere=$(find "$RACINE/base" -mindepth 1 -maxdepth 1 -type d -name '2*' | sort | tail -n 1)
	[ -z "$derniere" ] && return 0
	avant "$(basename "$derniere")" "$(date -u -d "-$BASE_HEURES hours" +%Y%m%dT%H%M%SZ)"
}

# Nom du segment WAL qui contient le début d'une sauvegarde (segments de 16 Mo, valeur par défaut).
premier_wal() {
	ligne=$(tr -d ' \n' <"$1" | grep -o '"Timeline":[0-9]*,"Start-LSN":"[0-9A-F]*/[0-9A-F]*"' | head -n 1)
	tl=$(printf '%s' "$ligne" | sed 's/.*"Timeline":\([0-9]*\),.*/\1/')
	lsn=$(printf '%s' "$ligne" | sed 's/.*"Start-LSN":"\([0-9A-F]*\/[0-9A-F]*\)"/\1/')
	printf '%08X%08X%08X' "$tl" "0x${lsn%/*}" "$((0x${lsn#*/} >> 24))"
}

sauvegarder_base() {
	nom=$(date -u +%Y%m%dT%H%M%SZ)
	clair="$TRAVAIL/$nom"
	destination="$RACINE/base/.$nom"
	rm -rf "${TRAVAIL:?}"/* "$destination"
	journal "sauvegarde de base $nom"
	pg_basebackup -D "$clair" -F t -z -X stream -c fast --manifest-checksums=SHA256 -l "sauvegarde $nom" || return 1
	pg_verifybackup -q -F t -n "$clair" || {
		journal "ERREUR sauvegarde $nom : vérification du manifeste en échec"
		return 1
	}
	mkdir -p "$destination"
	premier_wal "$clair/backup_manifest" >"$destination/premier_wal"
	for fichier in base.tar.gz pg_wal.tar.gz backup_manifest; do
		chiffrer_par_morceaux "$clair/$fichier" "$destination/$fichier" || return 1
	done
	rm -rf "$clair"
	mv "$destination" "$RACINE/base/$nom"
	cp -al "$RACINE/fichiers/courant" "$RACINE/fichiers/$nom" || return 1
	journal "sauvegarde de base $nom terminée ($(du -sh "$RACINE/base/$nom" | cut -f1), chiffrée)"
}

rotation() {
	find "$RACINE/base" -mindepth 1 -maxdepth 1 -type d -name '.*' -mmin +1440 -exec rm -rf {} + || return 1
	recente=$(find "$RACINE/base" -mindepth 1 -maxdepth 1 -type d -name '2*' | sort | tail -n 1)
	[ -n "$recente" ] || return 0
	limite=$(date -u -d "-$RETENTION_JOURS days" +%Y%m%dT%H%M%SZ)
	for dossier in "$RACINE/base" "$RACINE/fichiers"; do
		for chemin in "$dossier"/2*; do
			[ -d "$chemin" ] || continue
			nom=$(basename "$chemin")
			if avant "$nom" "$limite" && [ "$nom" != "$(basename "$recente")" ]; then
				rm -rf "$chemin" || return 1
			fi
		done
	done
	ancienne=$(find "$RACINE/base" -mindepth 1 -maxdepth 1 -type d -name '2*' | sort | head -n 1)
	pg_archivecleanup -x .gz.cms "$RACINE/wal" "$(cat "$ancienne/premier_wal")" || return 1
}

cycle() {
	ok=0
	verifier_archivage || ok=1
	expedier_wal || {
		journal "ERREUR expédition des WAL"
		ok=1
	}
	copier_fichiers || {
		journal "ERREUR copie des fichiers déposés"
		ok=1
	}
	if base_attendue; then
		sauvegarder_base || {
			journal "ERREUR sauvegarde de base"
			ok=1
		}
	fi
	rotation || {
		journal "ERREUR rotation"
		ok=1
	}
	[ "$ok" = 0 ] && touch /tmp/derniere-reussite
	return "$ok"
}

preparer
if [ "${SAUVEGARDE_UNE_FOIS:-0}" = "1" ]; then
	cycle
	exit $?
fi
journal "démarrage : base toutes les ${BASE_HEURES} h, cycle toutes les ${INTERVALLE} s, rétention ${RETENTION_JOURS} jours"
while :; do
	cycle || true
	sleep "$INTERVALLE"
done
