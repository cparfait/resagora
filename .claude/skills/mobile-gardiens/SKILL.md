---
name: mobile-gardiens
description: Application mobile hors ligne des gardiens (PWA installable sur smartphone) pour des gymnases sans réseau - planning local, pointage, états des lieux avec photos et signature, incidents, file de synchronisation, conflits, sécurité des données locales. À charger pour tout code de l'application mobile ou des endpoints de synchronisation.
---

# Application mobile des gardiens (hors ligne)

Contexte : **aucun réseau dans les gymnases** ; les gardiens ont des smartphones, avec une
couverture 4G/5G incertaine. Exigences MOB-01 à MOB-08 (cahier des charges §4.10 bis) ;
accès réseau par VPN de la Ville sur smartphones gérés par MDM (§6.7, option A).

## Architecture

- **PWA** (React 19 + TypeScript 7, Vite 8) dans `mobile/`, installable, servie par le reverse proxy **interne** (accessible via le VPN), jamais publiée en DMZ dans l'option A.
- **Service worker** : cache de l'application (précache versionné) ; mise à jour proposée à l'agent au retour du réseau.
- **Stockage local** : IndexedDB, données chiffrées avec une clé dérivée de la session (Web Crypto, AES-GCM), clé non persistée en clair.
- **Endpoints dédiés** `/api/mobile/*` côté API métier : `GET /mobile/paquet` (planning 14 jours + fiches des créneaux + grilles d'états des lieux), `POST /mobile/saisies` (lot de saisies terrain).

## Modèle hors ligne

1. **Paquet descendant** : à chaque connexion, l'app télécharge un paquet daté (`genere_le`) contenant uniquement ce dont l'agent a besoin (ses vacations, les créneaux de ses sites, contact référent, effectif, matériel). Ni pièces justificatives, ni montants, ni données d'autres sites (MOB-07).
2. **Saisies montantes** : pointage, heures réelles, états des lieux, incidents. Chaque saisie a un `uuid` généré sur l'appareil, l'horodatage local **et** l'identifiant de l'appareil.
3. **File d'envoi persistante** (IndexedDB) ; envoi par lots dès que `navigator.onLine` et un appel de santé réussissent ; réessais avec backoff ; l'app peut être fermée sans perte (MOB-05).
4. **Idempotence** : le serveur ignore un `uuid` déjà reçu et renvoie l'accusé.
5. **Conflits** (MOB-06) : le serveur fait foi pour les réservations ; une saisie sur une occurrence annulée entre-temps est conservée et signalée au gestionnaire, jamais rejetée silencieusement. Les saisies terrain ne s'écrasent jamais : elles s'ajoutent.
6. **Fraîcheur** : bandeau « données du JJ/MM à HH:MM » ; alerte au-delà de 24 h (MOB-08). Effacement local après 7 jours sans synchronisation ou à la déconnexion.

## États des lieux (MOB-03)

- Grille par espace téléchargée dans le paquet ; photos compressées sur l'appareil (JPEG ~1600 px, qualité 0,7) avant stockage ; horodatage et numéro de créneau incrustés en métadonnées.
- Signature de l'usager au doigt (canvas → PNG) ; nom du signataire saisi.
- À la synchronisation, l'état des lieux de sortie déclenche la proposition de restitution ou de retenue de caution (skill `finances-ciril`).

## Interface

- Gros boutons, utilisable à une main et avec des gants légers, contraste élevé (gymnases mal éclairés), fonctionne en mode avion.
- Indicateur permanent : connecté / hors ligne / N saisies en attente.
- Accessibilité : mêmes exigences que le back-office (navigation, contrastes, libellés).

## Tests

- Playwright avec émulation hors ligne (`context.setOffline(true)`) : saisie hors ligne → fermeture → réouverture → retour réseau → saisie reçue une seule fois.
- Tests de conflit : occurrence annulée pendant que l'agent est hors ligne.
- Test de purge : données effacées après 7 jours simulés sans synchronisation.
