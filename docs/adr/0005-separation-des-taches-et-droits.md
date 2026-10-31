# ADR 0005 — Séparation des tâches, objets transversaux et multi-sites, droits en base

- Date : 2026-10-31
- Statut : accepté (rôles initiaux à valider par la DAF et le comptable public)
- Exigences : RG-14, ADM-03, SEC-03, SEC-08 ; revues sécurité et métier du lot 0

## Décisions

1. **Rôles initiaux** (`apps/habilitations/actions.py`, figés dans les migrations 0002 et 0005) :
   - l'**ordonnateur** (service financier) émet factures, avoirs et titres, valide les retenues ;
   - la **régie** encaisse et enregistre la réception et la restitution des cautions ;
   - le **gestionnaire** constate un dommage et *propose* une retenue (`proposer_retenue`), émet devis
     et factures de location, déplace pour priorité municipale avec motif ;
   - l'**administrateur fonctionnel** gère droits, paramètres et modèles, sans acte financier ;
   - le **contrôle interne** lit le journal d'audit ; la direction lit tout sauf le journal.
2. **Cumuls interdits** pour un même agent (`INCOMPATIBILITES`) : encaisser × émettre facture,
   encaisser × émettre avoir, gérer les cautions × valider les retenues, administrer × encaisser.
   Vérifiés à l'attribution manuelle et à la synchronisation AD (le groupe en trop est ignoré et tracé).
3. **Double authentification déduite des actions** : un rôle qui porte une action sensible
   (`ACTIONS_SENSIBLES`) l'exige toujours ; le formulaire refuse de la désactiver.
4. **Périmètres** : en lecture, un objet est accessible si l'un de ses sites est couvert ; en
   écriture, **tous** ses sites doivent l'être. Un objet transversal (usager) suit l'action seule ; un
   objet du référentiel commun (`ecriture_ville_entiere`, ex. familles, paramètres) ne s'écrit qu'avec
   un périmètre « tous sites ». Le journal d'audit ne se lit qu'avec un périmètre « tous sites ».
5. **Base de données** : le rôle propriétaire `equipements` ne sert qu'aux migrations et à la
   maintenance ; l'application utilise `equipements_app` (non superutilisateur, sans DDL), qui n'a sur
   les tables immuables (journal, points de contrôle, ancrages, puis documents signés, factures et
   journaux de caution déclarés `immuable = True`) que SELECT et INSERT (`manage.py accorder_droits`).
6. **Journal d'audit** : empreinte HMAC (clé `audit_cle_hmac`, hors base) de tous les champs, ancrage
   horaire de la dernière empreinte en base et dans les journaux techniques, TRUNCATE interdit, purge
   seulement au-delà de la durée de conservation (≥ 183 jours) avec archive et point de contrôle.

## Conséquences

- Les rôles et cumuls sont paramétrables (écrans « Rôles » et « Agents ») mais les garde-fous
  (double authentification, cumuls) restent imposés par l'API.
- Les journaux techniques doivent être expédiés vers le serveur syslog de la Ville et conservés
  au moins 6 mois (voir `docs/a-brancher.md`).
