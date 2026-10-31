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
| `DOCUSEAL_URL` | `deploy/lan/parametres.env` | **Obligatoire** : adresse HTTPS de DocuSeal vue du LAN (par le proxy, 443) ; `verifier_deploiement` refuse une adresse HTTP ou un simulateur | Back-office → dossier → document → « Signature électronique » : le circuit passe à « en attente de signature » |
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
| `CLAMAV_HOTE`, `CLAMAV_PORT` | LAN et DMZ | Aucun (conteneurs internes) ; sortie vers `database.clamav.net` par le proxy de la Ville pour les mises à jour : décommenter `HTTPProxyServer` et `HTTPProxyPort` dans `deploy/clamav/freshclam.conf` | Déposer le fichier de test EICAR sur le portail : refus « contrôle antivirus » et ligne « Fichier infecté rejeté » dans le journal de la façade |

## 8. SMS — COM-05

| Paramètre | Où | À fournir | Comment tester |
| --- | --- | --- | --- |
| `SMS_ADAPTATEUR` | `deploy/lan/parametres.env` | `desactive` (défaut) ou `http` | Une préférence « SMS » cochée sur le portail produit une ligne SMS dans le journal des envois |
| `SMS_URL`, secret `sms_jeton` | idem + `deploy/lan/secrets/sms_jeton` | Adresse **HTTPS** de l'API de l'opérateur retenu et jeton (les contacts confirment leur numéro par un code, D-037) | Envoi groupé avec SMS : le SMS apparaît chez l'opérateur (en recette : http://localhost:53010/sms) |
| `SMS_EXPEDITEUR`, `SMS_CHAMPS` | idem | Nom d'expéditeur (11 caractères) ; correspondance des champs si l'opérateur n'utilise pas `destinataire`, `expediteur`, `texte`, `reference` | — |

## 9. Portail public — POR-01 à POR-10

| Paramètre | Où | À fournir | Comment tester |
| --- | --- | --- | --- |
| `ORIGINE_PORTAIL` | `deploy/dmz/parametres.env` | Adresse publique exacte du portail (contrôle de l'en-tête Origin) | Une connexion depuis une autre origine est refusée (403) |
| `PORTAIL_URL` | `deploy/lan/parametres.env` | Même adresse (liens des courriels) | Lien de confirmation reçu par courriel |
| Déclaration d'accessibilité | Paramètres `accessibilite.*` | État de conformité, date et organisme d'audit, contenus non accessibles, contact | Page « Accessibilité » du portail |
| Service à prévenir | Paramètre `portail.service_courriel` | Boîte du service des équipements (comptes à valider, messages des usagers) | Inscription d'un compte de test : courriel « Nouveau compte du portail à valider » |
| `FACTEUR_DEBIT`, `DEBIT_*` | Jamais en production | Laisser les valeurs par défaut (D-032) | — |
| `ENVIRONNEMENT` | LAN et DMZ | `prod` (valeur par défaut) ; `recette` seulement sur un serveur de recette (D-038) | Avec un seuil modifié, la façade refuse de démarrer et `verifier_deploiement` échoue |

## 10. Finances et CIVIL Finances Publiques (Ciril GROUP) — TAR-01 à TAR-13

Aucune connexion directe à Ciril : la plateforme produit des fichiers de titres et relit l'état des encaissements,
dans des formats entièrement paramétrables (écran « Paramètres », groupe Finances). Le format définitif est à
convenir avec l'éditeur et le service financier.

| Paramètre | Où | À fournir | Comment tester |
| --- | --- | --- | --- |
| `ciril.format`, `ciril.colonnes` | Paramètres | Format attendu par l'import de titres de Ciril (CSV, XLSX ou XML) et ordre des colonnes ; champs disponibles listés dans l'aide du paramètre | Finances → Titres vers Ciril → « Créer le lot » : le fichier s'importe dans Ciril en recette éditeur |
| `ciril.csv_separateur`, `ciril.csv_encodage`, `ciril.xml_racine`, `ciril.xml_element` | Paramètres | Détails du format | Même test |
| `ciril.imputation`, `ciril.code_produit` | Paramètres | Imputation budgétaire et code produit des recettes de location | Colonnes « Imputation » et « Code produit » du lot |
| `ciril.import_colonnes` | Paramètres | En-têtes de l'état des titres soldés exporté de Ciril (titre, référence de la facture, montant, date, référence du paiement) | Finances → Encaissements → importer l'état : les factures passent « Soldée », les lignes non rapprochées figurent au rapport |
| `comptable.titulaire`, `comptable.iban`, `comptable.bic` | Paramètres | Coordonnées du compte du comptable public (Trésor public) | Les factures et le portail affichent ces coordonnées et la référence à indiquer |
| Grille tarifaire et délibération | Finances → Grilles tarifaires | Tarifs votés par le conseil municipal, référence et date de la délibération ; cautions par espace | Simulation publique d'une salle des fêtes sur le portail |
| `acomptes.taux`, `factures.echeance_jours`, `devis.validite_jours` | Paramètres | Règles financières de la Ville | Devis et facture d'une location |
| `caution.seuil_double_validation_centimes`, `caution.delai_restitution_jours` | Paramètres | Seuil au-delà duquel une retenue est validée par le service financier ; délai de restitution | Retenue au-delà du seuil : état « Retenue à valider » |
| Modèles « devis », « facture », « avoir » | Documents → Modèles | Charte de la Ville (logo, mentions légales du comptable) | Générer un devis : PDF/A conforme |

## 11. Application mobile des gardiens et planning du personnel — MOB-01 à MOB-08, PER-07, PER-08, SEC-10

| Réglage | Où | À fournir | Comment tester |
| --- | --- | --- | --- |
| `MOBILE_OPTION` (`A` ou `B`) | `deploy/lan/.env` et `deploy/dmz/.env` | Choix de la DSI : A = application et API joignables par le VPN des smartphones (recommandé) ; B = par Internet via la DMZ, certificat d'appareil et double authentification obligatoires | Option A : depuis un smartphone connecté au VPN, ouvrir `https://gardiens.<domaine LAN>` et se connecter avec un compte du groupe « Gardiens » |
| Nom `gardiens.<domaine>` et certificat | DNS interne (A) ou public (B), `deploy/*/secrets` | Entrée DNS et certificat serveur reconnu par les smartphones (autorité interne déployée par la MDM) | L'application s'installe (« Ajouter à l'écran d'accueil ») et s'ouvre en mode avion |
| Certificats d'appareil (option B) | Autorité interne, profil MDM, Personnel → Appareils mobiles | Un certificat client par smartphone ; le PEM est collé dans la fiche de l'appareil (seule l'empreinte est conservée) | Sans certificat, la connexion est refusée ; un appareil retiré perd ses sessions immédiatement |
| Groupe de l'annuaire « Gardiens » → rôle `gardien` | Administration → Groupes de l'annuaire | DN du groupe des gardiens | Le gardien se connecte ; sa fiche agent (champ « Identifiant de l'annuaire ») est rattachée à sa première connexion |
| `mobile.horizon_jours`, `mobile.alerte_heures`, `mobile.purge_jours` | Paramètres (groupe Mobile) | Horizon du planning embarqué (14 j), alerte de fraîcheur (24 h), effacement sans synchronisation (7 j) | Bandeau « plus de 24 h » ; effacement après 7 jours |
| Format de l'export paie | Personnel → Compteurs d'heures | Colonnes attendues par le logiciel de paie de la DRH (export livré : CSV point-virgule, heures décimales) | Exporter le mois et l'importer dans la paie en recette |
| Abonnements iCal | Personnel → Agents → « Lien iCal » | Rien : l'adresse est servie par l'API de gestion, joignable du LAN et du VPN | Abonner un agenda au lien puis le révoquer : l'agenda ne se met plus à jour |

## 11 bis. Pilotage, éditions et valorisation — VAL-01 à VAL-08, STA-01 à STA-05, DSH-01 à DSH-06, IMP-01 à IMP-04

| Élément | Où le saisir | Ce que la Ville fournit | Vérification |
| --- | --- | --- | --- |
| Seuils de convention et de compte rendu | Paramètres (groupe Valorisation), réservés à l'ordonnateur (`gerer_tarifs`) | Confirmation par le service juridique des seuils (23 000 €, 153 000 €) et de leur fondement (ADR 0007, point 4) | Une association au-delà de 23 000 € (nature + numéraire) apparaît en alerte dans la synthèse |
| Méthodes par famille et délibérations | Pilotage → Méthodes de valorisation | Délibération fixant la méthode (tarif voté par défaut ; coût de revient ou valeur locative), références des délibérations | Calculer un exercice puis comparer une ligne avec la grille votée |
| Coût horaire chargé du personnel dédié | Paramètres (`valorisation.cout_horaire_personnel_centimes`), repris par chaque nouvel exercice | Coût chargé d'une heure de gardien (DRH) | Une séance gardiennée fait apparaître une ligne « Personnel dédié » |
| Import des subventions en numéraire | Pilotage → Valorisation → « Importer les subventions » | Export CSV du logiciel financier (CIVIL Finances Publiques) : identifiant (SIRET, RNA ou nom), montant au format 22 980,50, objet, délibération | Importer le fichier de l'exercice : les lignes non rapprochées sont listées avant tout remplacement |
| Signataire de l'attestation | Paramètres `signature.elu_nom` et `signature.elu_courriel` (comme les conventions) | Élu délégataire signataire des attestations de valorisation | Clôturer un exercice de recette, éditer une attestation : l'élu reçoit l'invitation DocuSeal ; l'attestation apparaît sur le portail après signature |
| Date de dépôt des attestations | Paramètre `valorisation.date_depot_attestations` (JJ-MM, défaut 31-03) ou date propre à l'exercice | Date à laquelle les associations doivent disposer de l'attestation | Le compteur « Attestations à déposer » passe en alerte 30 jours avant |
| Domaines des destinataires des plannings | Paramètre `pilotage.domaines_destinataires` (défaut chatillon92.fr) | Domaines de messagerie professionnels autorisés (Ville, éventuellement établissements partenaires) | Une adresse hors domaine est refusée à la saisie de l'envoi programmé |
| Plage d'ouverture par défaut des statistiques | Paramètre `statistiques.ouverture_defaut` (8 h – 22 h) | Heures d'ouverture retenues pour un espace sans horaires saisis | Le taux d'occupation d'un espace sans horaires est calculé sur cette plage |

## 12. PayFiP — TAR-07, POR-07 (lot 7)

À ouvrir **seulement après la signature de la convention d'adhésion à PayFiP avec la DGFiP** (skill `finances-ciril`).
Tant que `PAYFIP_ACTIF=0`, aucun bouton de paiement n'apparaît et la facture ne mentionne pas le paiement en ligne.

| Élément | Où le saisir | Ce que la Ville fournit | Vérification |
| --- | --- | --- | --- |
| Mode PayFiP | `PAYFIP_MODE` (`deploy/lan/parametres.env`) : `titres` (défaut, Titres et Rôles : factures titrées dans CIVIL Finances Publiques) ou `regie` (factures payées à la régie avant leur transmission au comptable) — ADR 0008 | Choix fait avec le comptable public lors de l'adhésion ; acte constitutif de la régie pour le mode Régie | En `titres`, seule une facture portant un numéro de titre affiche « Payer en ligne » ; en `regie`, seule une facture non encore transmise. En Régie, l'export des titres signale les sommes encaissées (`mode_encaissement`) pour un titre de régularisation |
| Sortie vers la DGFiP | `PAYFIP_PROXY` (proxy de la Ville, liste blanche `www.payfip.gouv.fr`) ; seul le worker sort | Adresse du proxy et ouverture du flux 443 | Le rapprochement horaire relit une tentative de test sans erreur « injoignable » |
| Montant minimal | `PAYFIP_MONTANT_MINIMUM_CENTIMES` (défaut 100 = 1 €) | Montant minimal accepté par PayFiP (guide en vigueur) | Une facture en deçà ne propose pas le paiement en ligne |
| Numéro de client (`numcli`) | `PAYFIP_NUMCLI` | Numéro attribué par la DGFiP | `verifier_deploiement` refuse un numéro vide |
| Saisie | `PAYFIP_SAISIE` : T (test), X (activation), W (production) | Calendrier d'ouverture convenu avec la DGFiP | `verifier_deploiement` refuse T hors recette |
| Adresses PayFiP | `PAYFIP_URL_SERVICE` (service SOAP), `PAYFIP_URL_PAIEMENT` (page de paiement) | Adresses du guide de mise en œuvre en vigueur (défaut : www.payfip.gouv.fr) | Un paiement de test aboutit, saisie X |
| Adresse de notification | `PAYFIP_URL_NOTIFICATION` (défaut : portail + `/api/portail/payfip/notification`) | Nom public du portail | La notification arrive à la façade, qui ne l'accepte que des adresses de la DGFiP |
| Adresses IP des notifications | `IPS_NOTIFICATION_PAYFIP` (`deploy/dmz/parametres.env`, D-020) | Liste communiquée par la DGFiP | Une notification venue d'ailleurs est refusée (403) et journalisée |
| Clé de signature des notifications | secret `payfip_secret` (24 caractères au moins, `make secrets`) | Rien (générée localement) | Une notification à l'adresse modifiée est écartée sans appel à PayFiP |
| Encaissements PayFiP dans Ciril | Import des encaissements (Finances → Encaissements) | Avec l'éditeur : présence des paiements PayFiP dans l'état des encaissements | Une ligne qui correspond à un paiement en ligne déjà enregistré est comptée « confirmée par le comptable », sans doublon (D-072) |
| Trop-perçus | Finances → Paiements en ligne (« Enregistrer le remboursement ») | Procédure de remboursement (régie ou comptable public) | Un paiement arrivé sur une facture réglée entre-temps est signalé au service (`portail.service_courriel`) ; « à vérifier » si un règlement de même montant existe déjà |
| Points à confirmer dans le guide PayFiP | — | Valeurs de `resultrans` (dont V), format de `refdet` et `objet`, durée de validité d'un idOp, nouvelles tentatives de notification | Paiement de test en saisie X avant l'ouverture (W) |


