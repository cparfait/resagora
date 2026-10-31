"""Montants en centimes entiers (CLAUDE.md règle 5) : conversions et arrondis explicites."""

from __future__ import annotations

from decimal import ROUND_HALF_UP, Decimal

ESPACE_FINE = " "


def euros(centimes: int) -> str:
    """Affichage français : 123456 → « 1 234,56 € » (espace fine insécable entre milliers)."""
    signe = "-" if centimes < 0 else ""
    entiers, reste = divmod(abs(int(centimes)), 100)
    groupes = f"{entiers:,}".replace(",", ESPACE_FINE)
    return f"{signe}{groupes},{reste:02d} €"


def centimes(valeur: str | Decimal | int) -> int:
    """Conversion d'un montant en euros (texte ou décimal) vers des centimes, arrondi au plus proche."""
    texte = str(valeur)
    for caractere in (" ", ESPACE_FINE, " ", "€"):
        texte = texte.replace(caractere, "")
    texte = texte.replace(",", ".")
    return int((Decimal(texte) * 100).quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def appliquer_taux(montant: int, taux_pour_dix_mille: int) -> int:
    """Applique un taux exprimé en dix-millièmes (10000 = 100 %), arrondi au centime le plus proche."""
    resultat = Decimal(montant) * Decimal(taux_pour_dix_mille) / Decimal(10000)
    return int(resultat.quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def proratiser(montant: int, numerateur: int, denominateur: int) -> int:
    if denominateur == 0:
        return 0
    return int((Decimal(montant) * numerateur / denominateur).quantize(Decimal("1"), rounding=ROUND_HALF_UP))
