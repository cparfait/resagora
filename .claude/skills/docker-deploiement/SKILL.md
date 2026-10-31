---
name: docker-deploiement
description: Conteneurisation et déploiement de la plateforme (Dockerfiles durcis selon l'ANSSI, compose LAN et DMZ, CI, politique de versions et mises à jour, mise en production et retour arrière). À charger pour tout Dockerfile, compose, pipeline CI ou mise à jour de version.
---

# Docker et déploiement

## Politique de versions (cahier des charges §6.6)

Toujours la **dernière version stable supportée**, jamais `latest`, jamais une préversion en
production, jamais un composant en fin de vie. Références au 31/10/2026 :

| Composant | Version |
| --- | --- |
| Base des images | Debian 13 trixie slim (`python:3.14-slim-trixie`) |
| Python / Django / DRF / Celery | 3.14 / 6.1 → 6.2 LTS / 3.18 / 5.6 |
| PostgreSQL | 18 → 19 à sa première version corrective |
| Valkey | 9 |
| Node.js (build front) | 26 LTS |
| Traefik | 3.7, dernier correctif |
| DocuSeal | 3.1, dernier correctif |
| ClamAV, Gotenberg | dernière stable |

Avant d'écrire une version dans un fichier, **vérifie la version courante** (registre, notes de
version, endoflife.date). Si tu ne peux pas vérifier, signale-le au lieu de deviner.

- Images épinglées par digest : `FROM python:3.14-slim-trixie@sha256:...`.
- Lockfiles obligatoires (`uv.lock` ou `requirements.txt` avec hashes ; `package-lock.json`).
- Renovate : correctifs hebdomadaires, mineures mensuelles, majeures via ADR.
- Reconstruction hebdomadaire des images ; Trivy bloquant sur CVE critiques/hautes corrigeables ; SBOM (Syft) archivé à chaque version.

## Dockerfile type (backend)

```dockerfile
# syntax=docker/dockerfile:1
FROM python:3.14-slim-trixie@sha256:<digest> AS build
RUN pip install --no-cache-dir uv
WORKDIR /app
COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-dev

FROM python:3.14-slim-trixie@sha256:<digest>
RUN useradd --uid 10001 --create-home app
WORKDIR /app
COPY --from=build /app/.venv /app/.venv
COPY --chown=app:app backend/ .
USER 10001
ENV PATH="/app/.venv/bin:$PATH" PYTHONDONTWRITEBYTECODE=1
EXPOSE 8000
HEALTHCHECK CMD ["python", "-c", "import urllib.request;urllib.request.urlopen('http://127.0.0.1:8000/sante')"]
CMD ["gunicorn", "config.wsgi", "--bind", "0.0.0.0:8000", "--workers", "4"]
```

## Durcissement (fiche ANSSI « déploiements de conteneur Docker »)

Dans chaque service compose :

```yaml
read_only: true
tmpfs: [/tmp]
user: "10001:10001"
cap_drop: [ALL]
security_opt: ["no-new-privileges:true"]
pids_limit: 256
mem_limit: 1g
cpus: 1.0
restart: unless-stopped
```

- Jamais de montage du socket Docker, jamais `privileged`.
- Réseaux nommés par fonction (`dmz_front`, `dmz_back`, `lan_app`, `lan_data`) ; la base n'est jamais sur un réseau exposé.
- Secrets via `secrets:` (fichiers), pas `environment:`.
- Hôtes DMZ et LAN distincts ; daemon Docker durci, mises à jour du système hôte.

## Environnements et mise en production

- dev → recette (données anonymisées) → production, mêmes images (promotion par digest).
- Migrations Django réversibles, exécutées par un job dédié avant bascule.
- Retour arrière : redéploiement de l'image précédente + migration inverse documentée.
- Sauvegarde PostgreSQL (archivage continu des WAL, RPO 1 h), test de restauration trimestriel.
- Montée de version majeure PostgreSQL (18 → 19) : `pg_upgrade` répété en recette, procédure écrite, ADR.
