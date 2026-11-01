# ADR 0009 — Refonte graphique : charte de la Ville, Tailwind CSS v4, composants maison

- Date : 2026-11-01
- Statut : accepté
- Exigences : POR-09 (RGAA 4.1.2), PLA-01 ; politique de versions §6.6 ; référence visuelle `DESIGN.md`

## Contexte

La DSI a demandé une refonte graphique du portail et du back-office selon la direction « Larkfield Civic »
(cartes plates, un seul bloc prioritaire par écran), adaptée à l'identité du site ville-chatillon.fr (vert sapin
`#1A5D36`, vert anis, Montserrat, angles droits), avec un planning qui tient dans la fenêtre sans défilement.

## Décision

1. **Charte commune** `charte/charte.css` (jetons Tailwind v4) importée par le portail et le back-office ; la palette,
   les ombres, les flous et les rayons par défaut de Tailwind sont retirés : une classe hors charte ne produit aucun
   style. Contrastes vérifiés dans `DESIGN.md`.
2. **Tailwind CSS 4.3.3** (`@tailwindcss/vite`), chargé sans preflight le temps de la migration ; règles d'éléments en
   couche `base`, motifs partagés entre écrans (`.tableau`, `.alerte`, `.carte`…) sur les jetons.
3. **Composants maison** (`src/ui/`) restylés plutôt que remplacés par shadcn/ui : leurs rôles, libellés et
   comportements (testés) ne changent pas. Fenêtre modale : `<dialog>` natif (focus piégé par le navigateur) ;
   listes, cases et interrupteurs : éléments natifs. Radix n'est donc pas ajouté.
4. **Dépendances ajoutées** (versions épinglées, `npm audit` sans vulnérabilité) : `tailwindcss` et `@tailwindcss/vite`
   4.3.3, `clsx` 2.1.1, `tailwind-merge` 3.7.0 (configuré avec les jetons de la charte), `lucide-react` 1.66.0,
   `@fontsource-variable/montserrat` 5.3.0 (OFL). `class-variance-authority` écarté (aucune publication depuis
   novembre 2024) ; Aceternity UI et 21st.dev écartés (animations et dépendances sans apport).
5. **Police hébergée par l'application** : la CSP (`font-src 'self'`) interdit Google Fonts, et un appel à Google
   depuis le portail transmettrait l'adresse IP des usagers.
6. **Planning sans défilement** (vues semaine et jour) : la page occupe la hauteur de la fenêtre et la grille l'espace
   restant ; positions en pourcentage, plage 8 h – 22 h élargie aux séances, filtres repliables, séances simultanées
   côte à côte. La vue multi-sites garde sa capacité de référence 7 h – 24 h (calcul du taux inchangé).

## Écarts assumés avec la direction B

- Hachures des séances (dégradé répété) conservées : motif fonctionnel, le statut reste lisible sans la couleur.
- Grille du planning : texte de 13 px et séances courtes de moins de 44 px de haut ; la vue « Liste » reste
  l'alternative accessible.
- Pas de sélecteur de langue, de fil d'Ariane généralisé, de « Cette page vous a-t-elle été utile ? » ni de badges de
  compteur dans la navigation : ces fonctions n'existent pas dans l'application.
- Logotype texte en attendant le fichier SVG officiel du service communication.

## Vérifications

`npm run typecheck|lint|test` des deux fronts, parcours Playwright (axe-core, zéro violation), `e2e/tests/
refonte-clavier.spec.ts` (lien d'évitement, focus visible, menu, planning sans défilement), captures
`CAPTURES=avant|apres npx playwright test captures`.

## Revenir dessus

Activer le preflight de Tailwind quand plus aucun écran ne dépend des styles par défaut du navigateur ; réévaluer
shadcn/ui si de nouveaux composants complexes (liste avec recherche, calendrier de saisie) deviennent nécessaires.
