"""Génère docs/recette/matrice.csv : exigence → code → tests automatisés → scénario → statut.

Une exigence est « couverte » quand au moins un fichier de code la cite et qu'au moins un test
porte son identifiant (pytest : `test_pla04_...` ; Vitest/Playwright : « PLA-04 » dans le titre).
Usage : python scripts/matrice.py [--jusqua-lot N]   (code de sortie 1 si une exigence de ces lots est ouverte)
"""

from __future__ import annotations

import argparse
import csv
import re
import sys
from collections import defaultdict
from pathlib import Path

RACINE = Path(__file__).resolve().parent.parent
EXIGENCES = RACINE / "docs" / "recette" / "exigences.csv"
SORTIE = RACINE / "docs" / "recette" / "matrice.csv"
EXCLUS = {"node_modules", ".venv", "dist", "__pycache__", "migrations", "playwright-report", "test-results", "coverage"}
SOURCES = ["backend", "facade", "backoffice/src", "portail/src", "mobile/src", "e2e", "deploy"]
SUFFIXES = {".py", ".ts", ".tsx", ".yaml", ".html", ".docx.json"}


def est_test(chemin: Path) -> bool:
    nom = chemin.name
    return nom.startswith("test_") or ".test." in nom or ".spec." in nom or "tests" in chemin.parts or chemin.parts[0] == "e2e"


def charger() -> list[dict[str, str]]:
    with EXIGENCES.open(encoding="utf-8") as flux:
        return list(csv.DictReader(flux, delimiter=";"))


def indexer(ids: list[str]) -> tuple[dict[str, set[str]], dict[str, set[str]]]:
    code: dict[str, set[str]] = defaultdict(set)
    tests: dict[str, set[str]] = defaultdict(set)
    motifs_code = {i: re.compile(rf"\b{re.escape(i)}\b") for i in ids}
    motifs_py = {i: re.compile(rf"def test_{i.replace('-', '').lower()}(_|\b)") for i in ids}
    motifs_ts = {i: re.compile(rf"(it|test|describe)\([\"'`][^\"'`]*\b{re.escape(i)}\b") for i in ids}
    for dossier in SOURCES:
        for chemin in (RACINE / dossier).rglob("*") if (RACINE / dossier).exists() else []:
            if not chemin.is_file() or EXCLUS.intersection(chemin.parts) or chemin.suffix not in SUFFIXES:
                continue
            relatif = chemin.relative_to(RACINE)
            texte = chemin.read_text(encoding="utf-8", errors="replace")
            if est_test(relatif):
                for i in ids:
                    if motifs_py[i].search(texte) or motifs_ts[i].search(texte):
                        tests[i].add(relatif.as_posix())
            else:
                for i in ids:
                    if motifs_code[i].search(texte):
                        code[i].add(relatif.as_posix())
    return code, tests


def main() -> int:
    parseur = argparse.ArgumentParser()
    parseur.add_argument("--jusqua-lot", type=int, default=None)
    args = parseur.parse_args()
    exigences = charger()
    code, tests = indexer([e["id"] for e in exigences])
    ouvertes = []
    with SORTIE.open("w", encoding="utf-8", newline="") as flux:
        ecrivain = csv.writer(flux, delimiter=";")
        ecrivain.writerow(["id", "lot", "priorite", "libelle", "code", "tests", "scenario_recette", "statut"])
        for e in exigences:
            statut = "couverte" if code[e["id"]] and tests[e["id"]] else "ouverte"
            if statut == "ouverte" and (args.jusqua_lot is None or int(e["lot"]) <= args.jusqua_lot):
                ouvertes.append(e["id"])
            ecrivain.writerow([
                e["id"], e["lot"], e["priorite"], e["libelle"],
                " ".join(sorted(code[e["id"]])), " ".join(sorted(tests[e["id"]])),
                e["scenario_recette"], statut,
            ])
    total = len(exigences)
    print(f"Matrice écrite : {total - len([e for e in exigences if not (code[e['id']] and tests[e['id']])])}/{total} exigences couvertes.")
    if args.jusqua_lot is not None:
        if ouvertes:
            print("Exigences ouvertes : " + ", ".join(ouvertes))
            return 1
        print(f"Toutes les exigences des lots 0 à {args.jusqua_lot} sont couvertes.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
