"""Contexte de la requête courante (acteur, adresse, canal) utilisé par le journal d'audit."""

from __future__ import annotations

from contextvars import ContextVar
from dataclasses import dataclass


@dataclass(frozen=True)
class ContexteAudit:
    acteur_id: int | None = None
    acteur_libelle: str = ""
    adresse_ip: str | None = None
    canal: str = ""
    identifiant_requete: str = ""


_contexte: ContextVar[ContexteAudit] = ContextVar("contexte_audit", default=ContexteAudit())  # noqa: B039


def contexte_courant() -> ContexteAudit:
    return _contexte.get()


def definir_contexte(contexte: ContexteAudit) -> object:
    return _contexte.set(contexte)


def reinitialiser(jeton: object) -> None:
    _contexte.reset(jeton)  # type: ignore[arg-type]
