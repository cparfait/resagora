# ADR 0004 — Outillage des fronts : TypeScript 7, oxlint, génération OpenAPI isolée, service worker maison

- Date : 2026-10-31
- Statut : accepté
- Exigences : POR-09, MOB-01 ; politique de versions §6.6

## Décision

1. **TypeScript 7.0.2** (§6.6) pour le typage (`tsc --noEmit`) ; Vite 8 transpile.
2. **oxlint 1.90** (règles react, react-hooks, jsx-a11y, typescript, import, unicorn) au lieu
   d'ESLint : `typescript-eslint` 8.72 n'accepte que TypeScript < 6.1.
3. **openapi-typescript** (qui exige l'API JavaScript de TypeScript 5) est isolé dans
   `outils/codegen` avec TypeScript 5.9.3, utilisé seulement pour générer `src/api/schema.d.ts`.
   `minimatch` y est forcé en 11.0.3 (avis GHSA-g3hv-75wg-m249).
4. **Service worker écrit à la main** pour l'application mobile au lieu de `vite-plugin-pwa` /
   Workbox, qui apportaient 10 vulnérabilités modérées (`npm audit`) par leurs dépendances de build.

## Revenir dessus

Revenir à ESLint quand `typescript-eslint` prendra en charge TypeScript 7 ; réévaluer Workbox à
chaque revue annuelle des versions (novembre).
