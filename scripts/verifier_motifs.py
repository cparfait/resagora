"""Échoue si le code livré contient un motif interdit.

Motifs : marqueurs de travail non terminé, exceptions « non implémenté », écrans « en
construction », texte de remplissage, fonctions Python vides et fonctions TypeScript vides.
Usage : python scripts/verifier_motifs.py [racine]
"""

from __future__ import annotations

import ast
import re
import sys
from pathlib import Path

RACINE = Path(sys.argv[1]) if len(sys.argv) > 1 else Path(__file__).resolve().parent.parent
DOSSIERS = ["backend", "facade", "backoffice/src", "portail/src", "mobile/src", "e2e", "deploy", "scripts"]
EXTENSIONS = {".py", ".ts", ".tsx", ".js", ".mjs", ".yaml", ".yml", ".html", ".css", ".toml", ".sh", ".conf"}
EXCLUS = {"node_modules", ".venv", "dist", "build", "__pycache__", "playwright-report", "test-results", "coverage"}
CE_FICHIER = Path(__file__).resolve()

# Les motifs sont construits par concaténation pour que ce fichier ne se signale pas lui-même.
MOTIFS = [
    re.compile(r"\b" + "TO" + r"DO\b"),
    re.compile(r"\b" + "FIX" + r"ME\b"),
    re.compile(r"\b" + "X" + r"XX\b"),
    re.compile("NotImplemented" + "Error"),
    re.compile("en " + "construction", re.IGNORECASE),
    re.compile("lorem " + "ipsum", re.IGNORECASE),
]
TS_VIDES = [
    re.compile(r"=>\s*\{\s*\}"),
    re.compile(r"function\s+\w*\s*\([^)]*\)\s*(:\s*[\w<>\[\]| ]+)?\s*\{\s*\}"),
]


def fichiers() -> list[Path]:
    resultat = []
    for dossier in DOSSIERS:
        base = RACINE / dossier
        if not base.exists():
            continue
        for chemin in base.rglob("*"):
            if chemin.is_file() and chemin.suffix in EXTENSIONS and not EXCLUS.intersection(chemin.parts):
                if chemin.resolve() != CE_FICHIER:
                    resultat.append(chemin)
    return resultat


def _corps_vide(noeud: ast.FunctionDef | ast.AsyncFunctionDef) -> bool:
    corps = list(noeud.body)
    if corps and isinstance(corps[0], ast.Expr) and isinstance(getattr(corps[0], "value", None), ast.Constant):
        if isinstance(corps[0].value.value, str):
            corps = corps[1:]
    if not corps:
        return True
    return all(
        isinstance(instr, ast.Pass)
        or (isinstance(instr, ast.Expr) and isinstance(instr.value, ast.Constant) and instr.value.value is Ellipsis)
        for instr in corps
    )


def _est_protocole(classe: ast.ClassDef) -> bool:
    return any(getattr(base, "id", getattr(base, "attr", "")) == "Protocol" for base in classe.bases)


def fonctions_python_vides(chemin: Path, source: str) -> list[str]:
    try:
        arbre = ast.parse(source)
    except SyntaxError as erreur:
        return [f"{chemin}:{erreur.lineno}: syntaxe invalide"]
    erreurs: list[str] = []
    protocoles = {id(n) for c in ast.walk(arbre) if isinstance(c, ast.ClassDef) and _est_protocole(c) for n in c.body}
    for noeud in ast.walk(arbre):
        if isinstance(noeud, (ast.FunctionDef, ast.AsyncFunctionDef)) and id(noeud) not in protocoles:
            if _corps_vide(noeud) and not any(
                getattr(d, "id", getattr(d, "attr", "")) in {"overload", "abstractmethod"} for d in noeud.decorator_list
            ):
                erreurs.append(f"{chemin}:{noeud.lineno}: fonction vide « {noeud.name} »")
    return erreurs


def main() -> int:
    erreurs: list[str] = []
    for chemin in fichiers():
        texte = chemin.read_text(encoding="utf-8", errors="replace")
        for numero, ligne in enumerate(texte.splitlines(), start=1):
            for motif in MOTIFS:
                if motif.search(ligne):
                    erreurs.append(f"{chemin}:{numero}: motif interdit « {motif.pattern} »")
        if chemin.suffix == ".py":
            erreurs.extend(fonctions_python_vides(chemin, texte))
        if chemin.suffix in {".ts", ".tsx"} and ".test." not in chemin.name and ".spec." not in chemin.name:
            for numero, ligne in enumerate(texte.splitlines(), start=1):
                for motif in TS_VIDES:
                    if motif.search(ligne):
                        erreurs.append(f"{chemin}:{numero}: fonction vide")
    for erreur in erreurs:
        print(erreur)
    print(f"{len(erreurs)} motif(s) interdit(s) trouvé(s).")
    return 1 if erreurs else 0


if __name__ == "__main__":
    sys.exit(main())
