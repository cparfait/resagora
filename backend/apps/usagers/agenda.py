"""POR-05 : agenda des séances d'une structure, en iCalendar, pour s'y abonner depuis Outlook, Google Agenda…

Le lien porte un jeton aléatoire (256 bits) qui remplace l'authentification : il n'est montré qu'une fois, seule
son empreinte HMAC est conservée. Un contact a au plus un abonnement actif par structure ; il le révoque quand il
veut, il expire au bout d'un an. Il est révoqué quand le contact quitte la structure, quand son compte est suspendu ou
fermé, quand la structure est suspendue ou anonymisée ; à la lecture, ces conditions sont de nouveau contrôlées.

Le flux ne contient que les séances de la structure : espace, lieu, objet, numéro de dossier. Correspondance des
statuts : validée, confirmée, réalisée, clôturée → ferme ; demande, en instruction, option → « Provisoire » ;
annulée, refusée → « Annulé », « Refusé » (le logiciel d'agenda barre ou retire l'événement). Le libellé est aussi
porté par le titre, car tous les agendas n'affichent pas le statut iCalendar.
"""

from __future__ import annotations

import logging
import secrets
from datetime import timedelta
from typing import Any

from django.conf import settings
from django.db import transaction
from django.utils import timezone

from apps.audit.services import journaliser
from apps.noyau import ical
from apps.noyau.chiffrement import empreinte_hmac
from apps.noyau.exceptions import ErreurMetier

from .models import AbonnementAgenda, Contact, Rattachement, Usager

DUREE = timedelta(days=365)
PASSE = timedelta(days=30)
AVENIR = timedelta(days=400)
MAX_SEANCES = 2000
PROVISOIRES = {"demande", "en_instruction", "option"}
LIBELLES = {"annulee": "Annulé", "refusee": "Refusé", **dict.fromkeys(PROVISOIRES, "Provisoire")}
STRUCTURES_ACTIVES = {"en_attente", "valide"}

journal = logging.getLogger(__name__)


class AbonnementIntrouvable(ErreurMetier):
    """Jeton inconnu, expiré, révoqué ou contact détaché : même réponse dans tous les cas."""

    statut_http = 404

    def __init__(self) -> None:
        super().__init__("Élément introuvable.", code="introuvable")


def lien(jeton: str) -> str:
    return f"{settings.PORTAIL_URL.rstrip('/')}/api/portail/agenda/{jeton}.ics"


def abonnement_actif(usager: Usager, contact: Contact) -> AbonnementAgenda | None:
    return AbonnementAgenda.objects.filter(
        usager=usager, contact=contact, revoque_le__isnull=True, expire_le__gt=timezone.now()
    ).first()


@transaction.atomic
def emettre(usager: Usager, contact: Contact) -> tuple[str, AbonnementAgenda]:
    """Nouveau lien : l'éventuel lien précédent du contact pour cette structure est révoqué."""
    maintenant = timezone.now()
    # Verrou sur le rattachement : deux demandes simultanées sont traitées l'une après l'autre.
    Rattachement.objects.select_for_update().filter(usager=usager, contact=contact).first()
    AbonnementAgenda.objects.filter(usager=usager, contact=contact, revoque_le__isnull=True).update(revoque_le=maintenant)
    jeton = secrets.token_urlsafe(32)
    abonnement = AbonnementAgenda.objects.create(
        usager=usager, contact=contact, empreinte=empreinte_hmac(jeton), expire_le=maintenant + DUREE
    )
    journaliser("emettre_abonnement_agenda", abonnement, apres={"usager": usager.pk}, acteur=contact)
    return jeton, abonnement


@transaction.atomic
def revoquer(usager: Usager, contact: Contact) -> int:
    nombre = AbonnementAgenda.objects.filter(usager=usager, contact=contact, revoque_le__isnull=True).update(
        revoque_le=timezone.now()
    )
    journaliser("revoquer_abonnement_agenda", usager, apres={"revoques": nombre}, acteur=contact)
    return nombre


def revoquer_abonnements(*, usager: Usager | None = None, contact: Contact | None = None, acteur: Any, motif: str) -> int:
    """Révocation d'office (contact détaché, compte suspendu ou fermé, structure suspendue ou anonymisée)."""
    abonnements = AbonnementAgenda.objects.filter(revoque_le__isnull=True)
    if usager is not None:
        abonnements = abonnements.filter(usager=usager)
    if contact is not None:
        abonnements = abonnements.filter(contact=contact)
    nombre = abonnements.update(revoque_le=timezone.now())
    if nombre:
        objet = usager if usager is not None else contact
        journaliser("revoquer_abonnement_agenda", objet, apres={"revoques": nombre, "motif": motif}, acteur=acteur)
    return nombre


def flux(jeton: str) -> bytes:
    from apps.reservations.models import STATUTS_ACTIFS, STATUTS_BLOQUANTS, Occurrence

    maintenant = timezone.now()
    abonnement = (
        AbonnementAgenda.objects.select_related("usager", "contact")
        .filter(
            empreinte=empreinte_hmac(jeton or ""),
            revoque_le__isnull=True,
            expire_le__gt=maintenant,
            usager__statut__in=STRUCTURES_ACTIVES,
            contact__compte__statut="actif",
        )
        .first()
    )
    if abonnement is None or not Rattachement.objects.filter(usager=abonnement.usager, contact=abonnement.contact).exists():
        raise AbonnementIntrouvable()
    AbonnementAgenda.objects.filter(pk=abonnement.pk).update(dernier_acces=maintenant)
    seances = (
        Occurrence.objects.filter(
            reservation__dossier__usager=abonnement.usager,
            debut__gte=maintenant - PASSE,
            debut__lte=maintenant + AVENIR,
            statut__in=[*STATUTS_ACTIFS, *STATUTS_BLOQUANTS, "annulee", "refusee"],
        )
        .select_related("espace__batiment__site", "reservation__dossier")
        .order_by("debut")[: MAX_SEANCES + 1]
    )
    if len(seances) > MAX_SEANCES:
        journal.warning("Agenda de l'usager %s tronqué à %s séances", abonnement.usager_id, MAX_SEANCES)
    evenements = []
    for o in seances[:MAX_SEANCES]:
        site = o.espace.batiment.site
        adresse = ", ".join(filter(None, [site.adresse, " ".join(filter(None, [site.code_postal, site.commune]))]))
        description = f"Dossier {o.reservation.dossier.numero}" + (f"\nAccès : {site.acces}" if site.acces else "")
        libelle = LIBELLES.get(o.statut)
        resume = f"{o.espace.nom} — {o.reservation.dossier.objet}"
        evenements.append(
            ical.Evenement(
                uid=f"seance-{o.pk}@equipements.chatillon",
                debut=o.debut,
                fin=o.fin,
                resume=(f"{libelle} — {resume}" if libelle else resume)[:200],
                lieu=", ".join(filter(None, [o.espace.nom, site.nom, adresse])),
                description=description,
                annule=o.statut in {"annulee", "refusee"},
                provisoire=o.statut in PROVISOIRES,
            )
        )
    return ical.calendrier(
        f"Séances — {abonnement.usager.nom}",
        evenements,
        description="Réservations auprès de la Ville de Châtillon",
    )
