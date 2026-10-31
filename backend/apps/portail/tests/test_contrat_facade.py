"""SEC-01 : la liste blanche de la façade et les routes de l'API portail correspondent exactement."""

from __future__ import annotations

import re
import sys
from pathlib import Path

from django.urls import URLPattern, URLResolver, get_resolver

RACINE = Path(__file__).resolve().parents[4]
sys.path.insert(0, str(RACINE / "facade"))

from facade.routes import ROUTES  # noqa: E402


def _motifs_django() -> set[str]:
    def parcourir(motifs: list[URLPattern | URLResolver], prefixe: str) -> list[str]:
        resultat = []
        for motif in motifs:
            texte = prefixe + str(motif.pattern)
            if isinstance(motif, URLResolver):
                resultat += parcourir(motif.url_patterns, texte)
            else:
                resultat.append("/" + re.sub(r"<int:\w+>", "{id}", texte).removeprefix("^").removesuffix("$"))
        return resultat

    return {m for m in parcourir(get_resolver("config.urls_portail").url_patterns, "") if m.startswith("/api/portail/")}


def _motifs_facade() -> set[str]:
    return {
        r.motif.pattern.replace("[0-9]{1,12}", "{id}") for r in ROUTES if not r.motif.pattern.startswith("/api/portail/payfip")
    }


def test_sec01_toute_route_de_la_facade_existe_dans_l_api():
    absentes = {m for m in _motifs_facade() if "{uuid}" not in m} - _motifs_django()
    # Routes des lots suivants : attestations de valorisation (lot 6), paiement en ligne PayFiP (lot 7).
    lots_suivants = {
        m
        for m in absentes
        if m.startswith(("/api/portail/attestations", "/api/portail/paiements")) or m.endswith("/paiement-en-ligne")
    }
    assert absentes - lots_suivants == set()


def test_sec01_toute_route_de_l_api_portail_est_dans_la_liste_blanche():
    assert _motifs_django() - _motifs_facade() == set()
