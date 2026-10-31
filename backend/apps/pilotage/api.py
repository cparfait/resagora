"""API du pilotage : statistiques (STA-01 à STA-05) avec export tableur, tableau de bord « à traiter » et alertes
(DSH-01 à DSH-03, DSH-05, DSH-06), tableau de bord de la direction (DSH-04)."""

from __future__ import annotations

import io
from typing import Any

from django.http import HttpResponse
from django.utils import timezone
from drf_spectacular.utils import OpenApiParameter, extend_schema
from openpyxl import Workbook
from rest_framework import serializers
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.audit.services import journaliser
from apps.habilitations.authentification import agent_courant
from apps.noyau.exceptions import ErreurValidation
from apps.noyau.tableur import valeur_sure

from . import services


class PeriodeSerializer(serializers.Serializer):
    du = serializers.DateField()
    au = serializers.DateField()
    site = serializers.IntegerField(required=False, min_value=1)
    espace = serializers.IntegerField(required=False, min_value=1)
    export = serializers.ChoiceField(choices=["", "xlsx"], required=False, default="")

    def validate(self, donnees: dict[str, Any]) -> dict[str, Any]:
        if donnees["au"] < donnees["du"] or (donnees["au"] - donnees["du"]).days > 366:
            raise serializers.ValidationError("Période d'un an au plus.")
        return donnees


PARAMETRES_PERIODE = [OpenApiParameter(n, str) for n in ("du", "au", "site", "espace", "export")]


def _periode(request: Request) -> dict[str, Any]:
    entree = PeriodeSerializer(data=request.query_params)
    entree.is_valid(raise_exception=True)
    return dict(entree.validated_data)


def _classeur(feuilles: dict[str, list[list[Any]]], nom: str) -> HttpResponse:
    """Export tableur (STA-04) : une feuille par indicateur, textes neutralisés contre l'injection de formules."""
    classeur = Workbook()
    premiere = True
    for titre, lignes in feuilles.items():
        feuille = classeur.active if premiere else classeur.create_sheet()
        premiere = False
        feuille.title = titre[:31]
        for ligne in lignes:
            feuille.append([valeur_sure(v) for v in ligne])
    sortie = io.BytesIO()
    classeur.save(sortie)
    reponse = HttpResponse(sortie.getvalue(), content_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")
    reponse["Content-Disposition"] = f'attachment; filename="{nom}.xlsx"'
    return reponse


def _heures(minutes: float) -> float:
    return round(minutes / 60, 2)


class VueOccupation(APIView):
    """STA-01 : taux d'occupation par espace et par site sur la période."""

    actions_requises = {"get": "lire_statistiques"}

    @extend_schema(parameters=PARAMETRES_PERIODE, responses={200: dict})
    def get(self, request: Request) -> Response | HttpResponse:
        p = _periode(request)
        agent = agent_courant(request)
        lignes = services.occupation(
            services.espaces_du_perimetre(agent, "lire_statistiques", p.get("site"), p.get("espace")), p["du"], p["au"]
        )
        sites = services.occupation_par_site(lignes)
        if p["export"] == "xlsx":
            journaliser(
                "exporter_statistiques",
                objet_type="pilotage.occupation",
                apres={"du": str(p["du"]), "au": str(p["au"])},
                acteur=agent,
            )
            return _classeur(
                {
                    "Occupation par espace": [["Site", "Espace", "Famille", "Heures réservées", "Heures d'ouverture", "Taux (%)"]]
                    + [
                        [
                            ligne["site_nom"],
                            ligne["espace_nom"],
                            ligne["famille"],
                            _heures(ligne["minutes_reservees"]),
                            _heures(ligne["minutes_ouverture"]),
                            ligne["taux"] / 100,
                        ]
                        for ligne in lignes
                    ],
                    "Occupation par site": [["Site", "Heures réservées", "Heures d'ouverture", "Taux (%)"]]
                    + [
                        [s["site_nom"], _heures(s["minutes_reservees"]), _heures(s["minutes_ouverture"]), s["taux"] / 100]
                        for s in sites
                    ],
                },
                f"occupation-{p['du']:%Y%m%d}-{p['au']:%Y%m%d}",
            )
        return Response({"espaces": lignes, "sites": sites})


class VueRepartition(APIView):
    """STA-02 : heures par type d'usager, activité et famille d'espaces."""

    actions_requises = {"get": "lire_statistiques"}

    @extend_schema(parameters=PARAMETRES_PERIODE, responses={200: dict})
    def get(self, request: Request) -> Response | HttpResponse:
        p = _periode(request)
        agent = agent_courant(request)
        donnees = services.repartition(
            services.espaces_du_perimetre(agent, "lire_statistiques", p.get("site"), p.get("espace")), p["du"], p["au"]
        )
        if p["export"] == "xlsx":
            journaliser(
                "exporter_statistiques",
                objet_type="pilotage.repartition",
                apres={"du": str(p["du"]), "au": str(p["au"])},
                acteur=agent,
            )
            return _classeur(
                {
                    titre: [["Catégorie", "Heures", "Part (%)"]]
                    + [[p["libelle"], _heures(p["minutes"]), p["part"] / 100] for p in donnees[cle]]
                    for cle, titre in (
                        ("types_usager", "Types d'usager"),
                        ("activites", "Activités"),
                        ("familles", "Familles d'espaces"),
                    )
                },
                f"repartition-{p['du']:%Y%m%d}-{p['au']:%Y%m%d}",
            )
        return Response(donnees)


class VueRecettes(APIView):
    """STA-03 : recettes, gratuités et réductions, concours en nature valorisés."""

    actions_requises = {"get": "lire_finances"}

    @extend_schema(parameters=PARAMETRES_PERIODE, responses={200: dict})
    def get(self, request: Request) -> Response | HttpResponse:
        p = _periode(request)
        agent = agent_courant(request)
        donnees = services.recettes(agent, p["du"], p["au"], p.get("site"))
        if p["export"] == "xlsx":
            journaliser(
                "exporter_statistiques",
                objet_type="pilotage.recettes",
                apres={"du": str(p["du"]), "au": str(p["au"])},
                acteur=agent,
            )
            libelles = {
                "factures": "Factures émises (nombre)",
                "emis": "Facturé (€)",
                "avoirs": "Avoirs (€)",
                "net": "Recettes nettes (€)",
                "regle": "Réglé (€)",
                "reste_du": "Reste dû (€)",
                "reductions": "Réductions partielles accordées (€)",
                "gratuites": "Gratuités facturées à 0 € (€)",
                "concours_en_nature": "Concours en nature valorisés (€)",
            }
            return _classeur(
                {
                    "Recettes": [["Indicateur", "Valeur"]]
                    + [
                        [libelles[c], v if c == "factures" else v / 100]
                        for c, v in donnees.items()
                        if c in libelles and v is not None
                    ]
                },
                f"recettes-{p['du']:%Y%m%d}-{p['au']:%Y%m%d}",
            )
        return Response(donnees)


class VuePersonnel(APIView):
    """STA-05 : heures planifiées, réalisées, supplémentaires, de nuit, dimanches et fériés, astreintes."""

    actions_requises = {"get": "lire_personnel"}

    @extend_schema(parameters=PARAMETRES_PERIODE, responses={200: dict})
    def get(self, request: Request) -> Response | HttpResponse:
        p = _periode(request)
        agent = agent_courant(request)
        donnees = services.indicateurs_personnel(agent, p["du"], p["au"], p.get("site"))
        if p["export"] == "xlsx":
            journaliser(
                "exporter_statistiques",
                objet_type="pilotage.personnel",
                apres={"du": str(p["du"]), "au": str(p["au"])},
                acteur=agent,
            )
            libelles = {
                "agents": "Agents (nombre)",
                "planifiees": "Heures planifiées",
                "realisees": "Heures réalisées",
                "supplementaires": "Heures supplémentaires",
                "nuit": "Heures de nuit",
                "dimanches_feries": "Heures de dimanche et jours fériés",
                "astreintes": "Heures d'astreinte",
            }
            return _classeur(
                {
                    "Personnel": [["Indicateur", "Valeur"]]
                    + [[libelles[c], v if c == "agents" else _heures(v)] for c, v in donnees.items() if c in libelles]
                },
                f"personnel-{p['du']:%Y%m%d}-{p['au']:%Y%m%d}",
            )
        return Response(donnees)


class VueATraiter(APIView):
    """DSH-01 à DSH-03 : compteurs du jour et alertes, chacun avec le lien de sa liste filtrée (DSH-06)."""

    actions_requises = {"get": "lire_referentiel"}

    @extend_schema(responses={200: dict})
    def get(self, request: Request) -> Response:
        return Response({"compteurs": services.a_traiter(agent_courant(request)), "calcule_le": timezone.now()})


class VueDirection(APIView):
    """DSH-04 : indicateurs annuels de la direction comparés à l'année précédente, tendance mensuelle."""

    actions_requises = {"get": "lire_tableau_direction"}

    @extend_schema(parameters=[OpenApiParameter("annee", int)], responses={200: dict})
    def get(self, request: Request) -> Response:
        valeur = request.query_params.get("annee", "")
        annee = int(valeur) if valeur.isdecimal() else timezone.localdate().year
        if not 2000 <= annee <= timezone.localdate().year + 1:
            raise ErreurValidation("Année hors bornes.", code="annee_invalide")
        return Response(services.tableau_direction(agent_courant(request), annee))
