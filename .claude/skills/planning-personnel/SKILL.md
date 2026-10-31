---
name: planning-personnel
description: Planning des gardiens et agents d'équipement (besoins générés par les réservations, vacations, trames, absences, remplacements, contrôle du temps de travail, compteurs, diffusion mobile et iCal). À charger pour tout code dans apps/personnel.
---

# Planning du personnel

## Du besoin à la vacation

1. Une occurrence `validee`/`confirmee` sur un espace « gardiennage requis » crée un **besoin** : site, début = début − temps d'ouverture (ex. 15 min), fin = fin + temps de fermeture (REF-04, PER-02).
2. Les besoins contigus ou chevauchants d'un même site sont **fusionnés** en une plage.
3. Une **vacation** couvre une ou plusieurs plages : agent, site, début, fin, type (normale, supplémentaire, astreinte).
4. Les **trames** (semaine type par saison) génèrent des vacations récurrentes ; les besoins non couverts restent visibles (DSH-02).
5. Modification/annulation d'une réservation → recalcul du besoin → vacation signalée « à revoir » et agent notifié (RG-09).

## Proposition d'affectation (PER-04)

Candidats = agents affectables au site, habilitations valides à la date (SSIAP, PSC1…), non absents, sans chevauchement (RG-10), respectant les règles de temps de travail. Tri : équilibre des heures sur la période, puis préférence de site. Le planificateur valide.

## Règles de temps de travail (PER-05)

Garanties minimales du décret n° 2000-815 (fonction publique), à confirmer avec le protocole temps de travail de la Ville :

| Règle | Valeur par défaut (paramétrable) |
| --- | --- |
| Durée maximale hebdomadaire | 48 h |
| Moyenne sur 12 semaines consécutives | 44 h |
| Durée quotidienne maximale | 10 h |
| Amplitude maximale de la journée | 12 h |
| Repos quotidien minimal | 11 h |
| Repos hebdomadaire minimal | 35 h, dimanche en principe |
| Pause | 20 min dès 6 h de travail |

Implémenter comme un **moteur de règles** : chaque règle = une fonction pure `verifier(agent, vacations) -> list[Violation]`, testée isolément. Le planificateur peut forcer avec motif (tracé).

## Compteurs (PER-07)

Heures planifiées, réalisées, supplémentaires, de nuit (21 h–6 h, paramétrable), dimanches et fériés. Export pour la paie (CSV au format convenu avec la DRH). Fuseau Europe/Paris, attention aux changements d'heure.

## Diffusion

- Application mobile **hors ligne** de l'agent (les gymnases n'ont pas de réseau) : voir le skill `mobile-gardiens` (MOB-01 à MOB-08). Les heures réelles pointées sur le mobile alimentent les compteurs « réalisées ».
- Abonnement iCal personnel à jeton révocable (PER-08, IMP-05).
- PDF planning par personne / par site, envoi programmé (IMP-02, IMP-04).
- Signalement d'incident depuis le mobile, rattaché à l'occurrence et à l'usager (PER-09).
