# Sauvegarde et restauration (EXP-01)

Principes et choix : [ADR 0010](adr/0010-sauvegarde-et-restauration.md). Toutes les commandes se lancent depuis la
racine du dépôt, sur l'hôte LAN.

## Ce qui est sauvegardé, et quand

Tout est **chiffré** avant d'arriver dans la cible des sauvegardes (volume `sauvegardes`).

| Quoi | Quand | Où, dans la cible |
| --- | --- | --- |
| Journaux de transactions (WAL) | archivés au plus tard 15 min après une écriture, expédiés toutes les 30 min | `wal/` |
| Sauvegarde complète de la base, vérifiée | toutes les 24 h (`SAUVEGARDE_BASE_HEURES`) | `base/<AAAAMMJJTHHMMSSZ>/` (heure UTC) |
| Fichiers déposés (pièces, documents, photos) | toutes les 30 min | `fichiers/courant/`, et un instantané par sauvegarde complète |

- Conservation : 14 jours (`SAUVEGARDE_RETENTION_JOURS`). La sauvegarde la plus récente est toujours gardée.
- Perte de données maximale : 45 minutes environ.
- Volume à prévoir pour la cible : jusqu'à une vingtaine de Go de WAL sur 14 jours, plus les sauvegardes complètes
  (taille de la base compressée, une par jour) et les fichiers déposés.

## Mise en place

1. **Clé de chiffrement.** Créer la paire de clés sur un poste de la DSI, pas sur l'hôte :

   ```bash
   openssl req -x509 -newkey rsa:4096 -noenc -days 3650 -subj "/CN=Sauvegardes plateforme equipements" -keyout sauvegarde_cle_privee.pem -out sauvegarde_certificat.pem
   ```

   - Copier `sauvegarde_certificat.pem` (public) dans `deploy/lan/secrets/`.
   - Ranger `sauvegarde_cle_privee.pem` au coffre de la DSI, avec `audit_cle_hmac` et `cle_chiffrement`, et la
     supprimer du poste. Sans elle, aucune sauvegarde n'est lisible.
   - Le service prévient 30 jours avant l'échéance du certificat : en créer un nouveau, garder l'ancienne clé privée
     tant que des sauvegardes chiffrées avec elle sont conservées (14 jours).
   - En développement, `make certs` crée une paire de test dans `deploy/lan/secrets/`.
2. Fournir le secret `deploy/lan/secrets/postgres_sauvegarde_password` (en développement : `make secrets`).
3. **Cible.** Placer le volume `sauvegardes` sur un stockage distinct de l'hôte (`VOLUME_SAUVEGARDES`, ou un volume
   Docker sur NFS) :
   - sur NFS avec `root_squash`, créer le répertoire à l'avance, propriétaire `999:999`, droits `700` ;
   - prévoir des **instantanés non modifiables depuis l'hôte** (ou une réplication vers un stockage à verrouillage
     d'objets) et une **copie hors site** : un attaquant maître de l'hôte pourrait sinon effacer les sauvegardes.
   La base ne dépend pas de la cible : si elle est indisponible, seul le service `sauvegarde` s'arrête, et les WAL
   attendent dans le volume local `wal`.
4. **Base déjà créée seulement** : créer le rôle de sauvegarde, une fois, puis redémarrer la base pour activer
   l'archivage :

   ```bash
   docker compose -f deploy/lan/compose.yaml up -d postgres
   ```

   ```bash
   docker compose -f deploy/lan/compose.yaml exec -u postgres postgres sh /docker-entrypoint-initdb.d/02-sauvegarde.sh
   ```

5. Démarrer la pile : `docker compose -f deploy/lan/compose.yaml up -d`. Le service `sauvegarde` fait une
   sauvegarde complète dès son démarrage.

## Vérifier que tout va bien

```bash
docker compose -f deploy/lan/compose.yaml ps sauvegarde
```

```bash
docker compose -f deploy/lan/compose.yaml logs --tail 20 sauvegarde
```

- L'état doit être `healthy`. Brancher cet état sur la supervision de la Ville.
- Toute ligne `ERREUR` mérite une analyse : un archivage en échec ou en retard fait grossir le disque de la base.

Sauvegarde complète à la demande (avant une mise à jour, par exemple) :

```bash
docker compose -f deploy/lan/compose.yaml run --rm -e SAUVEGARDE_UNE_FOIS=1 sauvegarde
```

## Restaurer

La restauration écrit toujours dans des volumes **neufs** : les volumes actuels restent intacts.

1. Arrêter la pile, sans supprimer les volumes :

   ```bash
   docker compose -f deploy/lan/compose.yaml stop
   ```

2. Sortir la clé privée du coffre et la déposer dans `deploy/lan/secrets/sauvegarde_cle_privee.pem` (droits `600`).
3. Écrire dans `deploy/lan/.env` **avant tout** les noms des volumes neufs, pour que la restauration et tous les
   démarrages suivants utilisent les mêmes volumes :

   ```
   VOLUME_PGDATA=equipements-lan_pgdata-20261101
   VOLUME_STOCKAGE=equipements-lan_stockage-20261101
   ```

4. Choisir l'instant voulu, **avec son fuseau** (`+01` en hiver, `+02` en été, ou `Z` pour UTC), et lancer la
   restauration. Exemple en PowerShell :

   ```powershell
   $env:CIBLE = "2026-11-01 10:00:00+01"
   $env:FICHIERS = "1"
   docker compose -f deploy/lan/compose.yaml --profile restauration run --rm restauration
   ```

   - Sans `CIBLE`, tous les WAL disponibles sont rejoués (dernier état connu).
   - Sans `SAUVEGARDE`, le script prend la sauvegarde complète la plus récente antérieure à l'instant voulu.
   - Les fichiers déposés reviennent dans leur état de cette sauvegarde, complétés par les fichiers ajoutés depuis.

5. **Supprimer la clé privée de l'hôte** (`deploy/lan/secrets/sauvegarde_cle_privee.pem`) et la remettre au coffre.
6. Redémarrer la pile. PostgreSQL rejoue les WAL jusqu'à l'instant voulu, puis ouvre la base :

   ```bash
   docker compose -f deploy/lan/compose.yaml up -d
   ```

7. Contrôler : `python manage.py verifier_deploiement` dans le conteneur `api`, connexion au back-office, derniers
   dossiers. Faire une sauvegarde complète à la demande (ci-dessus).

## Test trimestriel

Le skill `docker-deploiement` demande un test de restauration chaque trimestre.

- **Test automatique**, sans donnée réelle : `make test-integration` (ou
  `cd backend && pytest -m integration tests/test_sauvegarde_restauration.py`). Il sauvegarde, modifie, puis
  restaure à un instant donné dans des conteneurs jetables.
- **Test sur les sauvegardes de production**, sur un hôte isolé de la DSI, jamais sur la recette (qui travaille sur
  des données anonymisées) :
  - sans accès réseau sortant ;
  - restauration comme ci-dessus, puis démarrage de la **seule base** :
    `docker compose -f deploy/lan/compose.yaml up -d postgres` (ni API, ni tâches, ni envoi de courriels ou de SMS) ;
  - contrôles en SQL : nombre de dossiers, dernière écriture, `pg_is_in_recovery()` à faux ;
  - puis suppression des conteneurs et des volumes restaurés, et de la clé privée.
