# ADR 0010 — Sauvegarde et restauration de la base et des fichiers déposés

- Date : 2026-11-01
- Statut : accepté (cible de stockage, copie hors site et coffre de la clé privée à fournir par l'exploitation, `docs/a-brancher.md` § 3)
- Exigences : EXP-01, SEC-08, SEC-09, RG-13, ADR 0005, ADR 0006 ; revues sécurité et métier du 2026-11-01

## Contexte

Le skill `docker-deploiement` exige une sauvegarde PostgreSQL par archivage continu des WAL, avec une perte de
données d'une heure au plus (RPO 1 h) et un test de restauration trimestriel. Jusqu'ici, rien ne sauvegardait la
base : le point était laissé à l'exploitation. Les fichiers déposés (pièces justificatives, documents signés,
photos) sont stockés hors base, dans le volume `stockage` : une sauvegarde de la base seule ne suffit pas.

Les sauvegardes contiennent toute la base et des pièces d'identité : elles doivent être chiffrées, et un serveur
compromis ne doit pas pouvoir les effacer. La règle 9 du `CLAUDE.md` impose de ne pas ajouter de dépendance sans
nécessité ; pour 30 à 50 salles, le volume reste modeste.

## Décisions

1. **Outils de l'image `postgres` seulement.** L'image déjà épinglée fournit `basic_archive`, `pg_basebackup`,
   `pg_verifybackup`, `pg_archivecleanup` et `openssl` : aucune image ni dépendance nouvelle.
2. **Trois volumes, trois rôles.**
   - `wal` (disque local) : seul volume de sauvegarde monté dans `postgres`, qui y archive les WAL en continu
     (`archive_mode=on`, `basic_archive`, `archive_timeout=900`).
   - `sauvegarde-travail` (disque local) : préparation de la sauvegarde de base, vidé après chiffrement.
   - `sauvegardes` (cible, en production sur un stockage distinct) : monté **seulement** dans le service
     `sauvegarde` (et en lecture seule dans `restauration`). Ni `postgres` ni l'API ne peuvent l'effacer.
   La base démarre même si la cible est indisponible (elle ne dépend que du volume local `wal`).
3. **Cycle de 30 minutes** du service `sauvegarde` : WAL archivés compressés, chiffrés, expédiés dans la cible puis
   retirés de `wal` ; miroir chiffré des fichiers déposés. RPO : 15 min d'archivage + 30 min d'expédition.
4. **Sauvegarde de base quotidienne** : tar compressé, WAL inclus (restaurable seul), manifeste SHA-256 vérifié par
   `pg_verifybackup` avant chiffrement. Une sauvegarde invalide n'est pas retenue.
5. **Chiffrement** : CMS (`openssl cms`), AES-256-GCM, pour le certificat `sauvegarde_certificat` (clé RSA). Les gros
   fichiers sont chiffrés par morceaux de 64 Mo, car le déchiffrement CMS charge chaque morceau en mémoire. La clé
   privée est conservée au coffre de la DSI et n'est déposée sur l'hôte que le temps d'une restauration.
6. **Moindre privilège.** Le rôle `equipements_sauvegarde` a le droit `REPLICATION`, qui permet de copier
   physiquement tout le cluster : c'est un rôle sensible. Il ne se connecte qu'en réplication et à la base
   `postgres` (état de l'archivage, `pg_ls_archive_statusdir` accordée nommément, sans le rôle `pg_monitor`), depuis
   le réseau `lan_data` ; toute autre connexion est refusée (`reject` dans `pg_hba.conf`). Le service tourne sans
   root, système de fichiers en lecture seule, `stockage` en lecture seule.
7. **Fichiers déposés.** Miroir chiffré fichier par fichier (les fichiers en cours d'écriture attendent le cycle
   suivant), instantané par liens physiques à chaque sauvegarde de base, sans doublon d'octets. À la restauration :
   instantané de la sauvegarde retenue, complété par les fichiers ajoutés depuis. Un fichier supprimé ou altéré
   après la sauvegarde revient donc dans sa version de la sauvegarde.
8. **Rotation** fondée sur l'horodatage du nom : sauvegardes et instantanés de plus de 14 jours
   (`SAUVEGARDE_RETENTION_JOURS`) supprimés, la plus récente toujours gardée ; WAL antérieurs à la plus ancienne
   sauvegarde conservée supprimés. Un fichier effacé au titre du RGPD (ADR 0006) disparaît des sauvegardes au plus
   tard à la fin de la rétention.
9. **Restauration non destructive.** `restaurer.sh` refuse d'écrire dans un volume qui n'est pas vide : on restaure
   dans des volumes neufs (`VOLUME_PGDATA`, `VOLUME_STOCKAGE`), les volumes d'origine restent intacts. L'instant
   cible exige un fuseau explicite (sans fuseau, PostgreSQL le lirait en UTC) et une seule ligne ; la sauvegarde de
   base retenue par défaut est la plus récente antérieure à la cible.
10. **Surveillance.** Le service est déclaré en mauvaise santé si un cycle échoue pendant plus de 70 minutes :
    archivage désactivé, en échec ou en retard (segment en attente depuis plus d'une heure), expédition, copie des
    fichiers, sauvegarde ou rotation en échec. Il prévient 30 jours avant l'échéance du certificat.
11. **Test réel.** `backend/tests/test_sauvegarde_restauration.py` (`pytest -m integration`) reprend l'image, les
    options et les commandes de préparation du compose : sauvegarde, modifications, restauration à un instant donné,
    contrôle du chiffrement et des refus.

## Conséquences

- **Copie immuable et hors site** : un attaquant maître de l'hôte LAN peut encore effacer la cible. L'exploitation
  doit prévoir des instantanés du stockage non modifiables depuis l'hôte, ou une réplication vers un stockage à
  verrouillage d'objets, et une copie hors site (`docs/a-brancher.md` § 3).
- `audit_cle_hmac` et `cle_chiffrement` ne sont pas dans la base : elles se conservent à part, au coffre, avec la clé
  privée des sauvegardes. Sans elles, une base restaurée ne vérifie plus son journal d'audit et ne déchiffre plus les
  champs chiffrés.
- Volume de la cible : jusqu'à 96 segments WAL de 16 Mo par jour en cas d'écritures continues (moins une fois
  compressés), soit une vingtaine de Go au plus sur 14 jours, plus les sauvegardes de base et les fichiers.
- Sur une base déjà créée, le rôle de sauvegarde se crée une fois à la main (procédure), car les scripts
  d'initialisation ne s'exécutent qu'à la création.
- Le test de restauration sur des données réelles se fait sur un hôte isolé, base seule (procédure) : jamais sur la
  recette, qui travaille sur des données anonymisées.
- Le passage à PostgreSQL 19 (`pg_upgrade`) impose une nouvelle sauvegarde de base aussitôt après.
- Le test d'intégration demande Docker : il n'est pas lancé par `make test` mais par `make test-integration`.
