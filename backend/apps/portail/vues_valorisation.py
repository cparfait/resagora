"""Portail : attestations annuelles de valorisation des avantages en nature (VAL-04), pour les structures du contact."""

from __future__ import annotations

from django.http import FileResponse
from drf_spectacular.utils import extend_schema
from rest_framework.request import Request
from rest_framework.response import Response

from apps.audit.services import journaliser
from apps.noyau import fichiers
from apps.noyau.montants import euros
from apps.valorisation.models import Valorisation

from .authentification import Introuvable, contact_courant, usagers_du_contact
from .securite import VueContact


def _attestations(request: Request):  # type: ignore[no-untyped-def]
    contact = contact_courant(request)
    return contact, (
        Valorisation.objects.filter(
            usager__in=usagers_du_contact(contact), actuelle=True, document__isnull=False, deposee_le__isnull=False
        )
        .select_related("exercice", "usager", "document")
        .order_by("-exercice__annee")
    )


class VueAttestationsPortail(VueContact):
    @extend_schema(responses={200: dict})
    def get(self, request: Request) -> Response:
        _contact, attestations = _attestations(request)
        return Response(
            [
                {
                    "id": v.pk,
                    "exercice": v.exercice.annee,
                    "usager": v.usager_id,
                    "usager_nom": v.usager.nom,
                    "montant": v.total,
                    "montant_texte": euros(v.total),
                    "deposee_le": v.deposee_le,
                    "numero": v.document.numero if v.document else "",
                }
                for v in attestations
            ]
        )


class VueFichierAttestation(VueContact):
    """Téléchargement contrôlé : l'attestation d'une autre structure renvoie 404."""

    @extend_schema(responses={(200, "application/pdf"): bytes})
    def get(self, request: Request, pk: int) -> FileResponse:
        contact, attestations = _attestations(request)
        trouvee = attestations.filter(pk=pk).first()
        if trouvee is None or trouvee.document is None:
            raise Introuvable()
        journaliser("telecharger_attestation_portail", trouvee, acteur=contact)
        return fichiers.reponse_telechargement(trouvee.document.fichier_signe or trouvee.document.fichier)
