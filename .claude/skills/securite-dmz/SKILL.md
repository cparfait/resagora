---
name: securite-dmz
description: Règles de sécurité de la plateforme (séparation DMZ/LAN, façade API portail, authentification AD et usagers, fichiers déposés, OWASP ASVS niveau 2). À charger pour tout code touchant portail/, /api/portail/*, l'authentification, les droits, les fichiers ou la configuration réseau.
---

# Sécurité — DMZ, LAN et application

## Le modèle en une image

```
Internet ──443──> [Reverse proxy + WAF] (DMZ)
                     ├─> Portail web (statique)
                     ├─> Façade API portail ──8443 mTLS──> API métier (LAN)   ← SEUL flux entrant LAN
                     └─> DocuSeal (routes de signature uniquement)
LAN ──443──> DocuSeal (dépôt / récupération)      LAN ──443 via proxy──> PayFiP
```

## Règles d'exposition

1. **Aucune donnée métier en DMZ.** La façade n'a ni base de données ni secret du LAN. Elle garde seulement des sessions usagers (Valkey dédié DMZ) et une quarantaine temporaire de fichiers.
2. **Liste blanche de routes** : la façade relaie uniquement `/api/portail/*` vers l'API métier, méthodes et chemins listés explicitement. Toute autre route → 404.
3. **mTLS** façade → API : certificat client propre à la façade, vérifié par l'API ; l'API refuse toute requête `/api/portail/*` qui n'arrive pas par ce canal.
4. **Interface d'administration DocuSeal non publiée** ; seules les routes de signature passent le reverse proxy.
5. **Retours PayFiP (lot 7) et webhooks DocuSeal** : la façade vérifie (signature/secret, IP source si fournie), relaie ; l'API **revérifie** l'état auprès de la source (PayFiP) avant d'enregistrer un paiement. Traitements idempotents.
6. Le back-office n'est jamais exposé sur Internet.

## Accès mobile des gardiens (cahier des charges §6.7)

Les gymnases n'ont pas de réseau ; les gardiens utilisent des smartphones en 4G/5G.
- **Option A (retenue par défaut)** : smartphones de la Ville gérés par MDM, VPN vers le réseau municipal ; l'application mobile et `/api/mobile/*` restent sur le LAN, **rien n'est ajouté en DMZ**.
- **Option B (seulement si smartphones personnels)** : `/api/mobile/*` relayé par la façade comme le portail, avec authentification AD, double facteur et certificat d'appareil. Toute bascule vers B exige un ADR et une nouvelle analyse de risques.
- Dans tous les cas : jeton lié à l'appareil et révocable, données locales chiffrées et minimales, journal des synchronisations.

## Authentification

- **Agents** : LDAPS vers l'AD ; groupes AD → rôles ; double authentification pour administration et régie (SEC-03). Sessions courtes, cookie `Secure; HttpOnly; SameSite=Lax`.
- **Usagers** : Argon2id, politique de mot de passe conforme aux recommandations ANSSI, verrouillage progressif, double authentification proposée (TOTP), réinitialisation par lien à usage unique de courte durée. Pas d'énumération de comptes (messages identiques).
- Jetons portail liés à l'usager **et** au contact ; un contact ne voit que les dossiers de ses usagers.

## Contrôles applicatifs (OWASP ASVS niveau 2)

- Contrôle d'accès objet par objet côté serveur (IDOR) : chaque test d'endpoint inclut un accès à l'objet d'un autre usager / hors périmètre.
- CSRF actif, CORS fermé (aucune origine tierce), en-têtes : CSP stricte sans `unsafe-inline`, HSTS, `X-Content-Type-Options`, `Referrer-Policy`, `Permissions-Policy`.
- Limitation de débit : connexion, inscription, réinitialisation, dépôt de demande, téléversement.
- Validation des entrées par serializers ; requêtes ORM uniquement (pas de SQL brut concaténé).
- Erreurs : message neutre côté client, détail dans les journaux.

## Fichiers déposés (SEC-07)

1. Réception en quarantaine DMZ, taille max, extension **et** type réel (magic bytes) en liste blanche : PDF, JPEG, PNG.
2. Analyse ClamAV ; si infecté → rejet + journal.
3. Transfert vers l'API, renommage aléatoire, stockage hors racine web, empreinte SHA-256 enregistrée.
4. Téléchargement uniquement via endpoint contrôlé (droits), `Content-Disposition: attachment`.

## Secrets et journaux

- Secrets fournis par fichiers (Docker secrets), jamais en variables d'environnement visibles ni dans le dépôt.
- Journaux sans mot de passe, jeton ni pièce d'identité ; données personnelles minimisées.
- Journal d'audit et journaux techniques ≥ 6 mois, intégrité protégée (SEC-08).

## Dépendances

Dernière version stable supportée de chaque composant (§6.6). Toute nouvelle dépendance : vérifier maintenance, licence, CVE. Correctif critique sous 7 jours.
