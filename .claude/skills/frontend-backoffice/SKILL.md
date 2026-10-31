---
name: frontend-backoffice
description: Conventions du back-office React/TypeScript des agents (planning multi-vues, tableau de bord, formulaires, états, accessibilité). À charger pour tout écran dans backoffice/. Utiliser aussi le skill intégré frontend-design pour la direction visuelle et dataviz pour les graphiques.
---

# Back-office (agents)

## Principes d'interface

- **Le tableau de bord répond à « que dois-je traiter aujourd'hui ? »** (DSH-01) : compteurs cliquables qui ouvrent la liste filtrée (DSH-06). Pas de graphique décoratif.
- **Densité maîtrisée** : les agents traitent des dizaines de dossiers ; listes compactes, actions en lot, raccourcis clavier documentés.
- **Chaque écran a ses états** : chargement (squelette), vide (message + action), erreur (message compréhensible + réessayer), droits insuffisants.
- **Statuts** affichés par libellé + couleur + icône (jamais la couleur seule).
- **Vocabulaire métier** du cahier des charges (dossier, occurrence, option, créneau annuel, vacation).

## Planning (PLA-01 à PLA-03)

- Vues : jour, semaine, mois, chronologie par ressource (lignes = espaces), occupation multi-sites, liste.
- La vue liste est l'alternative accessible au planning graphique : toujours disponible.
- Glisser-déposer → appel API de contrôle de conflit **avant** validation visuelle ; en cas de refus, retour à la position initiale + message.
- Vues enregistrées par agent (filtres + mode), stockées côté serveur.
- Couleurs par statut ou par type d'usager (choix de l'agent), légende toujours visible.
- Performance : 50 espaces × 1 semaine < 2 s ; virtualiser les lignes au-delà.

## Architecture

- Vite 8 + React 19 + TypeScript 7 strict, build sous Node.js 26 LTS (versions §6.6, toujours la dernière stable) ; routing par module métier.
- Toute nouvelle dépendance npm : vérifier dernière version, maintenance, licence et `npm audit` ; lockfile commité.
- Données : TanStack Query ; client API généré depuis l'OpenAPI du backend (jamais de types écrits à la main pour les DTO).
- Formulaires : React Hook Form + Zod, messages d'erreur en français, liés aux champs (`aria-describedby`).
- Composants dans `src/ui/` (design system interne) ; un composant = un fichier + un test.
- Les droits viennent de l'API (`/api/gestion/moi` renvoie actions autorisées par périmètre) ; l'UI masque, mais l'API refuse.

## Impression des plannings (IMP)

- Feuilles CSS `@media print` dédiées, A4/A3 paysage, noir et blanc lisible, légende, date d'édition, QR code vers la version en ligne.
- Les PDF officiels (affichage en salle, envoi programmé) sont générés côté serveur (skill `documents-signature`), pas par le navigateur.

## Tests

- Vitest + Testing Library pour les composants ; Playwright pour les parcours (`e2e/`).
- axe-core sur chaque page dans les tests e2e.
