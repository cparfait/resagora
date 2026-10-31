"""Matériel sur le portail (MAT-02, POR-04) : matériel proposé sur le site d'un espace, demande de prêt jointe à la
demande de réservation (étape 2) ou ajoutée ensuite à un dossier. Une demande en ligne est « demandée » et validée par
un agent ; la disponibilité est contrôlée dès la demande. Aucun montant ni stock détaillé n'est exposé."""

from __future__ import annotations

from typing import Any

from django.db import transaction
from drf_spectacular.utils import OpenApiParameter, extend_schema
from rest_framework import serializers, status
from rest_framework.request import Request
from rest_framework.response import Response

from apps.materiel import services as materiel
from apps.materiel.models import Materiel, ReservationMateriel, Stock
from apps.noyau.exceptions import ErreurMetier, ErreurValidation
from apps.reservations.models import Dossier, Reservation
from apps.usagers.models import Contact

from .authentification import contact_courant
from .securite import VueContact

#: Plafond affiché et demandable en ligne : le stock exact n'est pas exposé.
PLAFOND_DEMANDE = 200

STATUTS_PRETS = {
    "demandee": "Demandé, en attente de la Ville",
    "validee": "Accordé",
    "sortie": "Remis",
    "rendue": "Rendu",
    "refusee": "Refusé",
    "annulee": "Annulé",
}


def stocks_proposes(site_id: int) -> list[Stock]:
    """Matériel mobile ou consommable proposé en ligne et rangé sur le site (hors équipements fixes des espaces)."""
    return list(
        Stock.objects.filter(
            site_id=site_id,
            espace__isnull=True,
            materiel__actif=True,
            materiel__reservable=True,
            materiel__propose_portail=True,
        )
        .exclude(materiel__nature="fixe")
        .select_related("materiel")
        .order_by("materiel__libelle")
    )


def representation_prets(dossier: Dossier) -> list[dict[str, Any]]:
    return [
        {
            "id": p.pk,
            "materiel": p.stock.materiel.libelle,
            "unite": p.stock.materiel.unite,
            "quantite": p.quantite,
            "debut": p.debut,
            "fin": p.fin,
            "reservation": p.reservation_id,
            "statut": p.statut,
            "statut_libelle": STATUTS_PRETS.get(p.statut, p.statut),
            "motif": p.motif if p.statut in ("refusee", "annulee") else "",
        }
        for p in ReservationMateriel.objects.filter(dossier=dossier).select_related("stock__materiel").order_by("debut")
    ]


class MaterielDemandeSerializer(serializers.Serializer):
    materiel = serializers.IntegerField(min_value=1)
    quantite = serializers.IntegerField(min_value=1, max_value=9999)


def valider_materiel_demande(lignes: list[dict[str, Any]]) -> list[dict[str, int]]:
    """Brouillon (étape 2) : seuls des articles proposés en ligne, une ligne par article."""
    proposes = set(Materiel.objects.filter(actif=True, reservable=True, propose_portail=True).values_list("pk", flat=True))
    vus: set[int] = set()
    resultat = []
    for ligne in lignes:
        if ligne["materiel"] not in proposes or ligne["materiel"] in vus:
            raise ErreurValidation("Matériel non proposé en ligne ou en double.", code="materiel_invalide")
        vus.add(ligne["materiel"])
        resultat.append({"materiel": int(ligne["materiel"]), "quantite": int(ligne["quantite"])})
    return resultat


def _stock_du_site(materiel_id: int, reservation: Reservation) -> Stock:
    stock = next((s for s in stocks_proposes(reservation.espace.batiment.site_id) if s.materiel_id == materiel_id), None)
    if stock is None:
        raise ErreurMetier("Ce matériel n'est pas proposé sur le site de cet équipement.", code="materiel_autre_site")
    return stock


def materialiser_brouillon(dossier: Dossier, contact: Contact) -> list[str]:
    """À l'envoi de la demande : chaque matériel demandé l'est pour chaque séance des réservations dont le site le
    propose ; les refus sont lisibles (« 15 disponibles »)."""
    erreurs = []
    for ligne in dossier.brouillon_materiel or []:
        servies = 0
        for reservation in dossier.reservations.select_related("espace__batiment"):
            stock = next(
                (s for s in stocks_proposes(reservation.espace.batiment.site_id) if s.materiel_id == ligne["materiel"]), None
            )
            if stock is None:
                continue
            try:
                with transaction.atomic():
                    materiel.reserver_pour_reservation(reservation, stock, ligne["quantite"], acteur=contact, origine="portail")
                    servies += 1
            except ErreurMetier as erreur:
                erreurs.append(f"Matériel : {erreur.message}")
        if not servies and not erreurs:
            erreurs.append("Matériel : il n'est pas proposé sur le site des équipements demandés.")
    return erreurs


class VueMaterielPortail(VueContact):
    """Catalogue du matériel proposé sur le site d'un espace (quantité en état, sans détail du stock)."""

    @extend_schema(parameters=[OpenApiParameter("espace", int)], responses={200: dict})
    def get(self, request: Request) -> Response:
        from .catalogue import espaces_publics

        identifiant = request.query_params.get("espace", "")
        espace = (
            espaces_publics().select_related("batiment").filter(pk=int(identifiant)).first() if identifiant.isdecimal() else None
        )
        if espace is None:
            raise ErreurValidation("Indiquez l'équipement.", code="espace_requis")
        return Response(
            [
                {
                    "id": s.materiel_id,
                    "libelle": s.materiel.libelle,
                    "description": s.materiel.description,
                    "unite": s.materiel.unite,
                    "maximum": min(s.en_etat, PLAFOND_DEMANDE),
                }
                for s in stocks_proposes(espace.batiment.site_id)
                if s.en_etat > 0
            ]
        )


class PretPortailSerializer(serializers.Serializer):
    reservation = serializers.IntegerField(min_value=1)
    materiel = serializers.IntegerField(min_value=1)
    quantite = serializers.IntegerField(min_value=1, max_value=9999)
    commentaire = serializers.CharField(max_length=300, required=False, allow_blank=True, default="")


class VueMaterielDossier(VueContact):
    """Demande de matériel sur un dossier envoyé, pour une de ses réservations en cours."""

    throttle_scope = "depot"

    @extend_schema(request=PretPortailSerializer, responses={201: dict})
    def post(self, request: Request, pk: int) -> Response:
        from .vues_dossiers import dossier_autorise

        contact = contact_courant(request)
        dossier = dossier_autorise(contact, pk)
        if dossier.brouillon:
            raise ErreurMetier("Indiquez le matériel à l'étape 2 de la demande.", code="dossier_brouillon")
        if dossier.usager.statut != "valide":
            raise ErreurMetier("Votre structure ne peut pas déposer de demande : contactez le service.", code="usager_non_valide")
        entree = PretPortailSerializer(data=request.data)
        entree.is_valid(raise_exception=True)
        d = entree.validated_data
        reservation = (
            dossier.reservations.exclude(statut__in=["annulee", "refusee", "realisee", "cloturee"])
            .select_related("espace__batiment")
            .filter(pk=d["reservation"])
            .first()
        )
        if reservation is None:
            raise ErreurValidation("Choisissez une réservation en cours du dossier.", code="reservation_invalide")
        stock = _stock_du_site(d["materiel"], reservation)
        if d["quantite"] > PLAFOND_DEMANDE:
            raise ErreurValidation(f"{PLAFOND_DEMANDE} au plus par demande.", code="quantite_invalide")
        materiel.reserver_pour_reservation(
            reservation, stock, d["quantite"], acteur=contact, origine="portail", commentaire=d["commentaire"]
        )
        return Response({"materiel": representation_prets(dossier)}, status=status.HTTP_201_CREATED)
