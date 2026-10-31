"""Envoi des notifications (COM-01) : rendu du modèle, enregistrement, envoi asynchrone après validation.

Les messages sont rendus depuis des modèles éditables ; ils ne contiennent jamais de jeton ni de
mot de passe. L'envoi se fait par Celery après la validation de la transaction (`on_commit`).
"""

from __future__ import annotations

import logging
import uuid
from collections.abc import Iterable
from typing import Any

from django.conf import settings
from django.core.mail import EmailMessage
from django.db import models, transaction
from django.template import Context, Engine
from django.utils import timezone

from .models import ModeleMessage, Notification

journal = logging.getLogger(__name__)
MOTEUR = Engine(autoescape=False, string_if_invalid="")


def rendre(gabarit: str, contexte: dict[str, Any]) -> str:
    return MOTEUR.from_string(gabarit).render(Context(contexte)).strip()


def destinataires_usager(usager: Any) -> list[Any]:
    """Contacts à prévenir : le contact principal, sinon tous les contacts rattachés."""
    rattachements = list(usager.rattachements.select_related("contact").order_by("-principal"))
    principaux = [r.contact for r in rattachements if r.principal]
    return principaux or [r.contact for r in rattachements]


def notifier(
    code_modele: str,
    contexte: dict[str, Any],
    *,
    contacts: Iterable[Any] = (),
    usager: Any = None,
    objet: models.Model | None = None,
    courriels: Iterable[str] = (),
    groupe: str = "",
) -> list[Notification]:
    """Crée une notification par destinataire et programme l'envoi après validation de la transaction."""
    modele = ModeleMessage.objects.filter(code=code_modele, actif=True).first()
    if modele is None:
        journal.error("Modèle de message introuvable ou inactif : %s", code_modele)
        return []
    destinataires = list(contacts) or (destinataires_usager(usager) if usager is not None else [])
    contexte_complet = {"portail_url": getattr(settings, "PORTAIL_URL", ""), "usager": usager, **contexte}
    creees: list[Notification] = []
    for contact in destinataires:
        if not getattr(contact, "courriel", "") or getattr(contact, "anonymise_le", None):
            continue
        creees.append(
            Notification.objects.create(
                modele=modele,
                destinataire=contact.courriel,
                contact=contact,
                usager=usager,
                sujet=rendre(modele.sujet, {**contexte_complet, "contact": contact}),
                corps=rendre(modele.corps, {**contexte_complet, "contact": contact}),
                objet_type=objet._meta.label_lower if objet is not None else "",
                objet_id=str(objet.pk) if objet is not None else "",
                groupe=groupe,
            )
        )
    for adresse in courriels:
        creees.append(
            Notification.objects.create(
                modele=modele,
                destinataire=adresse,
                sujet=rendre(modele.sujet, contexte_complet),
                corps=rendre(modele.corps, contexte_complet),
                objet_type=objet._meta.label_lower if objet is not None else "",
                objet_id=str(objet.pk) if objet is not None else "",
                groupe=groupe,
            )
        )
    identifiants = [n.pk for n in creees]
    if identifiants:
        transaction.on_commit(lambda: _programmer(identifiants))
    return creees


def notifier_groupe(code_modele: str, elements: Iterable[tuple[Any, dict[str, Any], models.Model | None]]) -> str:
    """Envoi groupé (COM-03) : un identifiant commun permet de suivre l'envoi dans le journal des envois."""
    groupe = uuid.uuid4().hex
    for usager, contexte, objet in elements:
        notifier(code_modele, contexte, usager=usager, objet=objet, groupe=groupe)
    return groupe


def _programmer(identifiants: list[int]) -> None:
    from .tasks import envoyer_notification

    for identifiant in identifiants:
        envoyer_notification.delay(identifiant)


def envoyer(notification: Notification) -> bool:
    """Envoi effectif par SMTP ; idempotent (une notification envoyée ne repart pas)."""
    notification = Notification.objects.select_for_update().get(pk=notification.pk)
    if notification.statut == "envoyee":
        return True
    notification.tentatives += 1
    try:
        message = EmailMessage(
            subject=notification.sujet,
            body=notification.corps,
            from_email=settings.DEFAULT_FROM_EMAIL,
            to=[notification.destinataire],
        )
        message.send(fail_silently=False)
    except Exception as erreur:
        notification.statut = "echec"
        notification.erreur = f"{type(erreur).__name__}: {erreur}"[:300]
        notification.save(update_fields=["statut", "tentatives", "erreur"])
        raise
    notification.statut = "envoyee"
    notification.envoyee_le = timezone.now()
    notification.erreur = ""
    notification.save(update_fields=["statut", "tentatives", "erreur", "envoyee_le"])
    return True
