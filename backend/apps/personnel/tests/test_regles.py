"""PER-05 : chaque règle de temps de travail est une fonction pure, testée isolément (valeurs du décret 2000-815)."""

from __future__ import annotations

from datetime import datetime, timedelta

from apps.personnel import regles

PARIS = regles.PARIS
V = {
    "max_quotidien": 600,
    "amplitude_max": 720,
    "repos_quotidien": 660,
    "max_hebdo": 2880,
    "moyenne_12_semaines": 2640,
    "repos_hebdo": 2100,
    "pause_apres": 360,
    "pause": 20,
}


def p(jour: int, debut: int, fin: int, mois: int = 11) -> regles.Plage:
    d = datetime(2026, mois, jour, debut, tzinfo=PARIS)
    f = (
        datetime(2026, mois, jour, fin, tzinfo=PARIS)
        if fin > debut
        else datetime(2026, mois, jour, 0, tzinfo=PARIS) + timedelta(days=1, hours=fin)
    )
    return d, f


def codes(violations: list[regles.Violation]) -> list[str]:
    return [v.code for v in violations]


def test_per05_vacation_de_plus_de_10_heures_signalee():
    assert codes(regles.duree_quotidienne([p(2, 8, 19)], V)) == ["duree_quotidienne"]
    assert regles.duree_quotidienne([p(2, 8, 18)], V) == []


def test_per05_amplitude_de_la_journee():
    assert codes(regles.amplitude([p(2, 7, 9), p(2, 17, 20)], V)) == ["amplitude"]
    assert regles.amplitude([p(2, 8, 10), p(2, 17, 20)], V) == []


def test_per05_repos_quotidien_de_11_heures():
    assert codes(regles.repos_quotidien([p(2, 14, 23), p(3, 8, 12)], V)) == ["repos_quotidien"]
    assert regles.repos_quotidien([p(2, 14, 21), p(3, 8, 12)], V) == []


def test_per05_duree_hebdomadaire_de_48_heures():
    semaine = [p(jour, 8, 18) for jour in range(2, 7)]  # 50 h du lundi au vendredi
    assert codes(regles.duree_hebdomadaire(semaine, V)) == ["duree_hebdomadaire"]
    assert regles.duree_hebdomadaire(semaine[:4], V) == []


def test_per05_moyenne_sur_douze_semaines():
    lourd = [
        (
            datetime(2026, 9, 7, 8, tzinfo=PARIS) + timedelta(weeks=s, days=j),
            datetime(2026, 9, 7, 17, 30, tzinfo=PARIS) + timedelta(weeks=s, days=j),
        )
        for s in range(12)
        for j in range(5)
    ]
    assert "moyenne_12_semaines" in codes(regles.moyenne_douze_semaines(lourd, V))
    leger = [(d, f - timedelta(hours=2)) for d, f in lourd]
    assert regles.moyenne_douze_semaines(leger, V) == []


def test_per05_repos_hebdomadaire_de_35_heures():
    toute_la_semaine = [p(jour, 8, 16) for jour in range(2, 9)]  # 7 jours travaillés
    assert codes(regles.repos_hebdomadaire(toute_la_semaine, V)) == ["repos_hebdomadaire"]
    assert regles.repos_hebdomadaire(toute_la_semaine[:5], V) == []


def test_per05_pause_au_dela_de_6_heures_en_avertissement():
    violations = regles.pause([p(2, 8, 15)], V)
    assert codes(violations) == ["pause"] and violations[0].gravite == "avertissement"


def test_per05_changement_d_heure_compte_la_duree_reelle():
    """Nuit du 25 octobre 2026 : 2 h → 3 h → 2 h ; une vacation 20 h – 7 h dure 12 heures réelles."""
    nuit = (datetime(2026, 10, 24, 20, tzinfo=PARIS), datetime(2026, 10, 25, 7, tzinfo=PARIS))
    from datetime import UTC

    assert int((nuit[1].astimezone(UTC) - nuit[0].astimezone(UTC)).total_seconds() // 3600) == 12
    assert codes(regles.duree_quotidienne([nuit], V)) == ["duree_quotidienne"]


def test_per05_verifier_limite_aux_periodes_touchees():
    plages = [p(2, 8, 19), p(20, 8, 12)]
    assert codes(regles.verifier(plages, V, autour=p(20, 8, 12))) == []
    assert "duree_quotidienne" in codes(regles.verifier(plages, V, autour=p(2, 8, 19)))


def test_per05_changement_d_heure_discriminant():
    """21 h – 7 h la nuit du 24 au 25 octobre 2026 : 10 h à l'horloge, 11 h réelles ; seul le calcul en UTC la signale."""
    nuit = (datetime(2026, 10, 24, 21, tzinfo=PARIS), datetime(2026, 10, 25, 7, tzinfo=PARIS))
    assert nuit[1] - nuit[0] == timedelta(hours=10)  # soustraction d'heures locales : le piège évité
    assert codes(regles.duree_quotidienne([nuit], V)) == ["duree_quotidienne"]


def test_per05_repos_hebdomadaire_sur_fenetre_glissante():
    """Repos du samedi 18 h au lundi 8 h (38 h) : conforme, même si la semaine civile n'en contient que 30."""
    semaine = [p(j, 8, 18) for j in (2, 3, 4, 5, 6)] + [p(7, 8, 18), p(9, 8, 18), p(10, 8, 18)]
    assert regles.repos_hebdomadaire(semaine, V) == []
    sans_repos = [p(j, 8, 20) for j in range(2, 17)]
    assert "repos_hebdomadaire" in codes(regles.repos_hebdomadaire(sans_repos, V))


def test_per05_pause_sur_deux_vacations_enchainees():
    violations = regles.pause([p(2, 8, 12), p(2, 12, 16)], V)
    assert codes(violations) == ["pause"]
    assert (
        regles.pause([p(2, 8, 12), (datetime(2026, 11, 2, 12, 30, tzinfo=PARIS), datetime(2026, 11, 2, 16, tzinfo=PARIS))], V)
        == []
    )
