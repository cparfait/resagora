"""SEC-01 : la liste blanche de la façade et les routes de l'API portail correspondent exactement."""

from __future__ import annotations

import re
import sys
from pathlib import Path

from django.urls import URLPattern, URLResolver, get_resolver

RACINE = Path(__file__).resolve().parents[4]
sys.path.insert(0, str(RACINE / "facade"))

from facade.routes import JETON, ROUTES, ROUTES_MOBILE, UUID  # noqa: E402


def _motifs_django() -> set[str]:
    def parcourir(motifs: list[URLPattern | URLResolver], prefixe: str) -> list[str]:
        resultat = []
        for motif in motifs:
            texte = prefixe + str(motif.pattern)
            if isinstance(motif, URLResolver):
                resultat += parcourir(motif.url_patterns, texte)
            else:
                texte = re.sub(r"<uuid:\w+>", "{uuid}", re.sub(r"<int:\w+>", "{id}", texte))
                texte = re.sub(r"<jeton:\w+>", "{jeton}", texte)
                resultat.append("/" + texte.removeprefix("^").removesuffix("$"))
        return resultat

    return {
        m
        for m in parcourir(get_resolver("config.urls_portail").url_patterns, "")
        if m.startswith(("/api/portail/", "/api/mobile/"))
    }


def _motifs_facade() -> set[str]:
    return {
        r.motif.pattern.replace("[0-9]{1,12}", "{id}").replace(UUID, "{uuid}").replace(JETON, "{jeton}").replace(r"\.", ".")
        for r in [*ROUTES, *ROUTES_MOBILE]
    }


def test_sec01_toute_route_de_la_facade_existe_dans_l_api():
    assert _motifs_facade() - _motifs_django() == set()


def test_sec01_toute_route_de_l_api_portail_est_dans_la_liste_blanche():
    assert _motifs_django() - _motifs_facade() == set()
