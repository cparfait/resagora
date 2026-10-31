"""Exports tableur sûrs (OWASP ASVS 5.3.10) : une valeur texte venue d'un usager ou d'un agent ne devient jamais
une formule à l'ouverture dans un tableur (CSV ou XLSX), et un texte reste lisible en XML."""

from __future__ import annotations

import re

DEBUTS_DANGEREUX = ("=", "+", "-", "@", "\t", "\r", "\n")
CONTROLES_XML = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f￾￿]")


def cellule_sure(valeur: object) -> str:
    """Neutralise l'injection de formules : un texte commençant par =, +, -, @ ou un caractère de contrôle est préfixé."""
    texte = "" if valeur is None else str(valeur)
    return "'" + texte if texte[:1] in DEBUTS_DANGEREUX else texte


def valeur_sure(valeur: object) -> object:
    """Les nombres restent des nombres (montants d'avoir négatifs compris) ; tout texte est neutralisé."""
    if isinstance(valeur, bool) or valeur is None:
        return "" if valeur is None else str(valeur)
    if isinstance(valeur, (int, float)):
        return valeur
    return cellule_sure(texte_xml(valeur))


def texte_xml(valeur: object) -> str:
    """Retire les caractères de contrôle interdits en XML 1.0 (un nom saisi ne rend pas le fichier invalide)."""
    return CONTROLES_XML.sub("", "" if valeur is None else str(valeur))
