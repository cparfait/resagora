---
name: metier-reservations
description: Règles métier des réservations de salles et équipements sportifs (statuts, récurrences, saisons, conflits, priorités, options). À charger avant toute modification touchant une réservation, une occurrence, un créneau annuel ou le planning.
---

# Métier — réservations

Source : `docs/cahier-des-charges.md` §4.3, §4.17, §5.1. Cite toujours l'ID d'exigence.

## Glossaire

- **Dossier** : unité de gestion d'une demande (un usager, un objet). Contient 1..n réservations.
- **Réservation** : un espace + une règle de récurrence (RRULE) + période. Contient des **occurrences** matérialisées.
- **Occurrence** : un créneau daté. C'est elle qui porte conflits, présence, facturation et valorisation.
- **Créneau annuel** : réservation récurrente attribuée pour une saison sportive (campagne + commission).
- **Option** : pré-réservation avec `expire_le`. Ne bloque pas le créneau (RG-02).
- **Espace partageable** : peut accueillir plusieurs réservations simultanées jusqu'à sa capacité.

## Statuts (PLA-06)

```
demande → en_instruction → validee → confirmee → realisee → cloturee
   ↘ option (expire)     ↘ refusee        ↘ annulee (depuis tout statut avant realisee)
```

- `confirmee` exige ce que le type de réservation demande : dossier complet, convention signée, acompte payé, caution reçue (RG-06). Calcule-le, ne le stocke pas en booléen libre.
- Transitions implémentées comme méthodes de service (`ReservationService.valider(...)`) avec contrôle des droits et écriture du journal d'audit. Jamais de `reservation.statut = ...` direct dans une vue.

## Invariants

| ID | Invariant | Où l'imposer |
| --- | --- | --- |
| RG-01 | Pas de chevauchement de deux occurrences `validee`/`confirmee` sur un même espace, ni espace/sous-espace, sauf partageable | Contrainte d'exclusion PostgreSQL (`btree_gist`, `tstzrange`, `&&`) **et** contrôle applicatif avec message clair |
| RG-02 | Demande/option ne bloque pas | Filtre sur statut dans la contrainte |
| RG-03 | Priorité : Ville > scolaire temps scolaire > assos conventionnées locales > autres assos > entreprises/particuliers | Service d'arbitrage, paramétrable |
| RG-07 | Option expirée libérée après une relance | Tâche Celery planifiée, idempotente |
| RG-09 | Réservation sur espace « gardiennage requis » ⇒ besoin de personnel ; modif/annulation ⇒ mise à jour + notification de l'agent | Signal de domaine → `planning-personnel` |
| RG-12 | Valorisation sur heures non annulées dans les délais | `valorisation-subventions` |

Sous-espaces : réserver le gymnase entier bloque ses tiers de terrain et inversement (REF-05). Modélise la hiérarchie et inclue ancêtres + descendants dans le contrôle de conflit.

## Récurrences (PLA-04)

- Stocke la RRULE (RFC 5545) + `exdates` ; matérialise les occurrences sur la saison.
- Exclure vacances scolaires **zone C** et jours fériés selon le calendrier de la saison (ADM-01).
- Modifier « cette occurrence », « celle-ci et les suivantes », « toute la série » : trois chemins distincts et testés.
- Fuseau : calculs en `Europe/Paris` (changement d'heure !), stockage en UTC.

## Campagne annuelle (PLA-05)

1. Ouverture de campagne (dates) → les associations déposent leurs demandes de créneaux.
2. Instruction, détection des conflits, proposition d'arbitrage selon RG-03.
3. Décision en commission → attribution en lot → notification groupée + refus motivés.
4. Génération en lot des conventions (DOC-06).

## Cas limites à tester systématiquement

- Créneau traversant le changement d'heure d'octobre/mars.
- Réservation qui chevauche une fermeture exceptionnelle créée après coup (REF-06) → occurrences signalées, usager notifié.
- Priorité municipale qui déplace une réservation confirmée (PLA-12).
- Annulation tardive → frais selon barème (RG-08) et valorisation conservée (VAL-03).
- Deux agents valident simultanément deux demandes concurrentes → une seule réussit (contrainte BDD).
