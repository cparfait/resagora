"""Portail sans compte : disponibilités anonymisées (POR-02) et déclaration d'accessibilité (POR-09)."""

from __future__ import annotations

from datetime import date, datetime, time, timedelta
from typing import Any

from drf_spectacular.utils import OpenApiParameter, extend_schema
from rest_framework.request import Request
from rest_framework.response import Response

from apps.noyau.exceptions import ErreurValidation
from apps.noyau.parametres import parametre
from apps.referentiel.models import Fermeture, HoraireOuverture
from apps.reservations.models import Occurrence
from apps.reservations.recurrence import PARIS

from .catalogue import espaces_publics
from .securite import VuePublique

MAX_JOURS = 31


def _horaires_du_jour(espace_id: int, jour: date, vacances: bool) -> list[dict[str, str]]:
    from apps.referentiel.models import Saison

    du_jour = HoraireOuverture.objects.filter(espace_id=espace_id, jour_semaine=jour.weekday())
    saison = Saison.objects.filter(debut__lte=jour, fin__gte=jour).first()
    propres = du_jour.filter(saison=saison) if saison else du_jour.none()
    retenus = propres if propres.exists() else du_jour.filter(saison__isnull=True)
    if vacances:
        retenus = retenus.filter(pendant_vacances=True)
    return [{"debut": h.debut.strftime("%H:%M"), "fin": h.fin.strftime("%H:%M")} for h in retenus.order_by("debut")]


class VueDisponibilites(VuePublique):
    """Occupations d'un espace sur une période, sans aucun nom ni objet : « occupé », « demandé », « fermé »."""

    @extend_schema(
        parameters=[OpenApiParameter("espace", int), OpenApiParameter("debut", str), OpenApiParameter("jours", int)],
        responses={200: dict},
    )
    def get(self, request: Request) -> Response:
        from apps.referentiel.calendrier import est_ferie, est_vacances

        p = request.query_params
        identifiant = p.get("espace", "")
        espace = espaces_publics().filter(pk=int(identifiant)).first() if identifiant.isdecimal() else None
        if espace is None:
            raise ErreurValidation("Choisissez un espace du catalogue.", code="espace_invalide")
        try:
            debut = date.fromisoformat(p.get("debut", "")) if p.get("debut") else date.today()
            jours = int(p.get("jours", "7"))
        except ValueError as erreur:
            raise ErreurValidation("Période invalide (date au format AAAA-MM-JJ).", code="periode_invalide") from erreur
        if not 1 <= jours <= MAX_JOURS:
            raise ErreurValidation(f"Période de 1 à {MAX_JOURS} jours.", code="periode_invalide")
        fin = debut + timedelta(days=jours)
        instant_debut = datetime.combine(debut, time.min, tzinfo=PARIS)
        instant_fin = datetime.combine(fin, time.min, tzinfo=PARIS)
        lies = espace.ids_lies()
        occupations = (
            Occurrence.objects.filter(espace_id__in=lies, debut__lt=instant_fin, fin__gt=instant_debut)
            .exclude(statut__in=["annulee", "refusee"])
            .values_list("debut", "fin", "statut")
        )
        fermetures = Fermeture.objects.filter(
            espace_id__in=lies, debut__lt=instant_fin, fin__gt=instant_debut
        ) | Fermeture.objects.filter(
            site_id=espace.batiment.site_id, espace__isnull=True, debut__lt=instant_fin, fin__gt=instant_debut
        )
        plages: list[dict[str, Any]] = [
            {
                "debut": d.astimezone(PARIS).isoformat(),
                "fin": f.astimezone(PARIS).isoformat(),
                "etat": "demande" if s in {"demande", "en_instruction", "option"} else "occupe",
            }
            for d, f, s in occupations
        ]
        plages += [
            {"debut": f.debut.astimezone(PARIS).isoformat(), "fin": f.fin.astimezone(PARIS).isoformat(), "etat": "ferme"}
            for f in fermetures
        ]
        jours_detail = []
        for decalage in range(jours):
            jour = debut + timedelta(days=decalage)
            vacances = est_vacances(jour)
            jours_detail.append(
                {
                    "jour": jour.isoformat(),
                    "vacances": vacances,
                    "ferie": est_ferie(jour),
                    "horaires": _horaires_du_jour(espace.pk, jour, vacances),
                }
            )
        return Response(
            {
                "espace": espace.pk,
                "espace_nom": espace.nom,
                "debut": debut.isoformat(),
                "jours": jours_detail,
                "plages": sorted(plages, key=lambda x: x["debut"]),
            }
        )


class VueAccessibilite(VuePublique):
    """POR-09 : éléments variables des pages réglementaires (déclaration d'accessibilité, durées de conservation)."""

    @extend_schema(responses={200: dict})
    def get(self, request: Request) -> Response:
        return Response(
            {
                "etat": parametre("accessibilite.etat"),
                "taux": parametre("accessibilite.taux"),
                "date_audit": parametre("accessibilite.date_audit"),
                "auditeur": parametre("accessibilite.auditeur"),
                "non_conformites": parametre("accessibilite.non_conformites"),
                "contact": parametre("accessibilite.contact"),
                "date_declaration": parametre("accessibilite.date_declaration"),
                "referentiel": "RGAA 4.1.2",
                "conservation": {
                    "inactivite_mois": parametre("rgpd.conservation_mois_inactivite"),
                    "pieces_expirees_mois": parametre("rgpd.conservation_mois_pieces_expirees"),
                    "service": parametre("ville.service"),
                    "courriel": parametre("ville.courriel"),
                },
            }
        )
