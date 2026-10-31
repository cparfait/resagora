# Kit Claude Code — Plateforme de gestion des équipements

Ce kit se copie à la racine du dépôt Git du projet. Il donne à Claude Code le contexte métier,
les conventions techniques et les exigences de sécurité du cahier des charges.

## Contenu

```
CLAUDE.md                         contexte, règles non négociables, définition de « terminé »
.claude/settings.json             permissions (commandes autorisées / interdites), hook de formatage
.claude/skills/                   12 skills projet chargés automatiquement selon la tâche
  metier-reservations/            statuts, récurrences, conflits, campagne annuelle
  backend-django/                 structure Django 6 / DRF / Celery, permissions, tests
  frontend-backoffice/            back-office React, planning, tableau de bord
  portail-rgaa/                   portail public et accessibilité RGAA 4.1.2
  securite-dmz/                   DMZ / LAN, authentification, fichiers, OWASP ASVS
  docker-deploiement/             images durcies ANSSI, versions, CI, mise en production
  documents-signature/            modèles .docx, PDF/A, DocuSeal
  finances-ciril/                 tarifs, factures, titres Ciril, virements, cautions, PayFiP (lot 7)
  mobile-gardiens/                application mobile hors ligne des gardiens
  planning-personnel/             gardiens, vacations, temps de travail
  valorisation-subventions/       avantages en nature, attestations, annexe CA
  tests-recette/                  stratégie de tests et recette
.claude/agents/
  revue-securite.md               sous-agent de relecture sécurité
  revue-metier.md                 sous-agent de relecture des règles métier
```

## Mise en place

1. Copier le contenu du dossier à la racine du dépôt.
2. Exporter le cahier des charges en Markdown dans `docs/cahier-des-charges.md`.
3. Lancer Claude Code à la racine : il lit `CLAUDE.md` et propose les skills selon la tâche.
4. Première tâche conseillée : « Lot 0 — mets en place le socle (structure, Docker LAN/DMZ,
   authentification AD, rôles × périmètres, journal d'audit) en suivant CLAUDE.md. »

## Entretien

Les skills sont la mémoire du projet : mettez-les à jour quand une règle ou une version change
(revue annuelle des versions en novembre, voir §6.6 du cahier des charges).
