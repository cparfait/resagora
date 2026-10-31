---
name: valorisation-subventions
description: Calcul et restitution de la valorisation des avantages en nature (subventions en nature) accordés aux associations - cadre légal, méthodes de calcul, attestation annuelle, annexe du compte administratif, seuil de 23 000 euros. À charger pour tout code dans apps/valorisation ou touchant gratuités et réductions.
---

# Valorisation des avantages en nature

## Cadre légal (cahier des charges §4.12)

| Texte | Ce que l'outil doit produire |
| --- | --- |
| CGCT art. L. 2313-1 | Liste des concours en nature et en subventions par bénéficiaire, annexée au compte administratif |
| Loi 2000-321 art. 10 + décret 2001-495 | Alerte quand subventions numéraire + nature dépassent 23 000 €/an (convention obligatoire) ; 153 000 € (compte rendu financier) |
| CGPPP art. L. 2125-1 et L. 2125-1-2 | Toute gratuité porte son fondement (délibération ou convention) |
| Règlement ANC 2018-06 | Attestation annuelle permettant à l'association de valoriser ses contributions volontaires en nature (comptes 86/87, notamment 861/871) |

## Méthodes (paramétrées par famille d'espaces, référence de délibération)

1. **Tarif de référence** (défaut) : heures × tarif voté pour le type d'usager.
2. **Coût de revient horaire** : charges annuelles de l'espace / heures d'ouverture.
3. **Valeur locative** : loyer théorique au m² × surface × part de temps d'occupation (locaux à l'année, partagés).

Formule par association a et exercice :

```
V_a = Σ_réservations (heures × taux_horaire × part_occupation)
    + Σ_matériel (quantité × tarif)
    + Σ_personnel_dédié (heures × coût_horaire_chargé)
```

`part_occupation` = 1 si exclusif, prorata si l'espace est partagé simultanément.

## Règles

- Base = occurrences non annulées dans les délais ; absences non signalées valorisées (VAL-03, paramétrable).
- Montant figé à la clôture de l'exercice ; recalcul uniquement par procédure tracée.
- La valorisation se calcule sur le **tarif de référence conservé** : si une gratuité a été saisie sans tarif de référence, c'est une erreur bloquante (RG-05).
- Les services municipaux et écoles publiques ne reçoivent pas d'attestation (statistiques seulement).

## Restitutions

- Attestation PDF annuelle par association (modèle versionné), signée, déposée sur le portail avant la date paramétrée (VAL-04).
- État de l'annexe du compte administratif : bénéficiaire, nature, montant (VAL-05), export tableur.
- Simulation en cours d'année pour préparer les demandes de subvention (VAL-07).

## Tests indispensables

Gratuité totale ; réduction partielle (seul l'écart est valorisé) ; espace partagé à deux associations ; annulation hors délai ; changement de méthode entre deux exercices ; franchissement du seuil de 23 000 € avec subvention numéraire importée.
