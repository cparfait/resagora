# ADR 0002 — Façade DMZ en Python (Starlette + httpx)

- Date : 2026-10-31
- Statut : accepté
- Exigences : SEC-01, SEC-04, SEC-06, SEC-07

## Contexte

La façade doit : appliquer la liste blanche, porter les sessions usagers, contrôler CSRF et
origine, limiter le débit, mettre les fichiers en quarantaine (taille, type réel, ClamAV), vérifier
les rappels DocuSeal et PayFiP, et relayer en mTLS. Un reverse proxy seul (Traefik, nginx) ne sait
pas faire la quarantaine antivirale ni la gestion de session sans exposer le jeton.

## Décision

Petite application ASGI Starlette (≈ 500 lignes) avec httpx pour le client mTLS et redis-py pour
Valkey. Même langage, même chaîne de contrôle (ruff, mypy, Trivy) et même image de base que l'API.

## Conséquences

- Aucune logique métier dans la façade : elle ne connaît que des chemins et des natures de corps.
- Tests unitaires avec transport httpx simulé et magasin de sessions en mémoire (`facade/tests`).

## Alternatives écartées

- Node.js : seconde chaîne de dépendances serveur à surveiller.
- Module nginx / Lua : quarantaine et sessions plus difficiles à tester.
