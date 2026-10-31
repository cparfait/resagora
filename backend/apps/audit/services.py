"""Écriture et vérification du journal d'audit (SEC-08).

Chaque entrée porte l'empreinte de la précédente : toute modification, suppression ou insertion
hors application rompt la chaîne et est détectée par `verifier_chaine()`. Un déclencheur
PostgreSQL interdit en outre UPDATE et DELETE sur la table.
"""

from __future__ import annotations

import functools
import hashlib
import json
from collections.abc import Callable
from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal
from typing import Any, ParamSpec, TypeVar

from django.contrib.auth import get_user_model
from django.db import connection, transaction
from django.db.models import Model
from django.forms.models import model_to_dict
from django.utils import timezone

from .contexte import contexte_courant
from .models import JournalAudit

EMPREINTE_ORIGINE = "0" * 64
VERROU_JOURNAL = 7_202_610  # clé du verrou consultatif PostgreSQL qui sérialise la chaîne

P = ParamSpec("P")
R = TypeVar("R")


def _serialisable(valeur: Any) -> Any:
    if isinstance(valeur, datetime | date):
        return valeur.isoformat()
    if isinstance(valeur, Decimal):
        return str(valeur)
    if isinstance(valeur, Model):
        return valeur.pk
    if isinstance(valeur, dict):
        return {str(k): _serialisable(v) for k, v in valeur.items()}
    if isinstance(valeur, list | tuple | set):
        return [_serialisable(v) for v in valeur]
    if hasattr(valeur, "lower") and hasattr(valeur, "upper") and not isinstance(valeur, str):
        return {"debut": _serialisable(valeur.lower), "fin": _serialisable(valeur.upper)}
    if isinstance(valeur, str | int | float | bool) or valeur is None:
        return valeur
    return str(valeur)


CHAMPS_EXCLUS = {"password", "totp_secret_chiffre", "mot_de_passe", "jeton", "empreinte_jeton"}


def instantane(objet: Model | None) -> dict[str, Any] | None:
    """Photographie d'un objet pour le journal, sans champ sensible."""
    if objet is None:
        return None
    donnees = model_to_dict(objet)
    return {k: _serialisable(v) for k, v in donnees.items() if k not in CHAMPS_EXCLUS}


def _contenu_canonique(entree: JournalAudit) -> str:
    return json.dumps(
        {
            "horodatage": entree.horodatage.isoformat(),
            "acteur": entree.acteur_id,
            "acteur_libelle": entree.acteur_libelle,
            "canal": entree.canal,
            "action": entree.action,
            "objet_type": entree.objet_type,
            "objet_id": entree.objet_id,
            "avant": entree.avant,
            "apres": entree.apres,
            "adresse_ip": entree.adresse_ip,
            "precedente": entree.empreinte_precedente,
        },
        sort_keys=True,
        ensure_ascii=False,
        separators=(",", ":"),
    )


def calculer_empreinte(entree: JournalAudit) -> str:
    return hashlib.sha256(_contenu_canonique(entree).encode("utf-8")).hexdigest()


def journaliser(
    action: str,
    objet: Model | None = None,
    *,
    avant: dict[str, Any] | None = None,
    apres: dict[str, Any] | None = None,
    acteur: Any = None,
    objet_type: str = "",
    objet_id: str = "",
) -> JournalAudit:
    """Ajoute une entrée au journal, dans la transaction de l'appelant."""
    contexte = contexte_courant()
    if acteur is None:
        acteur_id, acteur_libelle = contexte.acteur_id, contexte.acteur_libelle
    elif isinstance(acteur, get_user_model()):
        acteur_id, acteur_libelle = acteur.pk, str(acteur)
    else:
        # Contact du portail ou appareil mobile : pas un agent, on garde le libellé.
        acteur_id, acteur_libelle = None, f"{acteur} ({acteur._meta.verbose_name})" if isinstance(acteur, Model) else str(acteur)
    with transaction.atomic():
        with connection.cursor() as curseur:
            curseur.execute("SELECT pg_advisory_xact_lock(%s)", [VERROU_JOURNAL])
        derniere = JournalAudit.objects.order_by("-id").values_list("empreinte", flat=True).first()
        entree = JournalAudit(
            horodatage=timezone.now(),
            acteur_id=acteur_id,
            acteur_libelle=acteur_libelle[:200],
            canal=contexte.canal,
            action=action,
            objet_type=objet_type or (objet._meta.label_lower if objet is not None else ""),
            objet_id=objet_id or (str(objet.pk) if objet is not None and objet.pk is not None else ""),
            objet_libelle=(str(objet)[:300] if objet is not None else ""),
            avant=_serialisable(avant) if avant is not None else None,
            apres=_serialisable(apres) if apres is not None else None,
            adresse_ip=contexte.adresse_ip,
            identifiant_requete=contexte.identifiant_requete,
            empreinte_precedente=derniere or EMPREINTE_ORIGINE,
        )
        entree.empreinte = calculer_empreinte(entree)
        entree.save(force_insert=True)
    return entree


def audite(action: str) -> Callable[[Callable[P, R]], Callable[P, R]]:
    """Décorateur de service : journalise l'objet renvoyé (état après) sous `action`."""

    def decorateur(fonction: Callable[P, R]) -> Callable[P, R]:
        @functools.wraps(fonction)
        def enveloppe(*args: P.args, **kwargs: P.kwargs) -> R:
            with transaction.atomic():
                resultat = fonction(*args, **kwargs)
                objet = resultat if isinstance(resultat, Model) else None
                journaliser(action, objet, apres=instantane(objet), acteur=kwargs.get("acteur"))
            return resultat

        return enveloppe

    return decorateur


@dataclass
class ResultatVerification:
    entrees_verifiees: int
    anomalies: list[str]

    @property
    def integre(self) -> bool:
        return not self.anomalies


def verifier_chaine() -> ResultatVerification:
    """Recalcule toute la chaîne et liste les ruptures (entrée modifiée, supprimée ou insérée)."""
    anomalies: list[str] = []
    precedente = EMPREINTE_ORIGINE
    nombre = 0
    for entree in JournalAudit.objects.order_by("id").iterator(chunk_size=2000):
        nombre += 1
        if entree.empreinte_precedente != precedente:
            anomalies.append(f"Entrée {entree.pk} : chaînage rompu (entrée précédente supprimée ou insérée).")
        if calculer_empreinte(entree) != entree.empreinte:
            anomalies.append(f"Entrée {entree.pk} : contenu modifié après écriture.")
        precedente = entree.empreinte
    return ResultatVerification(nombre, anomalies)
