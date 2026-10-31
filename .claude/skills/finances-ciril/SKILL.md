---
name: finances-ciril
description: Tarification, devis, factures, titres de recettes pour CIVIL Finances Publiques (Ciril GROUP), règlement par virement et suivi des encaissements, cautions, et paiement en ligne PayFiP prévu au lot 7. À charger pour tout code dans apps/finances ou touchant un montant, un paiement ou une caution.
---

# Finances — tarifs, Ciril, virements, cautions

Contexte de la Ville (cahier des charges §1.6) : seuls quelques CSE d'entreprises paient aujourd'hui,
**par virement**. Logiciel financier : **CIVIL Finances Publiques (Ciril GROUP)**. Pas encore de
convention PayFiP : PayFiP est développé **en dernier (lot 7)**. Ne pas l'anticiper dans le code
des lots précédents au-delà d'un point d'extension (interface `ModeReglement`).

## Principes

- Montants en **centimes entiers**. Arrondis explicites et testés.
- Tarif appliqué = celui en vigueur à la date d'occupation, **figé** sur le devis accepté (RG-04).
- Gratuité/réduction = pourcentage sur un tarif de référence conservé + fondement obligatoire (RG-05, TAR-03). Indispensable à la valorisation.
- Numérotation des factures chronologique, sans trou, par exercice (TAR-05). Avoir pour toute correction (RG-13).

## Calcul d'une ligne

```
montant_reference = quantite × tarif(espace, type_usager, unite, date)
                    + majorations (week-end, soirée, férié, non-résident)
                    + prestations annexes (ménage, gardiennage supplémentaire, matériel)
montant_du        = montant_reference × (1 − taux_reduction)
```

Conserver les deux montants sur chaque ligne.

## Titres de recettes pour Ciril (TAR-06)

- Le format d'import n'est pas public : il est défini avec Ciril GROUP lors d'un atelier au lot 0 (module Multi-facturation de CIVIL Finances Publiques ou import dédié). Isoler ce format dans un **adaptateur** (`finances/ciril/export.py`) pour pouvoir le changer sans toucher au métier.
- **Repli V1** (volume faible) : état des factures à titrer exporté en tableur (débiteur, SIRET, objet, imputation, montant, référence facture) ; le service financier saisit les titres dans Ciril puis reporte le numéro de titre dans l'outil.
- Un export = un lot numéroté, rejouable, avec trace de qui l'a produit et quand.

## Règlement par virement et encaissements (TAR-12, TAR-13)

- Avec un titre de recettes, l'argent est encaissé par le **comptable public**, pas par la Ville : la facture porte les coordonnées de paiement communiquées par le comptable et la référence à reporter dans le libellé du virement.
- Statuts de paiement : `a_titrer → titre_emis (n° de titre) → solde | solde_partiel | en_recouvrement`.
- Passage à `solde` : import de l'état des titres soldés exporté de Ciril (format à définir), ou pointage manuel par le régisseur avec date et référence. Jamais sur simple déclaration de l'usager.
- Rapprochement : liste des factures titrées non soldées après échéance (TAR-10).

## Cautions (CAU-01 à CAU-07)

- Statuts : `attendue → recue → restituable → restituee | retenue_partielle | retenue_totale → encaissee`.
- Restitution proposée seulement après l'état des lieux de sortie (RG-11), qui peut venir de l'application mobile hors ligne ; retenue = motif + photos + montant + notification usager.
- Séparation des tâches au-delà d'un seuil ; journal inaltérable ; état exportable ; alerte de délai.
- Modalités de dépôt et de restitution (chèque, consignation, virement) à valider avec le comptable public.

## Lot 7 — PayFiP (TAR-07, POR-07)

Uniquement après signature de la convention avec la DGFiP. Suivre alors le guide de mise en
œuvre PayFiP le plus récent :
1. `TentativePaiement` créée avant redirection.
2. Le retour navigateur n'est jamais une preuve de paiement.
3. Notification reçue par la façade, revérifiée par l'API auprès de PayFiP, traitement idempotent.
4. Rapprochement quotidien.
