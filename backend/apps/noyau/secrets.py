"""Lecture de la configuration : secrets dans des fichiers (Docker secrets), paramètres en variables (SEC-09)."""

from __future__ import annotations

import os
from pathlib import Path

DOSSIER_SECRETS = Path(os.environ.get("DOSSIER_SECRETS", "/run/secrets"))


def secret(nom: str, defaut: str | None = None) -> str:
    """Valeur du secret `nom` : fichier désigné par `<NOM>_FICHIER`, sinon `/run/secrets/<nom>`.

    En développement et en test uniquement, la variable `<NOM>` peut fournir la valeur.
    """
    variable_fichier = os.environ.get(f"{nom.upper()}_FICHIER")
    chemin = Path(variable_fichier) if variable_fichier else DOSSIER_SECRETS / nom
    if chemin.is_file():
        return chemin.read_text(encoding="utf-8").strip()
    if os.environ.get("ENVIRONNEMENT", "prod") in {"dev", "test"} and nom.upper() in os.environ:
        return os.environ[nom.upper()]
    if defaut is None:
        raise RuntimeError(f"Secret manquant : {nom} (fichier {chemin})")
    return defaut


def booleen(nom: str, defaut: bool) -> bool:
    valeur = os.environ.get(nom)
    return defaut if valeur is None else valeur.strip().lower() in {"1", "true", "oui", "vrai", "yes"}


def entier(nom: str, defaut: int) -> int:
    valeur = os.environ.get(nom)
    return defaut if valeur in (None, "") else int(valeur)


def liste(nom: str, defaut: str) -> list[str]:
    return [element.strip() for element in os.environ.get(nom, defaut).split(",") if element.strip()]
