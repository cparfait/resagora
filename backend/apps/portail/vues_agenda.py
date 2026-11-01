"""POR-05 : abonnement à l'agenda des séances d'une structure (lien iCal personnel, révocable).

Gestion du lien : contact connecté et rattaché à la structure. Lecture du flux : sans session (un logiciel
d'agenda ne se connecte pas), le jeton du lien en tient lieu ; même réponse 404 pour tout jeton non valable.
"""

from __future__ import annotations

from typing import Any

from django.http import HttpResponse
from drf_spectacular.utils import extend_schema
from rest_framework import status
from rest_framework.request import Request
from rest_framework.response import Response

from apps.usagers import agenda
from apps.usagers.models import AbonnementAgenda

from .authentification import contact_courant, usager_autorise
from .securite import VueContact, VuePublique


class JetonAgenda:
    """Convertisseur d'URL : jeton de `secrets.token_urlsafe(32)` (43 caractères base64url)."""

    regex = "[A-Za-z0-9_-]{43}"

    def to_python(self, valeur: str) -> str:
        return valeur

    def to_url(self, valeur: str) -> str:
        return valeur


def _etat(abonnement: AbonnementAgenda | None) -> dict[str, Any]:
    if abonnement is None:
        return {"actif": False, "cree_le": None, "expire_le": None, "dernier_acces": None}
    return {
        "actif": True,
        "cree_le": abonnement.cree_le,
        "expire_le": abonnement.expire_le,
        "dernier_acces": abonnement.dernier_acces,
    }


class VueAgendaUsager(VueContact):
    @extend_schema(responses={200: dict})
    def get(self, request: Request, pk: int) -> Response:
        contact = contact_courant(request)
        usager = usager_autorise(contact, pk)
        return Response(_etat(agenda.abonnement_actif(usager, contact)))

    @extend_schema(request=None, responses={201: dict})
    def post(self, request: Request, pk: int) -> Response:
        contact = contact_courant(request)
        usager = usager_autorise(contact, pk)
        jeton, abonnement = agenda.emettre(usager, contact)
        # Le lien n'est montré qu'ici : seule son empreinte est conservée.
        return Response({**_etat(abonnement), "url": agenda.lien(jeton)}, status=status.HTTP_201_CREATED)

    @extend_schema(responses={204: None})
    def delete(self, request: Request, pk: int) -> Response:
        contact = contact_courant(request)
        agenda.revoquer(usager_autorise(contact, pk), contact)
        return Response(status=status.HTTP_204_NO_CONTENT)


class VueAgendaIcal(VuePublique):
    throttle_scope = "agenda"

    @extend_schema(responses={(200, "text/calendar"): bytes})
    def get(self, request: Request, jeton: str) -> HttpResponse:
        reponse = HttpResponse(agenda.flux(jeton), content_type="text/calendar; charset=utf-8")
        reponse["Content-Disposition"] = 'inline; filename="seances.ics"'
        reponse["Cache-Control"] = "private, no-store"
        return reponse
