# ADR 0001 — Séparation DMZ / LAN et flux unique mTLS

- Date : 2026-10-31
- Statut : accepté
- Exigences : SEC-01, SEC-05, SEC-07, SEC-09, SEC-10

## Contexte

Le portail des usagers est un service public exposé sur Internet ; les données métier (usagers,
réservations, factures, cautions) et l'annuaire de la Ville sont sur le LAN. Le cahier des charges
(CLAUDE.md, skill `securite-dmz`) impose : aucune donnée métier en DMZ, un seul flux entrant vers
le LAN, en HTTPS mTLS sur le port 8443.

## Décision

1. **DMZ** : Traefik (TLS public, limitation de débit, refus des en-têtes alias), portail statique
   nginx non root, **façade** Python/Starlette sans base de données, Valkey dédié aux sessions
   usagers (jeton API jamais exposé au navigateur), ClamAV pour la quarantaine, DocuSeal (routes de
   signature uniquement).
2. **LAN** : l'API Django est déployée en **deux instances de la même image** :
   - `api` (canal `gestion`) : `/api/gestion/*` (agents, session AD) et `/api/mobile/*` (option A) ;
   - `api-portail` (canal `portail`) : gunicorn en TLS avec `--cert-reqs 2` et une AC dédiée à la
     façade ; seul `/api/portail/*` y est monté (`config/urls_portail.py`), le middleware
     `CanalMiddleware` refuse toute autre route, et chaque vue portail vérifie `CANAL == "portail"`.
3. La façade applique une **liste blanche** méthode × motif exact (`facade/facade/routes.py`) ;
   toute autre route reçoit 404 sans appel à l'API.
4. Réseaux Docker nommés par fonction (`dmz_front`, `dmz_back`, `lan_app`, `lan_data` interne) ;
   la base n'est jamais sur un réseau exposé.

## Conséquences

- Ajouter une route portail exige deux modifications (API + liste blanche) : c'est voulu.
- Une compromission de la façade ne donne ni base, ni secret LAN, ni route d'administration.
- En développement sur un seul hôte, le réseau `liaison_dmz` relie la façade à `api-portail`
  (`deploy/*/compose.dev.yaml`) ; en production, la façade vise l'adresse du pare-feu (`API_URL`).

## Revenir dessus

Toute exposition supplémentaire (ex. option B mobile, ADR 0006) passe par un nouvel ADR et une
analyse de risques.
