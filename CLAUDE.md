# Plateforme de gestion des équipements sportifs et associatifs — Ville de Châtillon

Application interne de la Ville : réservation de salles et d'équipements sportifs, portail usagers,
tarification et cautions, documents et signature, planning des gardiens, matériel, valorisation
des avantages en nature, statistiques.

La source de vérité fonctionnelle est `docs/cahier-des-charges.md`. Chaque exigence y porte un
identifiant (ex. `PLA-04`, `RG-05`). Cite cet identifiant dans les commits, tests et PR.

## Architecture en une phrase

Portail public en **DMZ** (façade sans base de données métier) → **un seul flux** HTTPS mTLS
port 8443 → **API métier Django sur le LAN**, qui porte toutes les règles et tous les contrôles
de droits. Tout tourne sous Docker (`deploy/lan`, `deploy/dmz`).

## Arborescence

- `backend/` — Python 3.14, Django 6.1 (→ 6.2 LTS), DRF 3.18, Celery 5.6, PostgreSQL 18 (→ 19), Valkey 9
- `backoffice/` — React 19 + TypeScript 7 (Vite 8, Node.js 26 LTS), application des agents (LAN uniquement)
- `portail/` — React 19 + TypeScript 7, portail public, RGAA 4.1.2 obligatoire
- `mobile/` — PWA hors ligne des gardiens (gymnases sans réseau), accès par VPN

## Contexte de la Ville (à garder en tête)

- 30 à 50 salles et équipements ; volume modeste, pas de sur-architecture.
- Logiciel financier : CIVIL Finances Publiques (Ciril GROUP) ; interface à définir avec l'éditeur.
- Règlement par virement aujourd'hui (quelques CSE) ; **PayFiP en dernier (lot 7)**.
- Aucun réseau dans les gymnases : tout ce qu'utilise un gardien sur place doit marcher hors ligne.
- `deploy/lan/compose.yaml`, `deploy/dmz/compose.yaml` — un compose par zone
- `e2e/` — tests Playwright
- `docs/adr/` — décisions d'architecture numérotées (`NNNN-titre.md`)

## Commandes

```bash
make up            # lance la pile LAN de développement
make test          # pytest backend + vitest front
make lint          # ruff, mypy, eslint, tsc
make e2e           # playwright
make a11y          # tests axe-core du portail
```

## Règles non négociables

1. **Les règles de gestion vivent dans l'API**, jamais seulement dans l'interface. Lis le skill
   `metier-reservations` avant de toucher à une réservation, un statut ou une récurrence.
2. **Droits = rôle × périmètre**, vérifiés côté serveur sur chaque objet (RG-14). Tout endpoint
   a un test d'accès autorisé ET un test d'accès refusé.
3. **Rien de métier en DMZ** : pas de base de données, pas de secret LAN, pas de route
   d'administration. Lis `securite-dmz` avant de toucher à `portail/` ou `/api/portail/*`.
4. **Documents signés, factures, journaux de caution sont immuables** (RG-13) : on corrige par
   avenant ou avoir, jamais par UPDATE.
5. **Montants en centimes (entiers)**, jamais en float. Dates en UTC en base, affichage
   Europe/Paris.
6. **Gratuité = réduction de 100 % sur un tarif de référence conservé** (RG-05), sinon la
   valorisation des avantages en nature est fausse.
7. Toute migration est réversible. Aucune donnée personnelle réelle dans les fixtures.
8. Textes de l'interface en français, accessibles, sans jargon technique.
9. **Versions** : toujours la dernière version stable supportée (cahier des charges §6.6).
   N'ajoute jamais une dépendance sans vérifier sa dernière version, sa maintenance active et
   ses CVE connues ; versions épinglées (lockfiles, images par digest), jamais `latest`.
   Jamais de composant en fin de vie, jamais de préversion en production.

## Skills projet (dans `.claude/skills/`)

| Skill | À charger quand… |
| --- | --- |
| `metier-reservations` | réservations, récurrences, conflits, statuts, saisons |
| `backend-django` | modèles, API, migrations, permissions |
| `frontend-backoffice` | écrans agents, planning, tableau de bord |
| `portail-rgaa` | tout écran du portail public |
| `securite-dmz` | façade, authentification, fichiers, flux réseau |
| `docker-deploiement` | Dockerfile, compose, CI, mise en production |
| `documents-signature` | modèles .docx, PDF, DocuSeal |
| `finances-ciril` | tarifs, factures, titres Ciril, virements, cautions, PayFiP (lot 7) |
| `mobile-gardiens` | application mobile hors ligne des gardiens, synchronisation |
| `planning-personnel` | gardiens, vacations, temps de travail |
| `valorisation-subventions` | avantages en nature, attestations, annexe CA |
| `tests-recette` | avant toute PR et en fin de lot |

## Façon de travailler

1. Partir d'un identifiant d'exigence. Proposer un plan court avant de coder.
2. Écrire les tests d'abord (règle → API → e2e si parcours usager).
3. Implémenter le minimum qui fait passer les tests.
4. Lancer les sous-agents `revue-securite` (si façade, auth, droits, fichiers) et
   `revue-metier` (si règle de gestion) avant de proposer la PR.
5. `make lint test` doit passer. Mettre à jour la doc ou un ADR si le comportement change.

## Définition de « terminé »

- [ ] Exigence couverte par un test qui échoue sans le code
- [ ] Droits testés (autorisé + refusé)
- [ ] Lint, typage, tests verts ; couverture API métier ≥ 80 %
- [ ] Portail : zéro erreur axe-core, navigation clavier vérifiée
- [ ] Migration réversible
- [ ] Doc utilisateur / ADR à jour si besoin
