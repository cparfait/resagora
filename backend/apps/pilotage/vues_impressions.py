"""Éditions et envois programmés (IMP-01, IMP-03, IMP-04) ; droits rôle × périmètre sur l'espace ou le site."""

from __future__ import annotations

import re
from datetime import date, timedelta
from typing import Any

from django.db import transaction
from django.http import HttpResponse
from django.utils import timezone
from drf_spectacular.utils import OpenApiParameter, extend_schema
from rest_framework import serializers
from rest_framework.request import Request
from rest_framework.routers import SimpleRouter
from rest_framework.views import APIView

from apps.audit.services import instantane, journaliser
from apps.habilitations.authentification import agent_courant
from apps.noyau.api import VuePerimetre
from apps.noyau.exceptions import ErreurValidation
from apps.referentiel.models import Espace, Site

from . import impressions
from .models import EnvoiProgramme


def _date(valeur: str, defaut: date) -> date:
    try:
        return date.fromisoformat(valeur) if valeur else defaut
    except ValueError as erreur:
        raise ErreurValidation("Date au format AAAA-MM-JJ.", code="date_invalide") from erreur


def _pdf(contenu: bytes, nom: str) -> HttpResponse:
    reponse = HttpResponse(contenu, content_type="application/pdf")
    reponse["Content-Disposition"] = f'attachment; filename="{nom}.pdf"'
    return reponse


class VuePlanningPdf(APIView):
    """IMP-01 : planning d'un espace ou d'un site, A4 ou A3."""

    actions_requises = {"get": "lire_reservation"}

    @extend_schema(
        parameters=[OpenApiParameter(n, str) for n in ("site", "espace", "du", "au", "papier")],
        responses={(200, "application/pdf"): bytes},
    )
    def get(self, request: Request) -> HttpResponse:
        p = request.query_params
        site = Site.objects.filter(pk=int(p["site"])).first() if p.get("site", "").isdecimal() else None
        espace = (
            Espace.objects.select_related("batiment__site").filter(pk=int(p["espace"])).first()
            if p.get("espace", "").isdecimal()
            else None
        )
        aujourd_hui = timezone.localdate()
        lundi = aujourd_hui - timedelta(days=aujourd_hui.weekday())
        du = _date(p.get("du", ""), lundi)
        au = _date(p.get("au", ""), du + timedelta(days=6))
        papier = p.get("papier", "A4")
        contenu = impressions.imprimer_planning(
            acteur=agent_courant(request), site=site, espace=espace, du=du, au=au, format_papier=papier
        )
        return _pdf(contenu, f"planning-{du:%Y%m%d}")


class VueFeuilleDeSalle(APIView):
    """IMP-03 : feuille de la semaine à afficher en salle, avec QR code vers la page de l'équipement."""

    actions_requises = {"get": "lire_reservation"}

    @extend_schema(
        parameters=[OpenApiParameter("espace", int), OpenApiParameter("jour", str)], responses={(200, "application/pdf"): bytes}
    )
    def get(self, request: Request) -> HttpResponse:
        p = request.query_params
        espace = (
            Espace.objects.select_related("batiment__site").filter(pk=int(p["espace"])).first()
            if p.get("espace", "").isdecimal()
            else None
        )
        if espace is None:
            raise ErreurValidation("Choisissez l'espace.", code="espace_requis")
        jour = _date(p.get("jour", ""), timezone.localdate())
        return _pdf(
            impressions.feuille_de_salle(acteur=agent_courant(request), espace=espace, jour=jour),
            f"feuille-{espace.pk}-{jour:%Y%m%d}",
        )


class EnvoiSerializer(serializers.ModelSerializer):
    cible = serializers.SerializerMethodField()
    destinataires = serializers.ListField(child=serializers.EmailField(), max_length=30, required=False)
    destinataires_texte = serializers.CharField(
        write_only=True, required=False, max_length=3000, help_text="Une adresse par ligne (saisie du formulaire)."
    )

    class Meta:
        model = EnvoiProgramme
        fields = [
            "id",
            "libelle",
            "site",
            "espace",
            "cible",
            "destinataires",
            "destinataires_texte",
            "jour_semaine",
            "heure",
            "format_papier",
            "actif",
            "prochain_envoi_le",
            "dernier_envoi_le",
            "echecs",
            "suspendu_motif",
        ]
        read_only_fields = ["prochain_envoi_le", "dernier_envoi_le", "echecs", "suspendu_motif"]

    def get_cible(self, envoi: EnvoiProgramme) -> str:
        return str(envoi.espace or envoi.site or "")

    def validate(self, donnees: dict[str, Any]) -> dict[str, Any]:
        site = donnees.get("site", getattr(self.instance, "site", None))
        espace = donnees.get("espace", getattr(self.instance, "espace", None))
        if (site is None) == (espace is None):
            raise serializers.ValidationError("Choisissez un site ou un espace.")
        texte = donnees.pop("destinataires_texte", None)
        if texte is not None:
            adresses = [a.strip() for a in re.split(r"[\s,;]+", texte) if a.strip()]
            champ = serializers.EmailField()
            for adresse in adresses:
                try:
                    champ.run_validation(adresse)
                except serializers.ValidationError as erreur:
                    raise serializers.ValidationError({"destinataires_texte": f"Adresse invalide : {adresse}"}) from erreur
            if len(adresses) > 30:
                raise serializers.ValidationError({"destinataires_texte": "30 adresses au plus."})
            donnees["destinataires"] = list(dict.fromkeys(a.lower() for a in adresses))
        destinataires = donnees.get("destinataires", getattr(self.instance, "destinataires", []))
        if not destinataires:
            raise serializers.ValidationError({"destinataires": "Au moins une adresse."})
        domaines = impressions.domaines_autorises()
        hors = [a for a in destinataires if a.rsplit("@", 1)[-1].lower() not in domaines]
        if hors:
            raise serializers.ValidationError(
                {
                    "destinataires_texte" if "destinataires_texte" in self.initial_data else "destinataires": (
                        f"Adresse hors des domaines de la Ville ({', '.join(sorted(domaines))}) : {hors[0]}"
                    )
                }
            )
        if "destinataires" in donnees:
            donnees["destinataires"] = [a.lower() for a in donnees["destinataires"]]
        return donnees


class VueEnvois(VuePerimetre):
    """IMP-04 : envois hebdomadaires programmés du planning."""

    queryset = EnvoiProgramme.objects.select_related("site", "espace__batiment__site")
    serializer_class = EnvoiSerializer
    chemin_site = "site"
    actions_requises = {"lecture": "lire_reservation", "ecriture": "instruire_reservation"}
    http_method_names = ["get", "post", "patch", "delete", "head", "options"]

    def get_queryset(self) -> Any:
        from django.db.models import Q

        from apps.habilitations.services import sites_autorises

        qs = EnvoiProgramme.objects.select_related("site", "espace__batiment__site")
        sites = sites_autorises(agent_courant(self.request), "lire_reservation")
        return qs if sites is None else qs.filter(Q(site__in=sites) | Q(espace__batiment__site__in=sites))

    @transaction.atomic
    def perform_create(self, serializer: Any) -> None:
        self._verifier_lies(serializer)
        envoi = serializer.save(cree_par=agent_courant(self.request))
        self._verifier_objet(envoi)
        impressions.programmer(envoi, acteur=agent_courant(self.request))
        journaliser("creer_envoiprogramme", envoi, apres=instantane(envoi))

    @transaction.atomic
    def perform_update(self, serializer: Any) -> None:
        self._verifier_lies(serializer)
        avant = instantane(serializer.instance)
        # Qui modifie un envoi en devient responsable : ses droits sont revérifiés à chaque envoi.
        envoi = serializer.save(cree_par=agent_courant(self.request), echecs=0, suspendu_motif="")
        self._verifier_objet(envoi)
        impressions.programmer(envoi, acteur=agent_courant(self.request))
        journaliser("modifier_envoiprogramme", envoi, avant=avant, apres=instantane(envoi))


routeur = SimpleRouter(trailing_slash=False)
routeur.register("pilotage/envois-planning", VueEnvois, basename="envois-planning")
