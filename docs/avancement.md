# Avancement

> Mémoire du projet : relire ce fichier après toute interruption.
> Référentiel des exigences : `docs/recette/exigences.csv` (reconstitué, voir D-001).
> Matrice générée : `docs/recette/matrice.csv` (`make matrice`).

## Lot 0 — Socle

Exigences : SEC-01, SEC-02, SEC-03, SEC-05, SEC-06, SEC-08, SEC-09, REF-01, REF-02, ADM-03, ADM-05, ADM-06, RG-14.

| Étape | Contenu | Exigences | État |
| --- | --- | --- | --- |
| 0.1 | Dépôt, docs, Makefile, CI, contrôle des motifs interdits, matrice | — | en cours |
| 0.2 | Projet Django (réglages, santé, DRF, OpenAPI, pytest, ruff, mypy) | SEC-05, SEC-09 | à faire |
| 0.3 | Référentiel de base (sites, bâtiments, espaces, familles) | REF-01, REF-02 | à faire |
| 0.4 | Habilitations rôle × périmètre, actions, `peut()`, `/api/gestion/moi` | RG-14, ADM-03 | à faire |
| 0.5 | Journal d'audit chaîné et immuable, décorateur `@audite`, consultation | SEC-08, ADM-05 | à faire |
| 0.6 | Authentification AD (LDAPS ldap3), groupes → rôles, TOTP admin/régie, limitation de débit | SEC-02, SEC-03, SEC-06, ADM-06 | à faire |
| 0.7 | Façade DMZ (liste blanche, mTLS, en-têtes) et contrôle mTLS côté API | SEC-01, SEC-05 | à faire |
| 0.8 | Docker : images durcies, compose LAN, DMZ et dev, certificats de développement, secrets | SEC-01, SEC-09 | à faire |
| 0.9 | Fronts : squelettes back-office, portail et mobile, connexion agent | SEC-02 | à faire |
| 0.10 | Revue sécurité et métier, e2e, critère de sortie | — | à faire |

Critère de sortie (reconstitué, §9.2 indisponible) : pile LAN et DMZ démarrée, agent authentifié
par l'annuaire de test, droits rôle × périmètre testés (autorisé et refusé), journal d'audit
vérifiable, flux façade → API en mTLS seulement.

## Journal

- 2026-10-31 — Démarrage. Cahier des charges absent (D-001), référentiel reconstitué.
