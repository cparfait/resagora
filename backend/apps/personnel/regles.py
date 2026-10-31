"""Moteur de règles du temps de travail (PER-05) : chaque règle est une fonction pure, testée isolément.

`verifier(plages, valeurs)` reçoit les plages de travail d'un agent (début, fin en UTC) et les valeurs des
paramètres ; il renvoie les violations. Les garanties par défaut sont celles du décret n° 2000-815 (durée
maximale hebdomadaire, moyenne sur 12 semaines, durée quotidienne, amplitude, repos quotidien et hebdomadaire,
pause), à aligner sur le protocole temps de travail de la Ville (paramètres `personnel.*`).
"""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Callable, Iterable
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from functools import wraps
from itertools import pairwise
from zoneinfo import ZoneInfo

PARIS = ZoneInfo("Europe/Paris")
Plage = tuple[datetime, datetime]


@dataclass(frozen=True)
class Violation:
    code: str
    message: str
    du: date
    au: date
    gravite: str = "bloquant"  # bloquant (forçage motivé) | avertissement

    def en_dict(self) -> dict[str, str]:
        return {
            "code": self.code,
            "message": self.message,
            "gravite": self.gravite,
            "du": self.du.isoformat(),
            "au": self.au.isoformat(),
        }


def _heures(minutes: float) -> str:
    h, m = divmod(round(minutes), 60)
    return f"{h} h {m:02d}" if m else f"{h} h"


def _jour(instant: datetime) -> date:
    return instant.astimezone(PARIS).date()


def _lundi(instant: datetime) -> date:
    jour = _jour(instant)
    return jour - timedelta(days=jour.weekday())


def _en_utc(
    regle: Callable[[list[Plage], dict[str, int]], list[Violation]],
) -> Callable[[list[Plage], dict[str, int]], list[Violation]]:
    """Durées calculées en UTC : une soustraction d'heures locales ignorerait le changement d'heure."""

    @wraps(regle)
    def appliquer(plages: list[Plage], v: dict[str, int]) -> list[Violation]:
        return regle([(d.astimezone(UTC), f.astimezone(UTC)) for d, f in plages], v)

    return appliquer


def _minutes(plage: Plage) -> float:
    return (plage[1] - plage[0]).total_seconds() / 60


def _trier(plages: Iterable[Plage]) -> list[Plage]:
    return sorted(plages, key=lambda p: p[0])


@_en_utc
def duree_quotidienne(plages: list[Plage], v: dict[str, int]) -> list[Violation]:
    par_jour: dict[date, float] = defaultdict(float)
    for p in plages:
        par_jour[_jour(p[0])] += _minutes(p)
    return [
        Violation(
            "duree_quotidienne",
            f"{jour:%d/%m/%Y} : {_heures(total)} de travail (maximum {_heures(v['max_quotidien'])}).",
            jour,
            jour,
        )
        for jour, total in sorted(par_jour.items())
        if total > v["max_quotidien"]
    ]


@_en_utc
def amplitude(plages: list[Plage], v: dict[str, int]) -> list[Violation]:
    bornes: dict[date, list[datetime]] = {}
    for debut, fin in plages:
        jour = _jour(debut)
        actuel = bornes.get(jour)
        bornes[jour] = [min(actuel[0], debut), max(actuel[1], fin)] if actuel else [debut, fin]
    return [
        Violation(
            "amplitude",
            f"{jour:%d/%m/%Y} : amplitude de {_heures((b[1] - b[0]).total_seconds() / 60)} (maximum {_heures(v['amplitude_max'])}).",
            jour,
            jour,
        )
        for jour, b in sorted(bornes.items())
        if (b[1] - b[0]).total_seconds() / 60 > v["amplitude_max"]
    ]


@_en_utc
def repos_quotidien(plages: list[Plage], v: dict[str, int]) -> list[Violation]:
    """Entre la dernière vacation d'une journée et la première du jour suivant, repos d'au moins 11 h."""
    violations = []
    triees = _trier(plages)
    for precedente, suivante in pairwise(triees):
        if _jour(suivante[0]) == _jour(precedente[0]):
            continue
        repos = (suivante[0] - precedente[1]).total_seconds() / 60
        if 0 <= repos < v["repos_quotidien"]:
            violations.append(
                Violation(
                    "repos_quotidien",
                    f"Repos de {_heures(repos)} seulement avant le {_jour(suivante[0]):%d/%m/%Y} (minimum {_heures(v['repos_quotidien'])}).",
                    _jour(precedente[0]),
                    _jour(suivante[0]),
                )
            )
    return violations


@_en_utc
def duree_hebdomadaire(plages: list[Plage], v: dict[str, int]) -> list[Violation]:
    par_semaine: dict[date, float] = defaultdict(float)
    for p in plages:
        par_semaine[_lundi(p[0])] += _minutes(p)
    return [
        Violation(
            "duree_hebdomadaire",
            f"Semaine du {lundi:%d/%m/%Y} : {_heures(total)} (maximum {_heures(v['max_hebdo'])}).",
            lundi,
            lundi + timedelta(days=6),
        )
        for lundi, total in sorted(par_semaine.items())
        if total > v["max_hebdo"]
    ]


@_en_utc
def moyenne_douze_semaines(plages: list[Plage], v: dict[str, int]) -> list[Violation]:
    par_semaine: dict[date, float] = defaultdict(float)
    for p in plages:
        par_semaine[_lundi(p[0])] += _minutes(p)
    violations = []
    for lundi in sorted(par_semaine):
        fenetre = [par_semaine.get(lundi - timedelta(weeks=k), 0.0) for k in range(12)]
        moyenne = sum(fenetre) / 12
        if moyenne > v["moyenne_12_semaines"]:
            violations.append(
                Violation(
                    "moyenne_12_semaines",
                    f"Moyenne de {_heures(moyenne)} sur les 12 semaines achevées la semaine du {lundi:%d/%m/%Y} (maximum {_heures(v['moyenne_12_semaines'])}).",
                    lundi - timedelta(weeks=11),
                    lundi + timedelta(days=6),
                )
            )
    return violations


@_en_utc
def repos_hebdomadaire(plages: list[Plage], v: dict[str, int]) -> list[Violation]:
    """Dans chaque semaine travaillée, une période de repos continue d'au moins 35 h. Le repos est cherché sur la
    semaine élargie d'un jour de chaque côté : un repos du samedi soir au lundi matin compte (fenêtre glissante)."""
    violations = []
    triees = _trier(plages)
    semaines = sorted({_lundi(p[0]) for p in triees})
    for lundi in semaines:
        debut_semaine = datetime(lundi.year, lundi.month, lundi.day, tzinfo=PARIS).astimezone(UTC)
        suivant = lundi + timedelta(days=7)
        fin_semaine = datetime(suivant.year, suivant.month, suivant.day, tzinfo=PARIS).astimezone(UTC)
        fenetre = (debut_semaine - timedelta(days=1), fin_semaine + timedelta(days=1))
        contenu = [(max(d, fenetre[0]), min(f, fenetre[1])) for d, f in triees if d < fenetre[1] and f > fenetre[0]]
        bornes = [fenetre[0], *[x for p in contenu for x in p], fenetre[1]]
        plus_long = max((bornes[i + 1] - bornes[i]).total_seconds() / 60 for i in range(0, len(bornes) - 1, 2))
        if plus_long < v["repos_hebdo"]:
            violations.append(
                Violation(
                    "repos_hebdomadaire",
                    f"Semaine du {lundi:%d/%m/%Y} : repos continu le plus long de {_heures(plus_long)} (minimum {_heures(v['repos_hebdo'])}).",
                    lundi,
                    lundi + timedelta(days=6),
                )
            )
    return violations


@_en_utc
def pause(plages: list[Plage], v: dict[str, int]) -> list[Violation]:
    """Travail continu au-delà du seuil sans pause : deux vacations qui s'enchaînent sans pause comptent ensemble."""
    continues: list[Plage] = []
    for debut, fin in _trier(plages):
        if continues and (debut - continues[-1][1]).total_seconds() / 60 < v["pause"]:
            continues[-1] = (continues[-1][0], max(continues[-1][1], fin))
        else:
            continues.append((debut, fin))
    return [
        Violation(
            "pause",
            f"{_jour(p[0]):%d/%m/%Y} : {_heures(_minutes(p))} sans interruption, prévoir une pause de {v['pause']} min.",
            _jour(p[0]),
            _jour(p[1]),
            gravite="avertissement",
        )
        for p in continues
        if _minutes(p) > v["pause_apres"]
    ]


REGLES: list[Callable[[list[Plage], dict[str, int]], list[Violation]]] = [
    duree_quotidienne,
    amplitude,
    repos_quotidien,
    duree_hebdomadaire,
    moyenne_douze_semaines,
    repos_hebdomadaire,
    pause,
]


def valeurs_parametrees() -> dict[str, int]:
    from apps.noyau.parametres import parametre

    return {
        "max_quotidien": int(parametre("personnel.max_quotidien_minutes")),
        "amplitude_max": int(parametre("personnel.amplitude_max_minutes")),
        "repos_quotidien": int(parametre("personnel.repos_quotidien_minutes")),
        "max_hebdo": int(parametre("personnel.max_hebdo_minutes")),
        "moyenne_12_semaines": int(parametre("personnel.moyenne_12_semaines_minutes")),
        "repos_hebdo": int(parametre("personnel.repos_hebdo_minutes")),
        "pause_apres": int(parametre("personnel.pause_apres_minutes")),
        "pause": int(parametre("personnel.pause_minutes")),
    }


def verifier(plages: Iterable[Plage], valeurs: dict[str, int] | None = None, *, autour: Plage | None = None) -> list[Violation]:
    """Toutes les violations ; `autour` ne garde que celles dont la période touche cette plage."""
    valeurs = valeurs or valeurs_parametrees()
    liste = _trier(plages)
    violations = [violation for regle in REGLES for violation in regle(liste, valeurs)]
    if autour is None:
        return violations
    du, au = _jour(autour[0]), _jour(autour[1])
    return [violation for violation in violations if violation.du <= au and violation.au >= du]
