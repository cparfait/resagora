---
name: portail-rgaa
description: Règles de conception et d'accessibilité RGAA 4.1.2 du portail public des usagers (associations, entreprises, écoles, particuliers). À charger pour tout écran ou composant dans portail/.
---

# Portail usagers — accessibilité RGAA

Le portail est un service public en ligne : conformité RGAA 4.1.2 obligatoire (POR-09), audit
avant ouverture, déclaration d'accessibilité publiée. Le DSFR est réservé aux sites de l'État :
le portail utilise la charte de la Ville, avec les mêmes exigences.

## Liste de contrôle par composant

- **Structure** : un seul `h1` par page, hiérarchie de titres sans saut, landmarks (`header`, `nav`, `main`, `footer`), lien d'évitement « Aller au contenu ».
- **Titre de page** unique et explicite : « Demande de réservation — étape 2 sur 4 — Portail des équipements ».
- **Formulaires** : `label` visible associé ; champs obligatoires indiqués en texte ; format attendu indiqué (ex. « jj/mm/aaaa ») ; erreurs listées en haut avec liens vers les champs **et** près de chaque champ ; `autocomplete` renseigné (nom, email, tel, adresse).
- **Clavier** : tout est utilisable au clavier, focus visible (contraste ≥ 3:1), ordre logique, pas de piège.
- **Contrastes** : texte ≥ 4,5:1, grands textes et composants d'interface ≥ 3:1.
- **Couleur** jamais seule porteuse d'information (disponibilités : couleur + texte « Libre / Occupé / Demandé »).
- **Calendrier de disponibilités** : grille avec en-têtes de lignes/colonnes (`th scope`), alternative en liste ; navigation par semaine avec boutons nommés.
- **Images** : `alt` pertinent ou vide si décorative ; photos des salles avec description utile (capacité visible dans le texte, pas seulement sur la photo).
- **Fichiers à téléverser** : formats et taille max annoncés avant le champ ; progression annoncée (`aria-live="polite"`).
- **Temps limité** (session) : avertir avant expiration et permettre de prolonger.
- **Documents PDF** fournis : balisés (PDF/UA si possible) ou alternative HTML.
- **Zoom 200 %** et largeur 320 px sans perte de contenu ni défilement horizontal.
- **Langue** : `lang="fr"` ; changements de langue balisés.
- **CAPTCHA** : uniquement si abus constaté, et dans une version accessible (pas d'image seule).

## Parcours

Demande guidée en étapes (POR-04) : 1. Espace et dates → 2. Détails (effectif, objet, matériel)
→ 3. Pièces justificatives (liste selon type d'usager) → 4. Récapitulatif et envoi.
Chaque étape enregistre un brouillon. L'indicateur d'étape est textuel.

## Sécurité côté portail

Le portail ne parle qu'à `/api/portail/*` via la façade DMZ. Aucune donnée d'un autre usager ne
doit transiter (disponibilités publiques anonymisées, POR-02). Voir `securite-dmz`.

## Tests

- axe-core (via Playwright) sur chaque page et chaque état d'erreur : zéro violation.
- Test manuel trimestriel NVDA + Firefox et VoiceOver + Safari sur les parcours principaux.
- Lighthouse accessibilité ≥ 95 en CI (indicatif, ne remplace pas l'audit).
