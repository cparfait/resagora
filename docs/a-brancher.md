# À brancher ou à valider par la Ville

Tout ce qui dépend de la Ville ou d'un tiers se règle **par configuration ou par secret**, sans
modifier le code. Pour chaque point : paramètre exact, emplacement, test de raccordement.

- Paramètres non secrets : `deploy/lan/parametres.env`, `deploy/dmz/parametres.env`.
- Secrets : un fichier par secret dans `deploy/lan/secrets/` et `deploy/dmz/secrets/` (droits 0600,
  jamais dans Git). En recette, `make secrets certs` en génère des valeurs de test.

## 1. Active Directory (SEC-02, ADM-06)

| Paramètre | Où | Valeur à fournir |
| --- | --- | --- |
| `LDAP_URI` | parametres.env (LAN) | `ldaps://dc1.ville.local:636` (ou `ldap://…:389` avec `LDAP_STARTTLS=1`) |
| `LDAP_FICHIER_AC` → secret `ldap_ac.pem` | secrets LAN | Certificat de l'AC qui signe les contrôleurs de domaine (PEM) |
| `LDAP_COMPTE_SERVICE_DN` | parametres.env | DN du compte de service en lecture seule, ex. `CN=svc-equipements,OU=Services,DC=ville,DC=local` |
| `ldap_mot_de_passe` | secret LAN | Mot de passe de ce compte de service |
| `LDAP_BASE_UTILISATEURS` | parametres.env | ex. `OU=Agents,DC=ville,DC=local` |
| `LDAP_BASE_GROUPES` | parametres.env | ex. `OU=Groupes,DC=ville,DC=local` |
| `LDAP_FILTRE_UTILISATEUR` | parametres.env | défaut `(&(objectClass=user)(sAMAccountName={identifiant}))` |
| `LDAP_ATTRIBUT_IDENTIFIANT` | parametres.env | défaut `sAMAccountName` |
| `LDAP_ATTRIBUT_GUID` | parametres.env | défaut `objectGUID` (identifiant immuable de l'agent) |
| `LDAP_MODE_GROUPES` | parametres.env | `ad_imbriques` (défaut, groupes imbriqués), `memberof` ou `recherche` |
| Groupes → rôles | écran « Groupes de l'annuaire » ou `python manage.py amorcer_groupes_ad fichier.json` | Liste des groupes AD (DN) et rôle × périmètre associé |

**Tester** : `docker compose -f deploy/lan/compose.yaml exec api python manage.py tester_annuaire --identifiant <agent>`
affiche la liaison du compte de service, l'entrée de l'agent et ses groupes avec le rôle obtenu.

**Premier administrateur** : créer le groupe AD des administrateurs, puis
`… exec -T api python manage.py amorcer_groupes_ad - < groupes.json` avec au minimum
`[{"dn": "CN=GG-Equipements-Admins,…", "role": "administrateur", "perimetre": "Ville entière"}]`.

## 2. Certificats et noms de domaine (SEC-01)

| Élément | Secret / paramètre | À fournir |
| --- | --- | --- |
| Certificat public du portail | `dmz_tls.crt`, `dmz_tls.key` (DMZ) | Certificat du nom public (ex. `reservations.ville-chatillon.fr`) et de `signature.…` |
| Règles de routage DMZ | `deploy/dmz/traefik/dynamique.yml` (`Host(...)`) | Noms définitifs du portail et de la signature |
| Origine du portail | `ORIGINE_PORTAIL` (DMZ) | `https://<nom public du portail>` |
| Certificat interne du back-office | `lan_tls.crt`, `lan_tls.key` (LAN) | Certificat de l'AC interne pour `equipements.<domaine interne>` et `gardiens.<domaine interne>` |
| mTLS façade → API | `ac_facade.crt` (LAN), `facade_client.crt/.key` (DMZ), `api_portail.crt/.key` (LAN), `ac_interne.crt` (DMZ) | AC privée dédiée à la façade (à émettre par la DSI), certificat client de la façade, certificat serveur d'`api-portail` |
| Adresse de l'API vue de la DMZ | `API_URL` (DMZ) | `https://<IP ou nom LAN de l'hôte API>:8443` ; ouvrir **uniquement** ce flux au pare-feu |
| `IP_LIAISON_DMZ` | environnement du compose LAN | Adresse d'écoute du port 8443 sur l'hôte LAN |
| `CSRF_TRUSTED_ORIGINS`, `DJANGO_ALLOWED_HOSTS` | parametres.env (LAN) | Noms internes définitifs |

**Tester** : depuis l'hôte DMZ, `curl --cert facade_client.crt --key facade_client.key --cacert ac_interne.crt https://<API_URL>/sante`
répond `{"etat": "ok"}` ; sans `--cert`, la poignée de main TLS échoue.

## 3. Base de données, journaux et sauvegardes

| Paramètre | Où | À fournir |
| --- | --- | --- |
| `postgres_password` | secret LAN | Mot de passe du rôle propriétaire `equipements` (migrations et maintenance seulement) |
| `postgres_app_password` | secret LAN | Mot de passe du rôle applicatif `equipements_app` (créé par `deploy/lan/postgres/initdb/01-roles.sh`) |
| `audit_cle_hmac` | secret LAN | Clé aléatoire (≥ 32 caractères) de la chaîne du journal d'audit ; à conserver avec les sauvegardes |
| Journaux techniques | exploitation | Serveur syslog de la Ville : remplacer le pilote `json-file` (`x-journaux` des compose) par `syslog` ou un agent de collecte ; conservation ≥ 6 mois (SEC-08). Les lignes `ANCRAGE_JOURNAL_AUDIT` y sont l'ancrage externe du journal. |
| Purge du journal d'audit | exploitation | Tâche planifiée annuelle avec le rôle propriétaire : `docker compose run --rm migrations python manage.py purger_journal_audit` (archive JSON Lines + empreinte, conservation `AUDIT_CONSERVATION_JOURS`, 400 jours par défaut, 183 minimum) |
| Archivage des WAL, sauvegarde | exploitation | Cible de sauvegarde, RPO 1 h (skill `docker-deploiement`) |

**Tester** : `docker compose -f deploy/lan/compose.yaml run --rm migrations python manage.py accorder_droits equipements_app`
affiche les tables en ajout seul ; `python manage.py verifier_deploiement` doit répondre « Instance prête ».

## 4. Proxys de confiance et réseaux

| Paramètre | Où | À fournir |
| --- | --- | --- |
| `FORWARDED_ALLOW_IPS` (façade, API) | compose DMZ / LAN | Adresse fixe du proxy Traefik de chaque zone (10.231.10.250 et 10.231.20.250 par défaut ; à adapter aux plages de la Ville) |
| Sous-réseaux `dmz_front`, `lan_app` | compose | Plages libres sur les hôtes de la Ville |
| Sortie Internet des mises à jour ClamAV | réseaux `sortie_dmz`, `sortie_lan` | Proxy HTTP de la Ville vers `database.clamav.net` |

## 5. Messagerie (SMTP) — COM-01

Recette : Mailpit (`mailpit:1025`, interface web http://localhost:58025 en développement). Production : serveur SMTP de la Ville.

| Paramètre | Où | À fournir | Comment tester |
| --- | --- | --- | --- |
| `SMTP_HOTE`, `SMTP_PORT` | `deploy/lan/parametres.env` | Relais SMTP interne de la Ville (ex. port 587) | `docker compose … exec api python manage.py sendtestemail adresse@chatillon92.fr` |
| `SMTP_STARTTLS` ou `SMTP_TLS` | idem | `1` selon le relais (STARTTLS sur 587, TLS implicite sur 465) | idem, le message doit arriver |
| `SMTP_UTILISATEUR` + secret `smtp_mot_de_passe` | `parametres.env` + `deploy/lan/secrets/smtp_mot_de_passe` | Compte d'envoi si le relais exige une authentification | idem |
| `COURRIEL_EXPEDITEUR` | `parametres.env` | Adresse d'expéditeur autorisée (SPF/DKIM du domaine de la Ville) | En-tête `From` du message de test |
| `PORTAIL_URL`, `BACKOFFICE_URL` | `parametres.env` | Noms de domaine définitifs (liens insérés dans les messages) | Lien d'une notification de validation |

## 5 bis. Calendrier scolaire et jours fériés — ADM-01

L'API sort vers Internet par le réseau `sortie_lan` (proxy de la Ville) ; à défaut, le calendrier s'importe depuis un fichier (écran Saisons et calendrier → « Importer un fichier du calendrier scolaire », export JSON du jeu national) et les jours fériés sont calculés localement (Pâques, Ascension, Pentecôte).

| Paramètre | Valeur par défaut | Comment tester |
| --- | --- | --- |
| `URL_CALENDRIER_SCOLAIRE` | API data.education.gouv.fr, jeu `fr-en-calendrier-scolaire` (académie de Versailles, zone C) | Back-office → Référentiel → Saisons et calendrier → « Importer vacances et fériés » sur la saison : les vacances apparaissent |
| `URL_JOURS_FERIES` | `https://calendrier.api.gouv.fr/jours-feries/metropole/{annee}.json` | Même import : les jours fériés apparaissent (sinon calcul local, signalé dans le journal) |
| `HTTPS_PROXY` | absent | Proxy de sortie de la Ville si l'API ne joint pas directement Internet |

## 6. Signature électronique (DocuSeal) — SIG-01 à SIG-05

Recette : simulateur `simulateurs` (deploy/dev, http://localhost:53010) qui reproduit l'API et les webhooks de DocuSeal 3.x.
Production : conteneur `docuseal` de la DMZ (image épinglée), pages de signature publiées seules (D-019).

| Paramètre | Où | À fournir | Comment tester |
| --- | --- | --- | --- |
| `DOCUSEAL_URL` | `deploy/lan/parametres.env` | Adresse de DocuSeal vue du LAN (par le proxy, 443) | Back-office → dossier → document → « Signature électronique » : le circuit passe à « en attente de signature » |
| `DOCUSEAL_URL_PUBLIQUE` | idem | Nom public des pages de signature (ex. `https://signature.chatillon.fr`) | Le lien « Signer en ligne » du portail ouvre cette adresse |
| Secret `docuseal_api_jeton` | `deploy/lan/secrets/` | Jeton d'API créé dans DocuSeal (Paramètres → API) par l'administrateur, compte de service dédié | Même test ; un jeton faux donne « Le service de signature a refusé la demande » |
| Webhook DocuSeal | Interface d'administration de DocuSeal (LAN uniquement) | URL `https://<portail>/api/portail/webhooks/docuseal`, en-tête `X-Docuseal-Secret` = secret `docuseal_webhook_secret` (DMZ), événements `form.*` et `submission.*` | Signer un document : il passe « Signé électroniquement » dans la minute (sinon la synchronisation planifiée le rattrape en 15 min) |
| `DOCUSEAL_HOTE` | `deploy/dmz` (variable d'environnement) | Nom public de DocuSeal | Page `/s/<jeton>` servie par le proxy DMZ |
| `SIGNATURE_MODE` | `deploy/lan/parametres.env` | `docuseal` (défaut) ou `manuel` si DocuSeal n'est pas encore disponible | Le bouton « Signature papier » reste toujours disponible |
| Signataire de la Ville | Paramètres `signature.elu_nom`, `signature.elu_qualite`, `signature.elu_courriel` | Élu ou agent délégataire, adresse de signature | Le second signataire reçoit le lien après l'usager |

## 7. Conversion PDF (Gotenberg) et antivirus (ClamAV) — DOC-04, SEC-07

| Paramètre | Où | À fournir | Comment tester |
| --- | --- | --- | --- |
| `GOTENBERG_URL` | `deploy/lan/parametres.env` | Aucun (conteneur interne `gotenberg`) | Générer une convention : un PDF/A-2b est rattaché au dossier |
| `CLAMAV_HOTE`, `CLAMAV_PORT` | LAN et DMZ | Aucun (conteneurs internes) ; sortie vers `database.clamav.net` par le proxy de la Ville pour les mises à jour | Déposer le fichier de test EICAR sur le portail : refus « contrôle antivirus » et ligne « Fichier infecté rejeté » dans le journal de la façade |

## 8. SMS — COM-05

| Paramètre | Où | À fournir | Comment tester |
| --- | --- | --- | --- |
| `SMS_ADAPTATEUR` | `deploy/lan/parametres.env` | `desactive` (défaut) ou `http` | Une préférence « SMS » cochée sur le portail produit une ligne SMS dans le journal des envois |
| `SMS_URL`, secret `sms_jeton` | idem + `deploy/lan/secrets/sms_jeton` | Adresse de l'API de l'opérateur retenu et jeton | Envoi groupé avec SMS : le SMS apparaît chez l'opérateur (en recette : http://localhost:53010/sms) |
| `SMS_EXPEDITEUR`, `SMS_CHAMPS` | idem | Nom d'expéditeur (11 caractères) ; correspondance des champs si l'opérateur n'utilise pas `destinataire`, `expediteur`, `texte`, `reference` | — |

## 9. Portail public — POR-01 à POR-10

| Paramètre | Où | À fournir | Comment tester |
| --- | --- | --- | --- |
| `ORIGINE_PORTAIL` | `deploy/dmz/parametres.env` | Adresse publique exacte du portail (contrôle de l'en-tête Origin) | Une connexion depuis une autre origine est refusée (403) |
| `PORTAIL_URL` | `deploy/lan/parametres.env` | Même adresse (liens des courriels) | Lien de confirmation reçu par courriel |
| Déclaration d'accessibilité | Paramètres `accessibilite.*` | État de conformité, date et organisme d'audit, contenus non accessibles, contact | Page « Accessibilité » du portail |
| Service à prévenir | Paramètre `portail.service_courriel` | Boîte du service des équipements (comptes à valider, messages des usagers) | Inscription d'un compte de test : courriel « Nouveau compte du portail à valider » |
| `FACTEUR_DEBIT`, `DEBIT_*` | Jamais en production | Laisser les valeurs par défaut (D-032) | — |

## 10. Ciril, PayFiP, accès mobile — complétés aux lots concernés
