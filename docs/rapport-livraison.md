# Rapport de livraison — Plateforme de gestion des équipements sportifs et associatifs

- Ville de Châtillon — Direction des systèmes d'information
- Livraison : lots 0 à 7, dans l'ordre du §9.2.
- Dates : du 31 octobre au 1er novembre 2026.
- Dépôt Git local : 8 commits de lot. Le dernier est « Lot 7 — paiement en ligne PayFiP » ; le contrôle final fait l'objet d'un commit séparé (« Contrôle final »).
- Ce rapport clôt la réalisation. Les points qui demandent une information ou une action de la Ville figurent dans `docs/a-brancher.md`. Les choix faits en l'absence d'information figurent dans `docs/decisions.md` (D-001 à D-074) et dans les ADR 0001 à 0008.

## 1. Ce qui est livré

| Lot | Contenu | Exigences |
| --- | --- | --- |
| 0 — Socle | **Architecture** : DMZ (façade sans données métier, ADR 0001-0002) → flux mTLS unique → API Django sur le LAN.<br>**Accès** : authentification Active Directory, double authentification, droits rôle × périmètre (ADR 0003, 0005), journal d'audit chaîné et ancré.<br>**Socle technique** : paramètres, fichiers sous antivirus, pile Docker LAN et DMZ, CI. | 13 |
| 1 — Réservations | **Référentiel** : sites, bâtiments, espaces hiérarchisés et partageables, horaires, fermetures, saisons et calendrier scolaire.<br>**Réservations** : récurrences, conflits garantis par la base (RG-01), options, campagne annuelle et arbitrage.<br>**Écrans** : planning à six vues, dossiers, usagers et pièces. | 30 |
| 2 — Portail et échanges | **Portail public RGAA** : catalogue, disponibilités, inscription, demande en quatre étapes, suivi, messagerie.<br>**Documents** : modèles .docx versionnés, PDF/A (Gotenberg), signature DocuSeal ou manuscrite constatée.<br>**Échanges** : courriel et SMS, RGPD (ADR 0006). | 31 |
| 3 — Finances et Ciril | **Tarification** : grilles votées, réductions et gratuités sur tarif de référence (RG-05), simulateur public.<br>**Pièces** : devis, factures, acomptes, avoirs immuables (RG-13).<br>**Ciril** : export des titres et import des encaissements (CSV, XLSX, XML).<br>**Cautions** : état des lieux, retenues, double validation. | 23 |
| 4 — Personnel et mobile | **Planning** : besoins de gardiennage nés des séances, vacations, trames, absences et remplacements.<br>**Contrôles et sorties** : règles de temps de travail, compteurs et export paie, plannings PDF et iCal.<br>**Application mobile** : PWA hors ligne, chiffrée, avec pointage, états des lieux, photos et signature. | 22 |
| 5 — Matériel | Catalogue, stocks par site, prêts séance par séance facturés, retours et manquants, contrôles périodiques, pannes. | 5 |
| 6 — Pilotage | **Valorisation des avantages en nature** (ADR 0007) : attestation signée par l'élu, annexe du compte administratif.<br>**Statistiques** : occupation, répartition, recettes, personnel.<br>**Tableaux de bord** : « à traiter » et direction.<br>**Éditions** : planning imprimé, feuille de salle, envoi programmé. | 23 |
| 7 — PayFiP | Paiement en ligne Titres et Rôles ou Régie (ADR 0008) : tentative tracée, notification signée et revérifiée, rapprochement horaire, contrôles et trop-perçus. | 2 |

- **Exigences** : 149, dont 125 obligatoires (M), 22 souhaitables (S) et 2 complémentaires (C).
- **Couverture** : toutes sont reliées à leur code et à au moins un test automatisé (`docs/recette/matrice.csv`, régénérée par `make matrice`).
- **Référentiel** : le cahier des charges étant absent du dépôt, le référentiel `docs/recette/exigences.csv` a été reconstitué (D-001) à partir de CLAUDE.md, des skills et des exigences citées.

**Écrans**
- Back-office des agents : 64 écrans, dont le tableau de bord, le planning, les finances, le personnel, le matériel, le pilotage, la valorisation et l'administration.
- Portail public : pages publiques, espace usager, factures et paiement en ligne, attestations.
- Application mobile des gardiens, hors ligne.

**Documents** : 11 modèles livrés (DOC-02), les éditions imprimées (IMP) et l'attestation de valorisation.

## 2. Vérifications du contrôle final

| Vérification | Résultat |
| --- | --- |
| Tests de l'API (`pytest`) | 567 réussis, 1 ignoré : le test d'intégration à l'annuaire de recette, qui a besoin des secrets de développement sur le poste |
| Façade DMZ | 32 réussis |
| Back-office (Vitest) | 41 réussis |
| Portail (Vitest) | 9 réussis |
| Application mobile (Vitest) | 22 réussis |
| Parcours de bout en bout (Playwright, pile LAN + DMZ complète, axe-core WCAG 2.2 AA) | 26 réussis, aucune violation d'accessibilité |
| Scénarios transverses du §9.3 (`backend/tests/test_scenarios_transverses.py`) | 5 sur 5 : campagne annuelle jusqu'à la signature ; location par un particulier non résident (devis, PayFiP, caution, état des lieux, retenue partielle) ; fermeture imprévue ; absence d'un gardien ; clôture d'exercice |
| Analyse statique | ruff, mypy, oxlint, tsc : aucun écart. `makemigrations --check` : aucune migration manquante |
| Migrations | toutes réversibles (aller, retour à zéro, aller) |
| Motifs interdits (TODO, FIXME, NotImplementedError, fonctions vides, « en construction ») | 0 (`scripts/verifier_motifs.py`, bloquant en CI) |
| Matrice de traçabilité | 149 / 149 exigences couvertes |
| Trivy (5 images et dépôt) | conforme : aucune vulnérabilité critique ou haute corrigeable (§ 2.1) |

### 2.1 Analyse de vulnérabilités (Trivy 0.76.1)

La première analyse a relevé trois choses, toutes corrigées (D-074) :
- **libbrotli1 (CVE critique)** : correctif publié par Debian mais pas encore repris dans l'image nginx amont.
- **pip (CVE hautes)** : il embarque des versions vulnérables de msgpack, urllib3 et setuptools.
- **python-ldap (clés de test)** : ses jeux d'essai contiennent des clés de test.

Les images appliquent maintenant les correctifs de sécurité Debian à leur construction. Les images Python d'exécution ne contiennent plus ni pip, ni setuptools, ni les jeux d'essai.

Le conteneur d'outillage de développement s'exécute désormais sans les droits root.

**Résultat après correction : les cinq images (api, facade, backoffice, portail, mobile) et le dépôt sont conformes, sans vulnérabilité critique ni haute corrigeable, sans secret ni défaut de configuration haut. Les rapports sont dans `docs/securite/trivy-*.txt`.**

## 3. Revues indépendantes

Chaque lot a été relu par deux sous-agents qui n'ont pas participé à son écriture : `revue-securite` et `revue-metier`. Tous les points bloquants et majeurs ont été corrigés et testés. Les choix qui en découlent sont tracés.

| Lot | Bloquants corrigés | Majeurs corrigés | Décisions |
| --- | --- | --- | --- |
| 0 | 0 | 16 | D-015 à D-020, ADR 0005 |
| 1 | 4 | 20 | D-021 à D-028 |
| 2 | 3 | 18 | D-034 à D-038, ADR 0006 |
| 3 | 4 | 20 | D-039 à D-045 |
| 4 | 3 | 20 | D-046 à D-054 |
| 5 | 2 | 12 | D-055 à D-060 |
| 6 | 4 | 19 | D-061 à D-068, ADR 0007 |
| 7 | 4 | 10 | D-069 à D-073, ADR 0008 |

Exemples de points relevés et corrigés au fil des revues :
- conflit de réservation garanti par une contrainte d'exclusion en base ;
- immuabilité des pièces comptables, des cautions, du journal et des valorisations figées, garantie par des déclencheurs ;
- invitation à la signature dans l'ordre des signataires ;
- clôture d'exercice qui recalcule les bénéficiaires ;
- notification PayFiP signée et revérifiée ;
- aucune tentative de paiement close sans résultat de la DGFiP.

## 4. Intégrations et simulateurs

Chaque intégration est codée pour de vrai et dispose d'un simulateur ou d'un service de recette fidèle. Aucun service réel de la Ville n'a été joint.

| Intégration | Implémentation | Recette |
| --- | --- | --- |
| Active Directory (SEC-02) | LDAPS, groupes vers rôles et périmètres | annuaire OpenLDAP de recette (`deploy/dev/annuaire`) |
| Messagerie (COM-01) | SMTP, file d'envoi avec nouvelles tentatives | Mailpit |
| SMS (COM-05) | adaptateur HTTP | simulateur |
| Signature électronique (SIG) | API DocuSeal 3.x, webhook vérifié puis relu | simulateur DocuSeal, plus image DocuSeal en DMZ |
| PDF/A (DOC-04) | Gotenberg | conteneur Gotenberg |
| Antivirus (SEC-07) | ClamAV en DMZ et sur le LAN, quarantaine | conteneurs ClamAV, test EICAR |
| CIVIL Finances Publiques (TAR-06, TAR-13) | export des titres et import de l'état des encaissements, colonnes paramétrables | fichiers CSV, XLSX et XML |
| PayFiP (TAR-07, POR-07) | service SOAP PaiementSecuriseService, modes Titres et Régie | simulateur PayFiP (paiement accepté, refusé ou abandonné, notification) |
| Calendrier scolaire et jours fériés (ADM-01) | open data de l'Éducation nationale et API des jours fériés | fichier zone C 2026-2027 |
| Agendas (IMP-05) | flux iCal à jeton révocable | — |

## 5. Pile de démonstration et de recette

```
make secrets && make certs        # secrets et certificats de recette (jamais versionnés)
docker compose -f deploy/lan/compose.yaml -f deploy/lan/compose.dev.yaml up -d --build
docker compose -f deploy/dmz/compose.yaml -f deploy/dmz/compose.dev.yaml up -d --build
docker compose -f deploy/lan/compose.yaml -f deploy/lan/compose.dev.yaml exec api python manage.py charger_demo
make test lint e2e a11y           # contrôles
```

**Jeu de démonstration** : les données d'exemple de l'application CityResa, pour comparer les deux applications
avec les mêmes données (`backend/apps/noyau/demo/cityresa.json`, extrait par `outils/cityresa/extraire.mjs`) :
- 13 sites et 16 espaces de la ville, avec leurs horaires, capacités, règlements et cautions ;
- 46 usagers, dont les 41 associations du guide des sports, aux contacts fictifs (aucune personne réelle) ;
- 47 réservations à tous les statuts, récurrences comprises, et la saison 2026-2027 ;
- tarifs par espace (gratuités en réduction de 100 %), devis, factures et caution ;
- 8 gardiens avec trames, vacations, besoins et une absence ;
- matériel et prêts de CityResa, un retour avec manquants et une panne ;
- exercice de valorisation 2026 calculé, avec subventions en numéraire ;
- envoi programmé d'un planning.

**Comptes de recette** : annuaire OpenLDAP.
- `admin.recette`, `gest.ville`, `gest.complexe`, `accueil.recette`, `planif.recette`, `finances.recette`, `regie.recette`, `direction.recette`, `elu.recette`, `materiel.recette`, `gardien01` à `gardien08`.
- Leurs mots de passe sont générés par `make secrets` dans `deploy/dev/secrets`, non versionné.

**Adresses** :
- back-office : https://localhost ;
- portail : https://equipements.chatillon.test:9443 ;
- mobile : https://gardiens.chatillon.local ;
- Mailpit et simulateurs : http://127.0.0.1:58025 et :53010.

## 6. Ce que la Ville doit fournir ou trancher avant la mise en service

Le détail, avec l'endroit où saisir chaque élément et la vérification à faire, est dans `docs/a-brancher.md`. Points principaux :

1. **Référentiel d'exigences** (D-001) : confronter `docs/recette/exigences.csv` au cahier des charges et signaler les écarts.
2. **Active Directory** : groupes, compte de service, autorité de certification. **Certificats et noms** : portail, back-office, mobile, flux mTLS.
3. **Ciril GROUP** : format d'import des titres et de l'état des encaissements, à valider avec l'éditeur (paramètres `ciril.*`, D-039). Comment l'état distingue les paiements PayFiP.
4. **PayFiP** (ADR 0008) :
   - à ouvrir après la convention DGFiP ;
   - mode Titres ou Régie, numéro de client, saisie X puis W ;
   - adresses IP des notifications, proxy de sortie ;
   - points du guide à confirmer : `resultrans` V, format de `refdet`, montant minimal.
5. **Valorisation** (ADR 0007) :
   - fondement juridique et libellé du seuil de 153 000 € ;
   - signataire des attestations ;
   - délibérations fixant les méthodes ;
   - coût horaire chargé du personnel.
6. **Comptable public** : modalités de dépôt et de restitution des cautions, remboursement des trop-perçus.
7. **DRH** : format d'import de l'export paie (D-048), protocole de temps de travail (D-051).
8. **Messagerie, SMS, DocuSeal** : comptes, adresses et jetons de production.
9. **Archiviste et DPO** : durées de conservation (ADR 0006).

## 7. Limites connues et risques résiduels

- **Contexte d'exécution** :
  - les intégrations ont été éprouvées sur leurs simulateurs, pas sur les services réels de la Ville ni de la DGFiP (consigne : aucun service réel joint) ;
  - les essais de raccordement réels sont à mener en recette Ville (`docs/a-brancher.md`).
- **Test ignoré** : le test d'intégration à l'annuaire tourne contre l'OpenLDAP de recette quand les secrets de développement sont présents. Il a été ignoré dans la passe finale, faute de ces secrets sur le poste d'exécution des tests.
- **Mises à jour** :
  - les images appliquent les correctifs Debian à leur construction (D-074) ;
  - chaque nouvelle livraison doit être reconstruite et réanalysée (`make trivy`), d'autant que l'analyse dépend de la fraîcheur de la base de vulnérabilités ;
  - les dépendances sont épinglées (lockfiles) et les images par empreinte.
- **Démonstration** : l'exercice de valorisation est en cours, donc il n'a pas d'attestation déposée. Le parcours complet clôture → signature → dépôt est démontré par les tests automatisés (scénario transverse 5).
- **Volume** : il reste modeste (30 à 50 espaces, CLAUDE.md). Les statistiques et la valorisation sont calculées à la demande, sans entrepôt ni précalcul.

## 8. Documents de référence

- `docs/avancement.md` : avancement et journal par lot, critères de sortie.
- `docs/decisions.md` : 74 décisions tracées.
- `docs/adr/` : 8 décisions d'architecture.
- `docs/a-brancher.md` : raccordements et paramètres à fournir.
- `docs/recette/exigences.csv` et `docs/recette/matrice.csv` : exigences et traçabilité.
- `docs/api/openapi-*.yaml` : contrats d'API générés.
- `docs/securite/` : rapports Trivy et nomenclatures logicielles (SBOM).
