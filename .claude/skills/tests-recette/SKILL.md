---
name: tests-recette
description: Stratégie de tests et de recette de la plateforme (pyramide de tests, traçabilité exigence vers test, jeux de données, scénarios transverses, accessibilité, sécurité). À charger avant de proposer une PR, en fin de lot, ou pour écrire des scénarios de recette.
---

# Tests et recette

## Pyramide

| Niveau | Outil | Cible |
| --- | --- | --- |
| Règles de gestion, calculs | pytest (services purs) | Chaque RG et chaque formule |
| API | pytest + client DRF | Chaque endpoint : succès, validation, 401, 403/404 hors périmètre |
| Composants front | Vitest + Testing Library | États chargement / vide / erreur |
| Parcours | Playwright (`e2e/`) | Parcours usager et agent critiques, avec axe-core |
| Sécurité | Trivy, analyse des dépendances, tests d'accès | CI bloquante |

Couverture de l'API métier ≥ 80 % ; 100 % des règles RG-xx couvertes.

## Traçabilité

- Nom des tests : `test_<id_exigence>_<comportement>` (ex. `test_pla04_recurrence_exclut_vacances_zone_c`).
- `docs/recette/matrice.csv` : exigence → tests automatisés → scénario de recette manuel → statut.
- Une exigence M sans test = lot non livrable.

## Jeux de données

- Fabriques `factory_boy` + Faker `fr_FR` ; **aucune donnée personnelle réelle**.
- Jeu de recette : les données d'exemple de CityResa (13 sites, 16 espaces, 41 associations du guide des sports aux contacts fictifs, 47 réservations — `backend/apps/noyau/demo/cityresa.json`), 8 gardiens, une saison complète avec vacances zone C.
- Dates figées (`freezegun`) ; inclure les changements d'heure de mars et d'octobre.

## Scénarios transverses (cahier des charges §9.3)

1. Campagne annuelle complète : demandes → arbitrage → attribution → conventions en lot → signature.
2. Location d'une salle des fêtes par un particulier non résident : devis, PayFiP, caution, état des lieux, retenue partielle.
3. Fermeture imprévue d'un gymnase : occurrences impactées, notification groupée, besoins de gardiennage mis à jour.
4. Absence d'un gardien : vacation non couverte, proposition de remplaçant conforme aux règles de temps de travail.
5. Clôture d'exercice : attestations de valorisation et annexe du compte administratif.

## Avant toute PR

- [ ] `make lint test` vert
- [ ] Tests d'accès refusé présents pour tout nouvel endpoint
- [ ] axe-core sans violation sur les écrans touchés
- [ ] Migration réversible testée (`migrate` puis retour)
- [ ] Aucune nouvelle dépendance sans vérification de version, maintenance et CVE
- [ ] Sous-agents `revue-securite` / `revue-metier` passés si concernés
