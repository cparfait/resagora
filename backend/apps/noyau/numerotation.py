"""Numéros chronologiques sans trou, attribués dans la transaction de l'objet numéroté (TAR-05)."""

from __future__ import annotations

from django.db import transaction

from .models import Compteur


def prochain(cle: str) -> int:
    """Incrémente le compteur sous verrou de ligne : un numéro n'est consommé que si la transaction aboutit."""
    if not transaction.get_connection().in_atomic_block:
        raise RuntimeError("La numérotation doit être appelée dans une transaction.")
    compteur, _ = Compteur.objects.select_for_update().get_or_create(cle=cle)
    compteur.valeur += 1
    compteur.save(update_fields=["valeur"])
    return compteur.valeur


def numero(prefixe: str, annee: int, largeur: int = 5) -> str:
    return f"{prefixe}{annee}-{prochain(f'{prefixe}{annee}'):0{largeur}d}"
