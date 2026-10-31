# Avancement

> Mémoire du projet : relire ce fichier après toute interruption.
> Référentiel des exigences : `docs/recette/exigences.csv` (reconstitué, voir D-001).
> Matrice générée : `docs/recette/matrice.csv` (`make matrice`).
> Commandes utiles sous Windows : `backend/.venv/Scripts/python -m pytest` (tests API, base 127.0.0.1:55432),
> `docker compose -f deploy/dev/compose.yaml --profile outils run --rm outils make preparer lint test`,
> e2e : `cd e2e && PLAYWRIGHT_BROWSERS_PATH=../.playwright npx playwright test`.

## Lot 0 — Socle

Exigences : SEC-01, SEC-02, SEC-03, SEC-05, SEC-06, SEC-08, SEC-09, REF-01, REF-02, ADM-03, ADM-05, ADM-06, RG-14.

| Étape | Contenu | Exigences | État |
| --- | --- | --- | --- |
| 0.1 | Dépôt, docs, Makefile, CI, contrôle des motifs interdits, matrice | — | fait |
| 0.2 | Projet Django (réglages par canal, santé, DRF, OpenAPI, pytest, ruff, mypy) | SEC-05, SEC-09 | fait |
| 0.3 | Référentiel de base (sites, bâtiments, espaces hiérarchiques, familles) | REF-01, REF-02 | fait |
| 0.4 | Habilitations rôle × périmètre, actions, `peut()`, `/api/gestion/moi` | RG-14, ADM-03 | fait |
| 0.5 | Journal d'audit chaîné et immuable, `@audite`, consultation, export, vérification | SEC-08, ADM-05 | fait |
| 0.6 | AD LDAPS (python-ldap, D-004), groupes → rôles, TOTP admin/régie/finances, limitation de débit | SEC-02, SEC-03, SEC-06, ADM-06 | fait |
| 0.7 | Façade DMZ (liste blanche, sessions, CSRF, quarantaine ClamAV, rappels) + canal portail mTLS | SEC-01, SEC-05, SEC-07 | fait |
| 0.8 | Images durcies, compose LAN/DMZ/dev, certificats et secrets de dev, annuaire OpenLDAP | SEC-01, SEC-09 | fait |
| 0.9 | Back-office : connexion AD + TOTP, cadre, référentiel, administration, journal | SEC-02, SEC-03, ADM-03/05/06 | fait |
| 0.10 | Revues sécurité et métier (0 bloquant ; 6 majeurs sécurité et 10 points métier corrigés), e2e Playwright + axe, critère de sortie | — | fait |

Critère de sortie (reconstitué, §9.2 indisponible) :
- [x] pile LAN et DMZ démarrée en conteneurs ;
- [x] agent authentifié par l'annuaire de test (LDAPS) avec rôle issu de son groupe ;
- [x] droits rôle × périmètre testés (autorisé et refusé) côté API et interface ;
- [x] journal d'audit chaîné, immuable et vérifiable ;
- [x] flux façade → API en mTLS seulement (refus sans certificat client vérifié) ;
- [x] revues sécurité et métier traitées (ADR 0005, D-015 à D-020).

**Lot 0 terminé le 2026-10-31.**

## Lot 1 — Réservations

Exigences : REF-03 à REF-08, USR-01 à USR-05, PLA-01 à PLA-12, ADM-01, ADM-02, RG-01, RG-02, RG-03, RG-06, RG-07 (+ COM-01 socle des notifications, utilisé par REF-06, PLA-08, PLA-12).

| Étape | Contenu | Exigences | État |
| --- | --- | --- | --- |
| 1.1 | Paramètres fonctionnels tracés ; saisons, calendrier scolaire zone C (client open data + import) et jours fériés calculés | ADM-01, ADM-02 | fait |
| 1.2 | Horaires d'ouverture, fermetures exceptionnelles, documents d'espace (stockage contrôlé) | REF-03, REF-06, REF-08 | fait |
| 1.3 | Usagers, contacts, rattachements, conventionnement, pièces justificatives et alertes | USR-01 à USR-05 | fait |
| 1.4 | Dossiers, réservations, récurrences RRULE, occurrences, verrous par espaces feuilles + contrainte d'exclusion | PLA-04, PLA-06, REF-05, REF-07, RG-01, RG-02 | fait |
| 1.5 | Cycle de statuts, conditions de confirmation enfichables, options et relance, annulation, présence | PLA-06, PLA-08, PLA-10, PLA-11, RG-06, RG-07 | fait |
| 1.6 | Conflits et alternatives, liste d'attente, priorité municipale, fermeture → impacts | PLA-07, PLA-09, PLA-12, REF-06, RG-03 | fait |
| 1.7 | Campagne annuelle : dépôt, instruction, arbitrage RG-03, commission, attribution en lot | PLA-05, RG-03 | fait |
| 1.8 | Notifications électroniques (socle COM-01) | COM-01 | fait |
| 1.9 | Back-office : usagers, dossiers, planning six vues, glisser-déposer contrôlé, vues enregistrées, campagne, calendrier, paramètres | PLA-01, PLA-02, PLA-03 | fait |
| 1.10 | Jeu de démonstration, e2e du lot (planning six vues, demande → aperçu → validation, fiche usager), revues (4 bloquants et 20 majeurs corrigés, D-021 à D-028), critère de sortie | — | fait |

Critère de sortie (reconstitué) :
- [x] une demande se saisit, s'aperçoit (conflits, horaires, fermetures), se valide et se confirme selon les conditions RG-06 du type ;
- [x] aucun chevauchement possible (contrainte d'exclusion PostgreSQL, validations concurrentes testées), espaces divisibles et partageables ;
- [x] créneaux annuels hors vacances zone C et jours fériés, changement d'heure, modifications « cette séance / les suivantes / toute la série » sans perte d'historique ;
- [x] campagne annuelle : dépôt, instruction, arbitrage RG-03, attribution en lot dans le périmètre de l'agent ;
- [x] planning six vues accessible (axe sans violation), glisser-déposer contrôlé par l'API ;
- [x] droits rôle × périmètre testés (autorisé, refusé, hors périmètre) ; revues sécurité et métier traitées.

**Lot 1 terminé le 2026-10-31.**

## Lot 2 — Portail et échanges

Exigences : POR-01 à POR-06, POR-08 à POR-10, SEC-04, SEC-07, COM-01 à COM-05, DOC-01 à DOC-07, SIG-01 à SIG-05, USR-06, ADM-04, RG-13.

| Étape | Contenu | Exigences | État |
| --- | --- | --- | --- |
| 2.1 | Comptes usagers : inscription, confirmation, validation par la Ville, connexion sans énumération, verrouillage progressif, TOTP, réinitialisation, invitation de contacts, changement d'adresse | POR-01, SEC-04 | fait |
| 2.2 | API portail : compte, structures, contacts, pièces (quarantaine DMZ + ClamAV), disponibilités anonymisées, catalogue, demandes en quatre étapes avec brouillon, suivi, annulation, campagnes, notifications | POR-02 à POR-06, SEC-07 | fait |
| 2.3 | Messagerie par dossier, notifications groupées, journal des envois, préférences, SMS par adaptateur + simulateur, modèles de messages éditables | COM-01 à COM-05, POR-08, ADM-04 | fait |
| 2.4 | Documents : modèles .docx versionnés, catalogue DOC-02, contexte typé, PDF/A-2b par Gotenberg, SHA-256, génération en lot, avenants, téléchargement contrôlé, immuabilité | DOC-01 à DOC-07, RG-13 | fait |
| 2.5 | Signature : client DocuSeal (signataires ordonnés, expiration, relances, annulation, PDF signé + preuve, purge), webhooks via la façade revérifiés, circuit manuel, condition RG-06 « convention » | SIG-01 à SIG-05, POR-10 | fait |
| 2.6 | RGPD : durées de conservation, anonymisation, export des données | USR-06 | fait |
| 2.7 | Back-office : comptes à valider, messagerie, documents et signature, génération en lot, modèles, journal des envois, RGPD | ADM-04, COM-02, DOC-06 | fait |
| 2.8 | Portail public React RGAA 4.1.2 : catalogue, disponibilités, compte, demandes, dossiers, documents, signature, messagerie, déclaration d'accessibilité | POR-01 à POR-10 | fait |
| 2.9 | Déploiement (portail DMZ, Gotenberg, DocuSeal, simulateurs), e2e + axe sur toutes les pages, revues (3 bloquants et 18 majeurs corrigés, D-034 à D-038, ADR 0006), critère de sortie | POR-09 | fait |

Critère de sortie (reconstitué) :
- [x] un usager s'inscrit, confirme son adresse, est validé par la Ville, dépose une demande en quatre étapes et la suit ;
- [x] pièces déposées par la DMZ (quarantaine, ClamAV, type réel), refus EICAR tracé ;
- [x] messagerie par dossier, notifications éditables, journal des envois, SMS vers un numéro vérifié ;
- [x] convention générée en PDF/A-2b, signée dans l'ordre (usager puis élu invité à son tour), PDF signé et preuve rapatriés, purge DocuSeal ;
- [x] documents signés immuables en base (RG-13), avenant exigé quand le créneau change ;
- [x] RGPD : export, anonymisation, archives purgées au terme de leur durée (ADR 0006) ;
- [x] portail sans violation axe sur toutes les pages parcourues, navigation clavier ; accès d'un autre usager refusé partout ;
- [x] revues sécurité et métier traitées.

**Lot 2 terminé le 2026-10-31.**

## Journal

- 2026-10-31 — Démarrage. Cahier des charges absent (D-001), référentiel reconstitué.
- 2026-10-31 — Revues lot 0 : passage à python-ldap (ldap3 non maintenu), rôle PostgreSQL applicatif, HMAC + ancrage + purge du journal, verrouillage et réactivation TOTP, appariement objectGUID, séparation des tâches, routes DocuSeal restreintes. 109 tests API, 26 façade, 21 front, 4 e2e.
- 2026-10-31 — Lot 0 : 61+ tests API, 19 tests façade, 21 tests front, 4 e2e (axe sans violation) ; pile LAN + DMZ en conteneurs, chaîne mTLS vérifiée.
- 2026-10-31 — Lot 1 : 173 tests API, 28 tests front, 3 e2e lot 1 (axe sans violation) ; jeu de démonstration chargé (3 sites, 40 espaces, 63 créneaux annuels, locations) ; matrice lots 0–1 complète (49 exigences).
- 2026-10-31 — Revues lot 1 : campagnes « tous sites » réservées à la ville entière, conditions RG-06 refusées par défaut avec constat manuel tracé, transitions de clôture et d'attribution contrôlées, grammaire RRULE bornée, fermetures et saisons closes contrôlées par l'API, historique des séances conservé, verrous recalculés quand la hiérarchie change, paramètres validés par schéma. 207 tests API (hors intégration), 28 tests front, 7 e2e.
- 2026-10-31 — Revues lot 2 : élu invité à son tour, scan de l'usager contrôlé par un agent, avenant exigé quand le créneau change, modèles fusionnés en bac à sable strict, verrous TOTP et mot de passe, invitations sans énumération ni reprise de compte, signalements neutres sur le portail, archives RGPD (ADR 0006), garde-fous de recette, ClamAV et DocuSeal sans root.
