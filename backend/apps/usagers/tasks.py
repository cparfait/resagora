"""Tâches planifiées des usagers : relance des pièces (USR-03) et durées de conservation (USR-06)."""

from __future__ import annotations

from celery import shared_task

from . import rgpd
from .services import relancer_pieces


@shared_task(name="apps.usagers.tasks.relancer_pieces")
def tache_relancer_pieces() -> int:
    return relancer_pieces()


@shared_task(name="apps.usagers.tasks.anonymiser_inactifs")
def tache_anonymiser_inactifs() -> int:
    return rgpd.anonymiser_inactifs()


@shared_task(name="apps.usagers.tasks.purger_pieces_expirees")
def tache_purger_pieces_expirees() -> int:
    return rgpd.purger_pieces_expirees()


@shared_task(name="apps.usagers.tasks.purger_archives_echues")
def tache_purger_archives_echues() -> int:
    return rgpd.purger_archives_echues()
