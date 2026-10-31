"""API de gestion des réservations : dossiers, réservations, séances, planning, campagnes (PLA-01 à PLA-12)."""

from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any

import django_filters
from django.db.models import Q, QuerySet
from django.utils import timezone
from drf_spectacular.utils import OpenApiParameter, extend_schema
from rest_framework import status
from rest_framework.decorators import action
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.audit.services import instantane, journaliser
from apps.habilitations.authentification import agent_courant
from apps.habilitations.services import exiger, peut, sites_autorises
from apps.noyau.api import VuePerimetre
from apps.noyau.exceptions import ErreurMetier, ErreurValidation

from .. import campagne as services_campagne
from .. import conditions as services_conditions
from .. import services
from ..models import Campagne, Dossier, ListeAttente, Occurrence, Reservation, TypeReservation, VueEnregistree
from ..recurrence import decrire
from . import serializers as s

LECTURE_ECRITURE = {"lecture": "lire_reservation", "ecriture": "creer_reservation"}


def _perimetre_dossiers(qs: QuerySet[Dossier], request: Request, action_requise: str) -> QuerySet[Dossier]:
    agent = agent_courant(request)
    if not peut(agent, action_requise):
        return qs.none()
    sites = sites_autorises(agent, action_requise)
    if sites is None:
        return qs
    return qs.filter(Q(reservations__espace__batiment__site__in=sites) | Q(reservations__isnull=True, cree_par=agent)).distinct()


class VueTypesReservation(VuePerimetre):
    queryset = TypeReservation.objects.all()
    serializer_class = s.TypeReservationSerializer
    actions_requises = {"lecture": "lire_reservation", "ecriture": "gerer_parametres"}
    pagination_class = None


class FiltreDossiers(django_filters.FilterSet):
    recherche = django_filters.CharFilter(method="filtrer_recherche")
    statut = django_filters.CharFilter(field_name="reservations__statut")
    site = django_filters.NumberFilter(field_name="reservations__espace__batiment__site")

    class Meta:
        model = Dossier
        fields = ["usager", "type_reservation", "saison", "campagne", "origine"]

    def filtrer_recherche(self, qs: QuerySet[Dossier], nom: str, valeur: str) -> QuerySet[Dossier]:
        valeur = valeur.strip()[:80]
        return (
            qs.filter(
                Q(numero__icontains=valeur) | Q(objet__unaccent__icontains=valeur) | Q(usager__nom__unaccent__icontains=valeur)
            )
            if valeur
            else qs
        )


class VueDossiers(VuePerimetre):
    queryset = Dossier.objects.select_related("usager", "type_reservation").prefetch_related(
        "reservations__espace__batiment__site"
    )
    serializer_class = s.DossierSerializer
    actions_requises = {
        **LECTURE_ECRITURE,
        "ajouter_reservation": "creer_reservation",
        "apercu": "creer_reservation",
        "attester": "valider_reservation",
    }
    filterset_class = FiltreDossiers
    http_method_names = ["get", "post", "patch", "head", "options"]

    def get_queryset(self) -> QuerySet[Dossier]:
        action_requise = "lire_reservation" if self.request.method in ("GET", "HEAD", "OPTIONS") else "creer_reservation"
        return _perimetre_dossiers(
            Dossier.objects.select_related("usager", "type_reservation").prefetch_related("reservations__espace__batiment__site"),
            self.request,
            action_requise,
        ).order_by("-cree_le")

    def get_serializer_context(self) -> dict[str, Any]:
        return {**super().get_serializer_context(), "liste": getattr(self, "action", "") == "list"}

    def perform_update(self, serializer: Any) -> None:
        serializer.instance = services.modifier_dossier(
            serializer.instance, acteur=agent_courant(self.request), **serializer.validated_data
        )

    @extend_schema(request=s.AttestationSerializer, responses=s.DossierSerializer)
    @action(detail=True, methods=["post"])
    def attester(self, request: Request, pk: str | None = None) -> Response:
        """RG-06 : constat manuel d'une condition (ex. chèque de caution remis au guichet), motivé et tracé."""
        donnees = s.AttestationSerializer(data=request.data)
        donnees.is_valid(raise_exception=True)
        dossier = services_conditions.attester(
            self.get_object(),
            donnees.validated_data["condition"],
            acteur=agent_courant(request),
            motif=donnees.validated_data["motif"],
        )
        return Response(s.DossierSerializer(dossier, context=self.get_serializer_context()).data)

    def perform_create(self, serializer: Any) -> None:
        donnees = serializer.validated_data
        dossier = services.creer_dossier(
            acteur=agent_courant(self.request),
            usager=donnees.pop("usager"),
            type_reservation=donnees.pop("type_reservation"),
            objet=donnees.pop("objet"),
            contact=donnees.pop("contact", None),
            **donnees,
        )
        serializer.instance = dossier

    @extend_schema(request=s.NouvelleReservationSerializer, responses=s.ReservationSerializer)
    @action(detail=True, methods=["post"], url_path="reservations")
    def ajouter_reservation(self, request: Request, pk: str | None = None) -> Response:
        dossier = self.get_object()
        donnees = s.NouvelleReservationSerializer(data=request.data)
        donnees.is_valid(raise_exception=True)
        reservation = services.ajouter_reservation(dossier, acteur=agent_courant(request), **donnees.validated_data)
        return Response(s.ReservationSerializer(reservation).data, status=status.HTTP_201_CREATED)

    @extend_schema(request=s.NouvelleReservationSerializer, responses=s.ApercuSerializer)
    @action(detail=False, methods=["post"])
    def apercu(self, request: Request) -> Response:
        """Séances générées et conflits d'un créneau, avant tout enregistrement (PLA-04, PLA-07)."""
        donnees = s.NouvelleReservationSerializer(data=request.data)
        donnees.is_valid(raise_exception=True)
        champs = {k: v for k, v in donnees.validated_data.items() if k not in {"forcer_horaires", "motif_forcage"}}
        exiger(agent_courant(request), "creer_reservation", champs["espace"])
        brouillon = Reservation(**champs)
        resultat = services.apercu(champs["espace"], brouillon)
        return Response(
            {
                "seances": [{"debut": d.isoformat(), "fin": f.isoformat()} for d, f in resultat.plages],
                "conflits": [c.en_dict() for c in resultat.conflits],
                "hors_horaires": [d.isoformat() for d in resultat.hors_horaires],
                "fermetures": [d.isoformat() for d in resultat.fermetures],
                "description": decrire(brouillon),
            }
        )


class VueReservations(VuePerimetre):
    queryset = Reservation.objects.select_related("dossier__usager", "espace__batiment__site")
    serializer_class = s.ReservationSerializer
    chemin_site = "espace__batiment__site"
    http_method_names = ["get", "post", "head", "options"]
    filterset_fields = ["dossier", "espace", "statut", "dossier__usager", "dossier__campagne"]
    actions_requises = {
        "lecture": "lire_reservation",
        "list": "lire_reservation",
        "retrieve": "lire_reservation",
        "instruire": "instruire_reservation",
        "option": "valider_reservation",
        "valider": "valider_reservation",
        "refuser": "valider_reservation",
        "confirmer": "confirmer_reservation",
        "annuler": "annuler_reservation",
        "cloturer": "cloturer_reservation",
        "modifier_serie": "valider_reservation",
        "priorite_municipale": "deplacer_priorite",
        "alternatives": "lire_reservation",
    }

    def create(self, request: Request, *args: Any, **kwargs: Any) -> Response:
        return Response({"code": "non_autorise", "message": "Ajoutez une réservation depuis son dossier."}, status=405)

    def _repondre(self, reservation: Reservation) -> Response:
        return Response(s.ReservationSerializer(Reservation.objects.get(pk=reservation.pk)).data)

    @extend_schema(request=None, responses=s.ReservationSerializer)
    @action(detail=True, methods=["post"])
    def instruire(self, request: Request, pk: str | None = None) -> Response:
        return self._repondre(services.instruire(self.get_object(), acteur=agent_courant(request)))

    @extend_schema(request=s.OptionSerializer, responses=s.ReservationSerializer)
    @action(detail=True, methods=["post"])
    def option(self, request: Request, pk: str | None = None) -> Response:
        donnees = s.OptionSerializer(data=request.data)
        donnees.is_valid(raise_exception=True)
        return self._repondre(
            services.mettre_en_option(self.get_object(), acteur=agent_courant(request), jours=donnees.validated_data.get("jours"))
        )

    @extend_schema(request=None, responses=s.ReservationSerializer)
    @action(detail=True, methods=["post"])
    def valider(self, request: Request, pk: str | None = None) -> Response:
        return self._repondre(services.valider(self.get_object(), acteur=agent_courant(request)))

    @extend_schema(request=s.RefusSerializer, responses=s.ReservationSerializer)
    @action(detail=True, methods=["post"])
    def refuser(self, request: Request, pk: str | None = None) -> Response:
        donnees = s.RefusSerializer(data=request.data)
        donnees.is_valid(raise_exception=True)
        return self._repondre(services.refuser(self.get_object(), acteur=agent_courant(request), **donnees.validated_data))

    @extend_schema(request=None, responses=s.ReservationSerializer)
    @action(detail=True, methods=["post"])
    def confirmer(self, request: Request, pk: str | None = None) -> Response:
        return self._repondre(services.confirmer(self.get_object(), acteur=agent_courant(request)))

    @extend_schema(request=s.AnnulationSerializer, responses=s.ReservationSerializer)
    @action(detail=True, methods=["post"])
    def annuler(self, request: Request, pk: str | None = None) -> Response:
        donnees = s.AnnulationSerializer(data=request.data)
        donnees.is_valid(raise_exception=True)
        return self._repondre(services.annuler(self.get_object(), acteur=agent_courant(request), **donnees.validated_data))

    @extend_schema(request=None, responses=s.ReservationSerializer)
    @action(detail=True, methods=["post"])
    def cloturer(self, request: Request, pk: str | None = None) -> Response:
        return self._repondre(services.cloturer(self.get_object(), acteur=agent_courant(request)))

    @extend_schema(request=s.ModificationSerieSerializer, responses=s.ReservationSerializer)
    @action(detail=True, methods=["post"], url_path="modifier-serie")
    def modifier_serie(self, request: Request, pk: str | None = None) -> Response:
        donnees = s.ModificationSerieSerializer(data=request.data)
        donnees.is_valid(raise_exception=True)
        return self._repondre(services.modifier_serie(self.get_object(), acteur=agent_courant(request), **donnees.validated_data))

    @extend_schema(request=s.PrioriteMunicipaleSerializer, responses=s.ReservationSerializer)
    @action(detail=True, methods=["post"], url_path="priorite-municipale")
    def priorite_municipale(self, request: Request, pk: str | None = None) -> Response:
        donnees = s.PrioriteMunicipaleSerializer(data=request.data)
        donnees.is_valid(raise_exception=True)
        deplacements = {int(k): (v["espace"], v["debut"], v["fin"]) for k, v in donnees.validated_data["deplacements"].items()}
        reservation = services.imposer_priorite_municipale(
            self.get_object(), acteur=agent_courant(request), motif=donnees.validated_data["motif"], deplacements=deplacements
        )
        return self._repondre(reservation)

    @extend_schema(responses=s.AlternativeSerializer(many=True))
    @action(detail=True, methods=["get"])
    def alternatives(self, request: Request, pk: str | None = None) -> Response:
        reservation = self.get_object()
        premiere = reservation.occurrences.exclude(statut="annulee").order_by("debut").first()
        if premiere is None:
            return Response([])
        return Response(services.alternatives(reservation.espace, premiere.debut, premiere.fin))


class FiltreOccurrences(django_filters.FilterSet):
    debut = django_filters.IsoDateTimeFilter(field_name="fin", lookup_expr="gt")
    fin = django_filters.IsoDateTimeFilter(field_name="debut", lookup_expr="lt")
    signalees = django_filters.BooleanFilter(method="filtrer_signalees")

    class Meta:
        model = Occurrence
        fields = ["reservation", "espace", "statut", "presence"]

    def filtrer_signalees(self, qs: QuerySet[Occurrence], nom: str, valeur: bool) -> QuerySet[Occurrence]:
        return qs.exclude(signalement="") if valeur else qs.filter(signalement="")


class VueOccurrences(VuePerimetre):
    queryset = Occurrence.objects.select_related("espace__batiment__site", "reservation__dossier__usager")
    serializer_class = s.OccurrenceSerializer
    chemin_site = "espace__batiment__site"
    http_method_names = ["get", "post", "head", "options"]
    filterset_class = FiltreOccurrences
    actions_requises = {
        "lecture": "lire_reservation",
        "list": "lire_reservation",
        "retrieve": "lire_reservation",
        "controle_deplacement": "lire_reservation",
        "deplacer": "valider_reservation",
        "modifier_suivantes": "valider_reservation",
        "annuler": "annuler_reservation",
        "presence": "cloturer_reservation",
    }

    def create(self, request: Request, *args: Any, **kwargs: Any) -> Response:
        return Response({"code": "non_autorise", "message": "Les séances naissent des réservations."}, status=405)

    @extend_schema(request=s.DeplacementSerializer, responses=s.ControleSerializer)
    @action(detail=True, methods=["post"], url_path="controle-deplacement")
    def controle_deplacement(self, request: Request, pk: str | None = None) -> Response:
        """PLA-02 : contrôle côté serveur avant validation visuelle du glisser-déposer."""
        occurrence = self.get_object()
        donnees = s.DeplacementSerializer(data=request.data)
        donnees.is_valid(raise_exception=True)
        espace, debut, fin = donnees.validated_data["espace"], donnees.validated_data["debut"], donnees.validated_data["fin"]
        exiger(agent_courant(request), "valider_reservation", espace)
        trouves = services.conflits(espace, debut, fin, exclure=[occurrence.pk])
        horaires = services.dans_les_horaires(espace, debut, fin)
        fermeture = services.fermetures_touchant(espace, debut, fin).exists()
        return Response(
            {
                "possible": not trouves and horaires and not fermeture,
                "hors_horaires": not horaires,
                "fermeture": fermeture,
                "conflits": [c.en_dict() for c in trouves],
                "alternatives": services.alternatives(espace, debut, fin) if trouves or fermeture else [],
            }
        )

    @extend_schema(request=s.DeplacementSerializer, responses=s.OccurrenceSerializer)
    @action(detail=True, methods=["post"])
    def deplacer(self, request: Request, pk: str | None = None) -> Response:
        donnees = s.DeplacementSerializer(data=request.data)
        donnees.is_valid(raise_exception=True)
        occurrence = services.deplacer_occurrence(self.get_object(), acteur=agent_courant(request), **donnees.validated_data)
        return Response(s.OccurrenceSerializer(occurrence).data)

    @extend_schema(request=s.ModificationSerieSerializer, responses=s.ReservationSerializer)
    @action(detail=True, methods=["post"], url_path="modifier-suivantes")
    def modifier_suivantes(self, request: Request, pk: str | None = None) -> Response:
        donnees = s.ModificationSerieSerializer(data=request.data)
        donnees.is_valid(raise_exception=True)
        reservation = services.modifier_suivantes(self.get_object(), acteur=agent_courant(request), **donnees.validated_data)
        return Response(s.ReservationSerializer(reservation).data)

    @extend_schema(request=s.AnnulationSerializer, responses=s.OccurrenceSerializer)
    @action(detail=True, methods=["post"])
    def annuler(self, request: Request, pk: str | None = None) -> Response:
        donnees = s.AnnulationSerializer(data=request.data)
        donnees.is_valid(raise_exception=True)
        occurrence = services.annuler_occurrence(self.get_object(), acteur=agent_courant(request), **donnees.validated_data)
        return Response(s.OccurrenceSerializer(occurrence).data)

    @extend_schema(request=s.PresenceSerializer, responses=s.OccurrenceSerializer)
    @action(detail=True, methods=["post"])
    def presence(self, request: Request, pk: str | None = None) -> Response:
        donnees = s.PresenceSerializer(data=request.data)
        donnees.is_valid(raise_exception=True)
        occurrence = services.saisir_presence(self.get_object(), acteur=agent_courant(request), **donnees.validated_data)
        return Response(s.OccurrenceSerializer(occurrence).data)


class VuePlanning(APIView):
    """PLA-01 : séances d'une période pour les vues jour, semaine, mois, chronologie, multi-sites et liste."""

    actions_requises = {"get": "lire_reservation"}
    MAX_JOURS = 62
    MAX_SEANCES = 5000

    @extend_schema(
        parameters=[OpenApiParameter(n, str) for n in ("debut", "fin", "site", "espace", "famille", "statut", "type_usager")],
        responses=s.SeancePlanningSerializer(many=True),
    )
    def get(self, request: Request) -> Response:
        try:
            debut = datetime.fromisoformat(request.query_params["debut"])
            fin = datetime.fromisoformat(request.query_params["fin"])
        except (KeyError, ValueError) as erreur:
            raise ErreurValidation("Indiquez debut et fin au format ISO 8601.", code="periode_invalide") from erreur
        debut = timezone.make_aware(debut) if timezone.is_naive(debut) else debut
        fin = timezone.make_aware(fin) if timezone.is_naive(fin) else fin
        if fin <= debut or fin - debut > timedelta(days=self.MAX_JOURS):
            raise ErreurValidation(f"Période invalide (au plus {self.MAX_JOURS} jours).", code="periode_invalide")
        agent = agent_courant(request)
        qs = Occurrence.objects.filter(debut__lt=fin, fin__gt=debut).exclude(statut__in=["refusee"])
        sites = sites_autorises(agent, "lire_reservation")
        if sites is not None:
            qs = qs.filter(espace__batiment__site__in=sites)
        p = request.query_params
        for parametre, chemin in (
            ("site", "espace__batiment__site_id"),
            ("espace", "espace_id"),
            ("famille", "espace__famille_id"),
        ):
            valeur = p.get(parametre, "")
            if valeur:
                if not valeur.isdigit():
                    raise ErreurValidation(f"Filtre « {parametre} » invalide.", code="filtre_invalide")
                qs = qs.filter(**{chemin: int(valeur)})
        if p.get("statut"):
            qs = qs.filter(statut__in=p["statut"].split(","))
        if p.get("type_usager"):
            qs = qs.filter(reservation__dossier__usager__type__in=p["type_usager"].split(","))
        if p.get("annulees") != "1":
            qs = qs.exclude(statut="annulee")
        lignes = list(
            qs.select_related("espace__batiment", "reservation__dossier__usager").order_by("debut")[: self.MAX_SEANCES + 1]
        )
        tronque = len(lignes) > self.MAX_SEANCES
        reponse = Response(
            [
                {
                    "id": o.pk,
                    "reservation": o.reservation_id,
                    "dossier": o.reservation.dossier_id,
                    "numero": o.reservation.dossier.numero,
                    "objet": o.reservation.dossier.objet,
                    "usager": o.reservation.dossier.usager.nom,
                    "type_usager": o.reservation.dossier.usager.type,
                    "espace": o.espace_id,
                    "espace_nom": o.espace.nom,
                    "site": o.espace.batiment.site_id,
                    "debut": o.debut.isoformat(),
                    "fin": o.fin.isoformat(),
                    "statut": o.statut,
                    "signalement": o.signalement,
                }
                for o in lignes[: self.MAX_SEANCES]
            ]
        )
        if tronque:
            reponse["X-Planning-Tronque"] = str(self.MAX_SEANCES)
        return reponse


class VueCampagnes(VuePerimetre):
    queryset = Campagne.objects.select_related("saison").prefetch_related("sites")
    serializer_class = s.CampagneSerializer
    actions_requises = {
        "lecture": "lire_reservation",
        "ecriture": "gerer_campagne",
        "statut": "gerer_campagne",
        "analyse": "lire_reservation",
        "attribution": "arbitrer_campagne",
    }

    def perform_destroy(self, instance: Any) -> None:
        if instance.statut != "preparation" or instance.dossiers.exists():
            raise ErreurMetier("Seule une campagne en préparation et sans demande peut être supprimée.", code="campagne_engagee")
        super().perform_destroy(instance)

    @extend_schema(request=s.StatutCampagneSerializer, responses=s.CampagneSerializer)
    @action(detail=True, methods=["post"])
    def statut(self, request: Request, pk: str | None = None) -> Response:
        donnees = s.StatutCampagneSerializer(data=request.data)
        donnees.is_valid(raise_exception=True)
        campagne = services_campagne.changer_statut(
            self.get_object(), donnees.validated_data["statut"], acteur=agent_courant(request)
        )
        return Response(s.CampagneSerializer(campagne).data)

    @extend_schema(responses={200: dict})
    @action(detail=True, methods=["get"])
    def analyse(self, request: Request, pk: str | None = None) -> Response:
        """Demandes concurrentes et proposition d'arbitrage RG-03."""
        groupes = services_campagne.analyser(self.get_object(), agent=agent_courant(request))
        return Response(
            [
                {
                    "espace": g.espace,
                    "creneau": g.creneau,
                    "candidats": [
                        c.__dict__ | {"depose_le": c.depose_le.isoformat() if c.depose_le else None} for c in g.candidats
                    ],
                }
                for g in groupes
            ]
        )

    @extend_schema(request=s.AttributionSerializer, responses={200: dict})
    @action(detail=True, methods=["post"])
    def attribution(self, request: Request, pk: str | None = None) -> Response:
        donnees = s.AttributionSerializer(data=request.data)
        donnees.is_valid(raise_exception=True)
        decisions = {int(k): v for k, v in donnees.validated_data["decisions"].items()}
        return Response(services_campagne.attribuer(self.get_object(), decisions, acteur=agent_courant(request)))


class VueListeAttente(VuePerimetre):
    queryset = ListeAttente.objects.select_related("usager", "espace__batiment")
    serializer_class = s.ListeAttenteSerializer
    chemin_site = "espace__batiment__site"
    actions_requises = LECTURE_ECRITURE
    http_method_names = ["get", "post", "delete", "head", "options"]
    filterset_fields = ["espace", "usager", "statut"]

    def perform_create(self, serializer: Any) -> None:
        d = serializer.validated_data
        serializer.instance = services.inscrire_liste_attente(
            acteur=agent_courant(self.request),
            espace=d["espace"],
            debut=d["debut"],
            fin=d["fin"],
            usager=d["usager"],
            contact=d.get("contact"),
        )


class VueVuesEnregistrees(VuePerimetre):
    """PLA-03 : vues du planning propres à chaque agent."""

    queryset = VueEnregistree.objects.none()
    serializer_class = s.VueEnregistreeSerializer
    actions_requises = {"lecture": "lire_reservation", "ecriture": "lire_reservation"}
    pagination_class = None

    def get_queryset(self) -> QuerySet[VueEnregistree]:
        if getattr(self, "swagger_fake_view", False):
            return VueEnregistree.objects.none()
        return VueEnregistree.objects.filter(agent=agent_courant(self.request))

    def perform_create(self, serializer: Any) -> None:
        agent = agent_courant(self.request)
        if serializer.validated_data.get("par_defaut"):
            VueEnregistree.objects.filter(agent=agent).update(par_defaut=False)
        vue = serializer.save(agent=agent)
        journaliser("creer_vue_planning", vue, apres=instantane(vue))

    def perform_update(self, serializer: Any) -> None:
        if serializer.validated_data.get("par_defaut"):
            VueEnregistree.objects.filter(agent=agent_courant(self.request)).update(par_defaut=False)
        serializer.save()
