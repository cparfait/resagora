# ADR 0006 — Conservation des données personnelles face à l'immuabilité des archives

- Date : 2026-10-31
- Statut : accepté (durées à valider par l'archiviste de la Ville et le délégué à la protection des données)
- Exigences : USR-06, RG-13, SEC-08 ; revue métier du lot 2 (M6)

## Contexte

USR-06 impose des durées de conservation et l'anonymisation des personnes physiques. RG-13 rend
immuables les documents signés, les factures, les avoirs et les journaux de caution : la base refuse leur
modification. Un document signé contient pourtant le nom, l'adresse et la signature d'un particulier.

## Décisions

1. **Deux régimes distincts.**
   - Les **données de gestion** (fiche usager, contacts, comptes, messages, notifications, pièces
     justificatives, signataires des circuits) sont anonymisées quand l'usager n'a plus d'activité depuis
     `rgpd.conservation_mois_inactivite` mois **et** que son dernier dossier est clos depuis
     `rgpd.conservation_mois_dossiers_clos` mois.
   - Les **archives publiques** (conventions, contrats, avenants, devis, factures, avoirs, états des lieux,
     attestations) restent intactes pendant leur durée d'utilité administrative, fixée par nature dans
     `rgpd.conservation_annees_documents` (par défaut : factures et avoirs 10 ans, conventions et
     contrats 5 ans, avis de fermeture 1 an). L'anonymisation de l'usager ne les modifie pas : ce sont
     des pièces justificatives de la comptabilité publique et des engagements de la Ville.
2. **Au terme de la durée**, la tâche mensuelle `purger_archives_echues` efface, pour les seuls usagers
   déjà anonymisés, le contexte de fusion, les signataires et les fichiers (PDF, PDF signé, preuve). Le
   numéro, la nature, le dossier, l'empreinte et le statut restent : la trace de l'existence du document
   et l'intégrité du registre sont conservées.
3. **Levée contrôlée de la protection** : le déclencheur RG-13 n'accepte cette modification que si la
   transaction a posé `SET LOCAL equipements.purge_archives = 'oui'`, ce que seule la procédure de purge
   fait ; même alors, la suppression, le changement de numéro, de fichier, d'empreinte ou de statut
   restent refusés. Chaque purge est journalisée.
4. Les **pièces comptables** (`finances_piececomptable`) gardent leur lien à l'usager anonymisé : son
   libellé neutre suffit à la comptabilité, et elles ne contiennent pas d'autre donnée personnelle.

## Conséquences

- Avant toute élimination, l'archiviste valide les durées (bordereau d'élimination pour les archives
  publiques) : les valeurs se modifient dans l'écran des paramètres, sans développement.
- Un document purgé n'est plus téléchargeable ; l'API répond « supprimé au terme de sa durée de
  conservation ».
