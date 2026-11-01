# Resagora — équipements sportifs et associatifs de la Ville de Châtillon

Application interne de la Ville de Châtillon (92) pour gérer ses salles et équipements sportifs et associatifs :
réservations et créneaux annuels, portail des usagers, tarification et cautions, documents et signature
électronique, planning des gardiens (avec une application mobile hors ligne), matériel, valorisation des
avantages en nature, statistiques et éditions.

- **Référentiel fonctionnel** : 149 exigences identifiées (`PLA-04`, `RG-05`…) dans `docs/recette/exigences.csv`,
  chacune reliée à son code et à ses tests (`docs/recette/matrice.csv`).
- **Volume visé** : 30 à 50 salles et équipements ; pas de sur-architecture.
- **Accessibilité** : portail public conforme RGAA 4.1.2 (zéro violation axe-core sur les parcours testés).

---

## Sommaire

1. [Fonctionnalités](#fonctionnalités)
2. [Architecture](#architecture)
3. [Technologies](#technologies)
4. [Arborescence](#arborescence)
5. [Démarrer en local](#démarrer-en-local)
6. [Données de démonstration (reprises de CityResa)](#données-de-démonstration-reprises-de-cityresa)
7. [Comptes et adresses de recette](#comptes-et-adresses-de-recette)
8. [Tests et contrôles qualité](#tests-et-contrôles-qualité)
9. [Charte graphique](#charte-graphique)
10. [Sécurité et données personnelles](#sécurité-et-données-personnelles)
11. [Règles de développement](#règles-de-développement)
12. [Documentation](#documentation)
13. [Avant la mise en service](#avant-la-mise-en-service)

---

## Fonctionnalités

| Lot | Contenu |
| --- | --- |
| **0 — Socle** | Authentification Active Directory (LDAP) avec double authentification ; droits **rôle × périmètre** vérifiés côté serveur sur chaque objet (RG-14) ; journal d'audit chaîné et ancré ; fichiers déposés analysés par antivirus (ClamAV). |
| **1 — Réservations** | Référentiel (sites, bâtiments, espaces hiérarchisés et partageables, horaires, fermetures, saisons, calendrier scolaire zone C) ; réservations ponctuelles et récurrentes (quotidiennes, hebdomadaires, mensuelles) ; conflits garantis par la base (RG-01) ; options ; campagne annuelle et arbitrage ; **planning à six vues** (jour, semaine, mois, chronologie par espace, multi-sites, liste), sans défilement en vue semaine ; **semaine type** d'un espace ou d'un site. |
| **2 — Portail et échanges** | Portail public : catalogue, disponibilités, inscription, demande guidée en quatre étapes, suivi, messagerie ; documents générés depuis des modèles .docx (PDF/A via Gotenberg) ; signature DocuSeal ou manuscrite constatée ; courriels et SMS. |
| **3 — Finances** | Grilles tarifaires votées, réductions et gratuités sur tarif de référence (RG-05), simulateur public ; devis, factures, acomptes, avoirs immuables (RG-13) ; export des titres vers CIVIL Finances Publiques (Ciril GROUP) et import des encaissements ; cautions avec état des lieux et double validation. |
| **4 — Personnel et mobile** | Présence d'un agent réglée salle par salle (« Présence par site » : seules ces salles créent des besoins) ; planning « qui est où » par agent (heures de la semaine, clic pour modifier son planning) ou par site ; besoins de gardiennage générés par les séances, vacations, trames, absences, remplacements ; contrôle du temps de travail, compteurs, export paie ; plannings PDF et **iCal compatibles Outlook** ; **PWA mobile hors ligne** des gardiens (gymnases sans réseau) : pointage, états des lieux, photos, signature, synchronisation chiffrée. |
| **5 — Matériel** | Catalogue, stocks par site, prêts séance par séance, retours et manquants, contrôles périodiques, pannes. |
| **6 — Pilotage** | Valorisation des avantages en nature (attestations, annexe du compte administratif, seuil de 23 000 €) ; statistiques (occupation, répartition, recettes, personnel) ; tableaux de bord « à traiter » et direction ; **impressions au format calendrier** (planning d'un espace ou d'un site, semaine type, feuille de salle, planning des vacations) ou en liste ; envoi programmé du planning. |
| **7 — PayFiP** | Paiement en ligne (Titres et Rôles ou Régie) : tentative tracée, notification signée et revérifiée, rapprochement, trop-perçus. |

Trois applications pour trois publics :

- **Back-office** des agents (réseau interne uniquement) : environ 65 écrans, rangés comme dans CityResa en une
  douzaine de rubriques (avec pastilles « à traiter »), plus une section « Administration » repliable ; les écrans
  d'une rubrique s'ouvrent par des onglets ;
- **Portail public** des usagers (associations, écoles, entreprises, particuliers) ;
- **Application mobile** des gardiens, utilisable sans réseau, accessible par VPN.

## Architecture

```
            Internet                         DMZ                                LAN de la Ville
 ┌───────────────────────┐   ┌──────────────────────────────┐   ┌─────────────────────────────────────────┐
 │ Usagers (navigateur)  │──▶│ Portail (React, fichiers     │   │ API métier Django (règles + droits)     │
 └───────────────────────┘   │ statiques) + façade Starlette│──▶│ PostgreSQL · Valkey · Celery            │
                             │ — aucune base de données     │   │ Gotenberg · ClamAV · DocuSeal           │
                             │ — aucun secret du LAN        │   │ Back-office (React) · Mobile (PWA)      │
                             └──────────────────────────────┘   └─────────────────────────────────────────┘
                                         un seul flux : HTTPS mTLS, port 8443
```

- Le **portail en DMZ** n'a ni base de données métier, ni secret du LAN, ni route d'administration (ADR 0001, 0002).
- **Un seul flux** traverse la frontière : HTTPS avec authentification mutuelle (mTLS) sur le port 8443.
- **Toutes les règles de gestion et tous les contrôles de droits vivent dans l'API**, jamais seulement dans
  l'interface.
- Tout tourne sous Docker, avec un compose par zone : `deploy/lan/compose.yaml` et `deploy/dmz/compose.yaml`.

## Technologies

| Domaine | Choix |
| --- | --- |
| API | Python 3.14, Django 6.1, Django REST Framework 3.18, Celery 5.6 |
| Données | PostgreSQL 18, Valkey 9 (file de tâches et cache) |
| Façade DMZ | Starlette (Python) |
| Fronts | React 19, TypeScript 7, Vite 8, TanStack Query, Tailwind CSS 4.3 (charte de la Ville), icônes Lucide |
| Mobile | PWA React, IndexedDB chiffrée, service worker écrit à la main |
| Documents | modèles .docx, PDF/A par Gotenberg, signature DocuSeal |
| Qualité | pytest, ruff, mypy, Vitest, oxlint, Playwright, axe-core, Trivy |
| Exécution | Docker (images épinglées par empreinte), Node.js 26 LTS |

Politique de versions : toujours la dernière version stable supportée ; dépendances épinglées (lockfiles, images par
empreinte) ; aucune préversion ni composant en fin de vie ; chaque ajout vérifié (maintenance, licence, CVE).

## Arborescence

```
backend/      API Django : apps métier (reservations, finances, personnel, materiel, valorisation, pilotage…)
facade/       Façade DMZ (Starlette) : seule porte d'entrée du portail vers le LAN
backoffice/   Application des agents (React + TypeScript)
portail/      Portail public des usagers (React + TypeScript, RGAA 4.1.2)
mobile/       PWA hors ligne des gardiens
charte/       Jetons de la charte graphique (Tailwind v4), communs au portail et au back-office
e2e/          Parcours Playwright et contrôles d'accessibilité axe-core
deploy/       Compose LAN, DMZ et services de test ; images ; configuration nginx, PostgreSQL, sauvegardes
docs/         ADR, recette (exigences, matrice), API OpenAPI, sécurité (Trivy, SBOM), rapport de livraison
outils/       Outils de développement (génération OpenAPI, extraction des données d'exemple de CityResa)
scripts/      Secrets et certificats de développement
DESIGN.md     Charte graphique (couleurs, typographie, composants, contrastes vérifiés)
CLAUDE.md     Règles du projet pour les agents de développement
```

## Démarrer en local

**Prérequis** : Docker (avec Compose), Python 3.14 avec [uv](https://docs.astral.sh/uv/), Node.js 26 LTS, GNU Make.

```bash
make preparer        # environnements Python et dépendances npm verrouillées
make secrets         # secrets de développement aléatoires (deploy/*/secrets, jamais versionnés)
make certs           # autorités et certificats de développement (mTLS, LDAPS)
make up              # services de test + pile LAN (API, tâches, back-office, mobile)
make up-dmz          # façade, portail et signature (DMZ)
make demo            # données de démonstration (reprises de CityResa)
```

Pour ouvrir le portail et l'application mobile depuis le poste, deux réglages sont à faire une fois :

1. **Fichier hosts** : faire pointer `equipements.chatillon.test`, `signature.chatillon.test` et
   `gardiens.chatillon.local` vers `127.0.0.1`.
2. **Autorité de certification** : approuver `deploy/lan/secrets/ac_interne.crt`, générée par `make certs`.

Pour arrêter la pile : `make down`.

## Données de démonstration (reprises de CityResa)

Le jeu de démonstration reprend les **données d'exemple de l'application CityResa**, pour comparer les deux
applications avec les mêmes données :

- **13 sites et 16 espaces** de la ville : Espace Maison Blanche, salles Gabriel Péri, Henri Matisse et Folie
  Desmares, Chalet des quatre vents, gymnases, dojo Marcel Doret, stade Guy Môquet, terrain multisport. Avec leurs
  horaires, capacités, équipements, règlements, consignes et cautions.
- **46 usagers**, dont les 41 associations du guide des sports de la Ville.
- **47 réservations** à tous les statuts, avec les récurrences hebdomadaires, les stages sur plusieurs jours et les
  conférences mensuelles.
- **Tarifs** par espace (gratuités en réduction de 100 % sur un tarif de référence, RG-05), **matériel** et prêts.

Ces données s'accompagnent de la saison 2026-2027 avec les vacances de la zone C, de 8 gardiens avec leurs trames et
vacations, de devis, factures et cautions, et d'un exercice de valorisation.

**Plannings simulés.** Les données de CityResa occupent peu les salles. S'y ajoutent donc, par défaut, des plannings
simulés, absents de CityResa :
- environ 125 créneaux hebdomadaires des associations selon leur discipline (arts martiaux au dojo, sports de ballon
  en gymnase, football et rugby au stade, danse et yoga en salle) ;
- le sport scolaire en journée ;
- des galas, lotos et tournois, et les assemblées générales.

Chaque dossier simulé porte la mention « Créneau simulé (démonstration) ». Pour une comparaison stricte avec CityResa,
sans simulation, chargez avec `python manage.py charger_demo --sans-simulation`.

Les dates sont relatives au jour du chargement : chargées le même jour, les deux applications montrent les mêmes
séances aux mêmes dates.

**Aucune donnée personnelle réelle.** Les associations de CityResa nomment de vraies personnes, issues du guide des
sports. Seules les structures sont reprises ; leurs contacts sont fictifs, sur le domaine réservé `exemple.test`.
Le test du jeu de démonstration le vérifie.

Pour refaire l'extraction quand CityResa évolue :

```bash
node outils/cityresa/extraire.mjs <chemin du dépôt CityResa>   # met à jour backend/apps/noyau/demo/cityresa.json
```

L'outil n'exécute que les parties « données » du script de démonstration de CityResa, dans un dossier temporaire,
sans base de données, sans réseau et sans lire de fichier `.env`.

## Comptes et adresses de recette

| Application | Adresse |
| --- | --- |
| Back-office | https://localhost |
| Portail public | https://equipements.chatillon.test:9443 |
| Application mobile | https://gardiens.chatillon.local |
| Mailpit (courriels de test) | http://127.0.0.1:58025 |
| Simulateurs (DocuSeal, PayFiP, SMS) | http://127.0.0.1:53010 |

**Comptes des agents**, dans l'annuaire OpenLDAP de recette :

- `admin.recette`, `gest.ville`, `gest.complexe`, `accueil.recette`, `regie.recette`, `finances.recette`,
  `planif.recette`, `direction.recette`, `elu.recette`, `materiel.recette` ;
- `gardien01` à `gardien08`.

Leur mot de passe commun est généré par `make secrets` dans `deploy/dev/secrets/mdp_agents_demo`. Ce fichier n'est
jamais versionné.

## Tests et contrôles qualité

```bash
make test            # pytest (API, façade) + Vitest (fronts)
make lint            # ruff, mypy, oxlint, tsc, recherche de motifs interdits (TODO, fonctions vides…)
make e2e             # parcours Playwright sur la pile de recette
make a11y            # contrôles d'accessibilité axe-core (WCAG 2.2 AA) des parcours
make matrice         # chaque exigence a son code et ses tests
make migrations-reversibles   # toutes les migrations s'appliquent puis se défont
make trivy           # vulnérabilités des images et dépendances (bloquant sur CVE critiques et hautes)
make recette         # tout ce qui précède
```

Définition de « terminé » :

- l'exigence est couverte par un test qui échoue sans le code ;
- les droits sont testés, en accès autorisé comme en accès refusé ;
- lint, typage et tests sont verts ; la couverture de l'API métier atteint au moins 80 % ;
- le portail ne présente aucune erreur axe-core, et la navigation au clavier est vérifiée ;
- les migrations sont réversibles ;
- la documentation et les ADR sont à jour.

Captures avant/après de la refonte graphique : `CAPTURES=apres npx playwright test captures` (dans `e2e/`).

## Charte graphique

L'interface suit l'identité du site **ville-chatillon.fr** ; la référence complète est dans `DESIGN.md`.

- **Couleurs** : vert sapin `#1A5D36`, vert anis, vert clair ; fond gris clair et cartes blanches.
- **Formes** : angles droits, design plat (ni ombre ni dégradé), filet anis sous les titres.
- **Bloc prioritaire** : un seul par écran, sur fond anis clair.
- **Police** : Montserrat, hébergée par l'application. La politique de sécurité interdit Google Fonts.

Les jetons de couleur sont définis dans `charte/charte.css` (Tailwind v4). Comme les couleurs par défaut de Tailwind
sont retirées, une classe hors charte ne produit aucun style. Tous les contrastes sont vérifiés (WCAG 2.2 AA) dans
`DESIGN.md`.

## Sécurité et données personnelles

- Séparation DMZ / LAN et flux mTLS unique (ADR 0001).
- Authentification AD et double authentification pour les agents ; comptes usagers validés par la Ville.
- Droits rôle × périmètre vérifiés côté serveur sur chaque objet (ADR 0005).
- Journal d'audit chaîné et ancré.
- Fichiers déposés analysés par antivirus.
- Politique de sécurité des contenus stricte (CSP `'self'`).
- Documents signés, factures et journaux de caution **immuables** : on corrige par avenant ou par avoir (RG-13,
  ADR 0006).
- Montants en centimes (entiers) ; dates en UTC en base, affichées en heure de Paris.
- RGPD :
  - durées de conservation (ADR 0006) ;
  - anonymisation ;
  - aucune donnée personnelle réelle dans les jeux de test et de démonstration.
- Sauvegardes chiffrées et restauration éprouvée (ADR 0010, `docs/sauvegarde-restauration.md`, `make test-sauvegarde`).
- Secrets uniquement dans `deploy/*/secrets` (ignorés par Git), jamais dans le code.

## Règles de développement

Les règles complètes sont dans `CLAUDE.md` et les skills de `.claude/skills/`. En résumé :

1. Partir d'un identifiant d'exigence et le citer dans les commits, les tests et les PR.
2. Écrire les tests d'abord : règle de gestion, puis API, puis parcours e2e.
3. Les règles de gestion vivent dans l'API ; tout endpoint a un test d'accès autorisé et un test d'accès refusé.
4. Rien de métier en DMZ.
5. Gratuité = réduction de 100 % sur un tarif de référence conservé (RG-05).
6. Toute migration est réversible.
7. Interface en français, accessible, sans jargon.

## Documentation

| Document | Contenu |
| --- | --- |
| `docs/rapport-livraison.md` | Ce qui est livré, vérifications, limites connues |
| `docs/a-brancher.md` | Ce que la Ville doit fournir pour la mise en service, et où le saisir |
| `docs/adr/` | Décisions d'architecture numérotées (DMZ, façade, AD, outillage, droits, conservation, valorisation, PayFiP, charte graphique, sauvegarde) |
| `docs/decisions.md` | Décisions de détail (D-001 et suivantes) |
| `docs/api/` | Schémas OpenAPI de l'API de gestion et de l'API du portail |
| `docs/recette/` | Référentiel d'exigences et matrice de traçabilité |
| `docs/securite/` | Analyses Trivy et nomenclatures logicielles (SBOM) |
| `docs/sauvegarde-restauration.md` | Procédure de sauvegarde et de restauration |
| `DESIGN.md` | Charte graphique |

## Avant la mise en service

Les intégrations ont été éprouvées sur des **simulateurs**, jamais sur les services réels de la Ville ou de la DGFiP.
Avant la mise en service, la Ville doit fournir ou trancher les points suivants (détail dans `docs/a-brancher.md`) :

- **Active Directory et certificats** : groupes, compte de service, autorité de certification, noms et certificats
  des applications.
- **Ciril GROUP** : formats d'export des titres et d'import des encaissements, à valider avec l'éditeur.
- **PayFiP** : convention avec la DGFiP, mode Titres ou Régie, numéro de client.
- **Valorisation** : fondement juridique, signataire des attestations, délibérations, coût horaire chargé du
  personnel.
- **Comptable public** : modalités des cautions et remboursement des trop-perçus.
- **DRH** : format de l'export paie et protocole de temps de travail.
- **Messagerie, SMS, DocuSeal** : comptes et jetons de production.
- **Archiviste et DPO** : durées de conservation.

---

Propriété de la Ville de Châtillon — usage interne. Licence : non libre (UNLICENSED).
