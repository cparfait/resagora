"""Authentification des usagers sur le canal portail (SEC-04).

La façade DMZ détient le jeton de session API et le transmet dans `Authorization: Portail <jeton>` ;
le navigateur ne le voit jamais. Le jeton est lié au compte, donc au contact : un contact ne voit que
les usagers auxquels il est rattaché et leurs dossiers.
"""

from __future__ import annotations

from typing import Any

from django.db.models import QuerySet
from rest_framework.authentication import BaseAuthentication
from rest_framework.exceptions import NotAuthenticated
from rest_framework.permissions import BasePermission
from rest_framework.request import Request

from apps.comptes.models import CompteUsager, JetonPortail
from apps.comptes.services import compte_du_jeton
from apps.noyau.exceptions import ErreurMetier
from apps.usagers.models import Contact, Rattachement, Usager

PREFIXE = "Portail "


class AuthentificationPortail(BaseAuthentication):
    def authenticate(self, request: Request) -> tuple[CompteUsager, JetonPortail] | None:
        entete = request.headers.get("Authorization", "")
        if not entete.startswith(PREFIXE):
            return None
        valeur = entete.removeprefix(PREFIXE).strip()
        if not valeur or len(valeur) > 200:
            return None
        trouve = compte_du_jeton(valeur)
        if trouve is None:
            raise NotAuthenticated("Votre session a expiré. Reconnectez-vous.")
        return trouve

    def authenticate_header(self, request: Request) -> str:
        return 'Portail realm="portail"'


class ContactConnecte(BasePermission):
    def has_permission(self, request: Request, view: Any) -> bool:
        return isinstance(request.user, CompteUsager)


def compte_courant(request: Request) -> CompteUsager:
    if not isinstance(request.user, CompteUsager):
        raise NotAuthenticated()
    return request.user


def contact_courant(request: Request) -> Contact:
    return compte_courant(request).contact


def usagers_du_contact(contact: Contact) -> QuerySet[Usager]:
    return Usager.objects.filter(rattachements__contact=contact).exclude(statut="anonymise").distinct()


class Introuvable(ErreurMetier):
    """Objet absent ou appartenant à un autre usager : même réponse (pas d'énumération, R2-27)."""

    statut_http = 404

    def __init__(self) -> None:
        super().__init__("Élément introuvable.", code="introuvable")


def usager_autorise(contact: Contact, identifiant: Any, *, valide: bool = False) -> Usager:
    usager = usagers_du_contact(contact).filter(pk=identifiant).first() if str(identifiant).isdigit() else None
    if usager is None:
        raise Introuvable()
    if valide and usager.statut != "valide":
        raise ErreurMetier(
            "Ce compte de structure n'est pas encore validé par la Ville.",
            code="usager_non_valide",
            details={"statut": usager.statut},
        )
    return usager


def rattachement(contact: Contact, usager: Usager) -> Rattachement:
    lien = Rattachement.objects.filter(contact=contact, usager=usager).first()
    if lien is None:
        raise Introuvable()
    return lien
