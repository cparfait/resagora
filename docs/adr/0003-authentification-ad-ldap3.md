# ADR 0003 — Authentification des agents par l'AD avec ldap3, rôles par groupes

- Date : 2026-10-31
- Statut : accepté
- Exigences : SEC-02, SEC-03, ADM-06, RG-14

## Décision

- Backend Django `apps.habilitations.ldap.LdapBackend` sur **ldap3** (pur Python) : LDAPS ou
  StartTLS avec vérification du certificat (AC fournie en secret), compte de service pour la
  recherche, liaison avec le DN de l'agent pour vérifier le mot de passe, filtres échappés.
- Groupes lus selon `LDAP_MODE_GROUPES` : `ad_imbriques` (règle LDAP_MATCHING_RULE_IN_CHAIN, défaut
  pour l'Active Directory), `memberof`, ou `recherche` (member/uniqueMember).
- À chaque connexion, les habilitations de source « ad » sont **recalculées** à partir de la table
  `GroupeAD` (groupe → rôle × périmètre, écran « Groupes de l'annuaire »). Un agent sans groupe
  correspondant ni habilitation manuelle est refusé.
- Les rôles marqués « double authentification » (administrateur, régisseur, service financier)
  exigent un code TOTP (RFC 6238) ; la graine est chiffrée en base, les codes ne sont pas rejouables.
- Pas de mot de passe local pour les agents (aucun `ModelBackend`).

## Raisons

`django-auth-ldap` dépend de `python-ldap` (extension C) : pas de paquet pour Windows ni pour toutes
les versions de Python 3.14 ; ldap3 couvre tout le besoin et se teste avec sa stratégie `MOCK_SYNC`.

## Raccordement

Paramètres réels : `docs/a-brancher.md` § Active Directory. Diagnostic :
`python manage.py tester_annuaire --identifiant <agent>`.
