"""Envoi des notifications (COM-01, COM-03, COM-05) : rendu du modèle, enregistrement, envoi asynchrone.

Les messages sont rendus depuis des modèles éditables. Un lien à usage unique (confirmation,
réinitialisation, invitation) est passé dans `secrets` : il figure dans le message envoyé, mais le
texte conservé au journal des envois le masque ; le texte complet, chiffré, est effacé dès l'envoi.
L'envoi se fait par Celery après la validation de la transaction (`on_commit`). Un contact qui l'a
demandé reçoit aussi un SMS pour les modèles qui en prévoient un (préférences, COM-04).
"""

from __future__ import annotations

import logging
import re
import uuid
from collections.abc import Iterable
from typing import Any

from django.conf import settings
from django.core.mail import EmailMessage
from django.db import models, transaction
from django.template import Context, Engine
from django.utils import timezone

from apps.noyau.chiffrement import chiffrer, dechiffrer

from .models import ModeleMessage, Notification
from .sms import envoyer_sms

journal = logging.getLogger(__name__)
MOTEUR = Engine(autoescape=False, string_if_invalid="")
MASQUE = "[lien personnel masqué]"


def rendre(gabarit: str, contexte: dict[str, Any]) -> str:
    return MOTEUR.from_string(gabarit).render(Context(contexte)).strip()


CHAMPS_INTERDITS = re.compile(r"mot_de_passe|password|secret|chiffr|jeton|token|empreinte|totp|siret_|iban", re.IGNORECASE)
MODELES_EXCLUS = {"habilitations.utilisateur", "comptes.jetonportail", "comptes.jetonunique", "noyau.fichier"}
PROPRIETES = {"reservations.reservation": ("description",), "reservations.dossier": ("statut",)}


class Fiche(dict[str, Any]):
    """Vue en lecture seule d'un objet pour les gabarits : champs simples, jamais de secret (m8)."""

    def __str__(self) -> str:
        return str(self.get("texte", ""))


def _fiche(valeur: Any, profondeur: int = 0) -> Any:
    if not isinstance(valeur, models.Model):
        return valeur
    if valeur._meta.label_lower in MODELES_EXCLUS or profondeur >= 2:
        return str(valeur)
    fiche = Fiche(pk=valeur.pk, id=valeur.pk, texte=str(valeur))
    for champ in valeur._meta.concrete_fields:
        if CHAMPS_INTERDITS.search(champ.name):
            continue
        if champ.is_relation:
            fiche[champ.name] = _fiche(getattr(valeur, champ.name, None), profondeur + 1)
        else:
            fiche[champ.name] = getattr(valeur, champ.attname)
    for propriete in PROPRIETES.get(valeur._meta.label_lower, ()):
        fiche[propriete] = getattr(valeur, propriete)
    return fiche


def aplatir(contexte: dict[str, Any]) -> dict[str, Any]:
    """Les gabarits, éditables par l'administration, ne reçoivent que des fiches (pas d'objet ORM)."""
    return {cle: _fiche(valeur) for cle, valeur in contexte.items()}


def destinataires_usager(usager: Any) -> list[Any]:
    """Contacts à prévenir : le contact principal, sinon tous les contacts rattachés."""
    rattachements = list(usager.rattachements.select_related("contact").order_by("-principal"))
    principaux = [r.contact for r in rattachements if r.principal]
    return principaux or [r.contact for r in rattachements]


def _preferences(contact: Any) -> Any:
    return getattr(contact, "preferences", None) if getattr(contact, "pk", None) else None


def notifier(
    code_modele: str,
    contexte: dict[str, Any],
    *,
    contacts: Iterable[Any] = (),
    usager: Any = None,
    objet: models.Model | None = None,
    courriels: Iterable[str] = (),
    groupe: str = "",
    secrets: dict[str, str] | None = None,
    sms: bool = True,
) -> list[Notification]:
    """Crée une notification par destinataire et programme l'envoi après validation de la transaction."""
    modele = ModeleMessage.objects.filter(code=code_modele, actif=True).first()
    if modele is None:
        journal.error("Modèle de message introuvable ou inactif : %s", code_modele)
        return []
    destinataires = list(contacts) or (destinataires_usager(usager) if usager is not None else [])
    base = aplatir({"portail_url": getattr(settings, "PORTAIL_URL", ""), "usager": usager, **contexte})
    masques = dict.fromkeys(secrets or {}, MASQUE)
    lien_objet = {
        "objet_type": objet._meta.label_lower if objet is not None else "",
        "objet_id": str(objet.pk) if objet is not None else "",
        "groupe": groupe,
    }

    def creer(destinataire: str, contexte_local: dict[str, Any], **champs: Any) -> Notification:
        return Notification.objects.create(
            modele=modele,
            destinataire=destinataire,
            sujet=rendre(modele.sujet, contexte_local)[:250],
            corps=rendre(modele.corps, {**contexte_local, **masques}),
            corps_secret=chiffrer(rendre(modele.corps, {**contexte_local, **(secrets or {})})) if secrets else "",
            **lien_objet,
            **champs,
        )

    creees: list[Notification] = []
    for contact in destinataires:
        if not getattr(contact, "courriel", "") or getattr(contact, "anonymise_le", None):
            continue
        local = {**base, "contact": _fiche(contact)}
        creees.append(creer(contact.courriel, local, contact=contact, usager=usager))
        preferences = _preferences(contact)
        if sms and modele.sms and preferences is not None and preferences.sms and preferences.telephone_sms:
            creees.append(
                Notification.objects.create(
                    modele=modele,
                    canal="sms",
                    destinataire=preferences.telephone_sms,
                    contact=contact,
                    usager=usager,
                    sujet=rendre(modele.sujet, local)[:250],
                    corps=rendre(modele.sms, {**local, **masques})[:320],
                    **lien_objet,
                )
            )
    for adresse in courriels:
        creees.append(creer(adresse, base))
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


def _transmettre(notification: Notification) -> str:
    """Remet le message au serveur SMTP ou à l'opérateur SMS ; renvoie un motif si l'envoi est ignoré."""
    if notification.canal == "sms":
        resultat = envoyer_sms(notification.destinataire, notification.corps, reference=f"N{notification.pk}")
        return "" if resultat.envoye else resultat.motif
    corps = dechiffrer(notification.corps_secret) if notification.corps_secret else notification.corps
    EmailMessage(
        subject=notification.sujet, body=corps, from_email=settings.DEFAULT_FROM_EMAIL, to=[notification.destinataire]
    ).send(fail_silently=False)
    return ""


def envoyer(notification: Notification) -> bool:
    """Envoi effectif ; idempotent (une notification envoyée ne repart pas). L'échec est enregistré puis relevé."""
    echec: Exception | None = None
    with transaction.atomic():
        notification = Notification.objects.select_for_update().get(pk=notification.pk)
        if notification.statut in {"envoyee", "ignoree"}:
            return True
        notification.tentatives += 1
        try:
            motif = _transmettre(notification)
        except Exception as erreur:
            notification.statut = "echec"
            notification.erreur = f"{type(erreur).__name__}: {erreur}"[:300]
            notification.save(update_fields=["statut", "tentatives", "erreur"])
            echec = erreur
        else:
            notification.statut = "ignoree" if motif else "envoyee"
            notification.envoyee_le = None if motif else timezone.now()
            notification.erreur = motif[:300]
            notification.corps_secret = ""
            notification.save(update_fields=["statut", "tentatives", "erreur", "envoyee_le", "corps_secret"])
    if echec is not None:
        raise echec
    return True
