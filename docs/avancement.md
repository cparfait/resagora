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

## Lot 3 — Finances et Ciril

Exigences : TAR-01 à TAR-13, CAU-01 à CAU-07, RG-04, RG-05, RG-08, RG-11, RG-13.

| Étape | Contenu | Exigences | État |
| --- | --- | --- | --- |
| 3.1 | Grilles tarifaires votées (délibération), tarifs de référence jamais nuls, majorations, prestations, réductions et gratuités fondées (100 % sur tarif conservé) | TAR-01 à TAR-03, RG-05 | fait |
| 3.2 | Devis (remplacement, validité, expiration quotidienne, acceptation en ligne), acomptes, factures depuis les lignes du devis, avoirs ligne à ligne, frais d'annulation au barème | TAR-04, TAR-05, TAR-07 à TAR-09, RG-04, RG-08 | fait |
| 3.3 | Titres vers Ciril (CSV, XLSX, XML paramétrables, lots numérotés, annulation d'un lot rejeté, report du numéro de titre) et import de l'état des encaissements (rapprochement, doublons signalés, ClamAV) | TAR-06, TAR-13 | fait |
| 3.4 | Règlement par virement : coordonnées figées à l'émission, IBAN contrôlé, retards | TAR-10, TAR-12 | fait |
| 3.5 | Cautions : attendue, reçue, restituable après l'état des lieux de sortie, retenue motivée avec photos (EXIF retiré), validation par un second agent au-delà du seuil, solde restitué, encaissement, alertes | CAU-01 à CAU-07, RG-11 | fait |
| 3.6 | Immuabilité en base (déclencheurs) des pièces émises, lignes, journaux de caution ; séparation des tâches dans les rôles | RG-13, ADR 0005 | fait |
| 3.7 | Back-office (tarifs, pièces, titres, encaissements, cautions), portail (simulation, factures, devis, cautions), démonstration, e2e + axe, revues (4 bloquants et 20 majeurs corrigés, D-041 à D-045) | TAR-11 | fait |

Critère de sortie (reconstitué) :
- [x] une location est simulée sur le portail, devisée, acceptée en ligne, facturée depuis le devis avec déduction de l'acompte ;
- [x] une annulation tardive produit un avoir et les frais du barème ; un avoir ne crédite jamais deux fois la même ligne ;
- [x] un lot de titres s'exporte au format paramétré, un lot rejeté s'annule et se réexporte, l'état des encaissements solde les factures ;
- [x] une caution n'est restituée qu'après l'état des lieux de sortie ; une retenue au-delà du seuil exige un second agent ;
- [x] pièces émises et journaux de caution immuables en base ; montants en centimes ;
- [x] revues sécurité et métier traitées.

**Lot 3 terminé le 2026-10-31.**

## Lot 4 — Personnel et application mobile hors ligne

Exigences : PER-01 à PER-09, MOB-01 à MOB-08, IMP-02, IMP-05, SEC-10.

| Étape | Contenu | Exigences | État |
| --- | --- | --- | --- |
| 4.1 | Agents, habilitations datées (SSIAP exigé pour garder un site), rattachement au compte de l'annuaire à la première connexion | PER-01 | fait |
| 4.2 | Besoins nés des réservations des espaces gardiennés, fusionnés par site, recalculés à chaque changement de séance (vacations « à revoir », agent prévenu) | PER-02, RG-09 | fait |
| 4.3 | Vacations, trames hebdomadaires appliquées sur la saison, candidats et remplaçants, moteur de règles (durée, repos, hebdomadaire, nuit), forçage motivé et tracé, absences | PER-03 à PER-06 | fait |
| 4.4 | Compteurs (planifiées, réalisées, supplémentaires, nuit, dimanches et fériés, astreintes) et export paie ; iCal personnel à jeton révocable ; planning PDF par agent ou site ; iCal du planning d'un espace | PER-07, PER-08, IMP-02, IMP-05 | fait |
| 4.5 | API mobile : options A (VPN) et B (DMZ, certificat d'appareil, TOTP), paquet minimal, saisies idempotentes, conflits conservés et signalés, photos, incidents, état des lieux vers les cautions | MOB-03 à MOB-07, PER-09, SEC-10 | fait |
| 4.6 | PWA hors ligne : service worker (coquille et ressources en cache dès l'installation), coffre IndexedDB chiffré (AES-GCM, PBKDF2), file d'envoi, déverrouillage sans réseau, reconnexion sans perte (rechiffrement), fraîcheur et purge à 7 jours | MOB-01, MOB-02, MOB-05, MOB-07, MOB-08 | fait |
| 4.7 | Back-office personnel (planning, agents, habilitations, trames, absences, compteurs, incidents, saisies, appareils), démonstration (8 gardiens), e2e hors ligne + axe | — | fait |
| 4.8 | Revues sécurité (8 majeurs) et métier (3 bloquants, 12 majeurs) corrigées : besoins rattachés et séances réalisées (RG-09), trames et horaires contrôlés, compteurs au prorata, saisies bornées, état des lieux réservé à l'agent en poste, appareils à autoriser, refus neutres, code de déverrouillage local, photos analysées et sans métadonnées, certificat d'appareil au format Traefik (D-047, D-051 à D-054) | — | fait |

Critère de sortie (reconstitué) :
- [x] une réservation d'espace gardienné crée le besoin ; une séance annulée met la vacation « à revoir » et prévient le gardien ;
- [x] une trame appliquée sur la saison n'affecte que des agents habilités, présents et dans les règles ; le forçage est motivé et tracé ;
- [x] une absence libère les vacations non pointées et un remplaçant conforme est proposé ;
- [x] compteurs du mois et export paie justes (prorata, nuit, dimanches et fériés, changement d'heure) ; iCal personnel révocable ; planning PDF ;
- [x] un gardien se connecte, choisit son code, pointe en mode avion, rouvre l'application sans réseau et synchronise : la saisie est reçue une fois ;
- [x] état des lieux de sortie avec photo et signature hors ligne, qui alimente la caution ; conflits conservés et signalés ;
- [x] paquet sans montant ni pièce ni autre site ; données locales chiffrées ; planning effacé après 7 jours sans synchronisation ;
- [x] e2e hors ligne et axe sans violation ; revues sécurité et métier traitées.

**Lot 4 terminé le 2026-10-31.**

## Journal

- 2026-10-31 — Démarrage. Cahier des charges absent (D-001), référentiel reconstitué.
- 2026-10-31 — Revues lot 0 : passage à python-ldap (ldap3 non maintenu), rôle PostgreSQL applicatif, HMAC + ancrage + purge du journal, verrouillage et réactivation TOTP, appariement objectGUID, séparation des tâches, routes DocuSeal restreintes. 109 tests API, 26 façade, 21 front, 4 e2e.
- 2026-10-31 — Lot 0 : 61+ tests API, 19 tests façade, 21 tests front, 4 e2e (axe sans violation) ; pile LAN + DMZ en conteneurs, chaîne mTLS vérifiée.
- 2026-10-31 — Lot 1 : 173 tests API, 28 tests front, 3 e2e lot 1 (axe sans violation) ; jeu de démonstration chargé (3 sites, 40 espaces, 63 créneaux annuels, locations) ; matrice lots 0–1 complète (49 exigences).
- 2026-10-31 — Revues lot 1 : campagnes « tous sites » réservées à la ville entière, conditions RG-06 refusées par défaut avec constat manuel tracé, transitions de clôture et d'attribution contrôlées, grammaire RRULE bornée, fermetures et saisons closes contrôlées par l'API, historique des séances conservé, verrous recalculés quand la hiérarchie change, paramètres validés par schéma. 207 tests API (hors intégration), 28 tests front, 7 e2e.
- 2026-10-31 — Revues lot 2 : élu invité à son tour, scan de l'usager contrôlé par un agent, avenant exigé quand le créneau change, modèles fusionnés en bac à sable strict, verrous TOTP et mot de passe, invitations sans énumération ni reprise de compte, signalements neutres sur le portail, archives RGPD (ADR 0006), garde-fous de recette, ClamAV et DocuSeal sans root.
- 2026-10-31 — Lot 3 et revues : facturation depuis le devis, avoirs ligne à ligne, barème cohérent, lots Ciril annulables, cautions restituables après état des lieux, immuabilité renforcée en base, IBAN réservé à l'ordonnateur et contrôlé, neutralisation des formules dans les exports.
- 2026-10-31 — Lot 4 : personnel (besoins, trames, règles, absences, compteurs, iCal, planning PDF), API mobile options A et B, PWA hors ligne chiffrée ; 14 tests mobile, parcours e2e en mode avion.
- 2026-10-31 — Revues lot 4 : moteur de besoins (jour de rattachement, séances réalisées, vacations existantes), contrôles des trames et des horaires, compteurs au prorata et astreintes à part, saisies terrain bornées, cautions bloquées par des dégâts intermédiaires, appareils à autoriser, connexion sans oracle, code de déverrouillage local (PBKDF2 600 000), photos mobiles en quarantaine DMZ (option B). Types Node épinglés pour le typage des parcours e2e.
