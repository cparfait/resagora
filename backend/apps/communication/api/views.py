"""API de gestion : modèles de messages (ADM-04), journal des envois (COM-04), messagerie par dossier
(COM-02), envois groupés (COM-03)."""

from __future__ import annotations

from datetime import datetime
from typing import Any

import django_filters
from django.conf import settings
from django.db import transaction
from django.db.models import Q, QuerySet
from django.template import TemplateSyntaxError
from django.utils import timezone
from drf_spectacular.utils import extend_schema
from rest_framework import serializers, status
from rest_framework.decorators import action
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.audit.services import journaliser
from apps.habilitations.authentification import agent_courant
from apps.habilitations.services import exiger, peut, sites_autorises
from apps.noyau.api import VuePerimetre
from apps.noyau.exceptions import ErreurValidation
from apps.reservations.models import Dossier, Occurrence
from apps.usagers.models import Usager

from ..models import Message, ModeleMessage, Notification
from ..services import MOTEUR, notifier, notifier_groupe


class ModeleMessageSerializer(serializers.ModelSerializer):
    class Meta:
        model = ModeleMessage
        fields = ["id", "code", "libelle", "sujet", "corps", "sms", "actif", "modifie_le"]
        read_only_fields = ["code", "modifie_le"]

    def _gabarit(self, valeur: str) -> str:
        try:
            MOTEUR.from_string(valeur)
        except TemplateSyntaxError as erreur:
            raise serializers.ValidationError(f"Gabarit invalide : {erreur}") from erreur
        return valeur

    def validate_sujet(self, valeur: str) -> str:
        return self._gabarit(valeur)

    def validate_corps(self, valeur: str) -> str:
        return self._gabarit(valeur)

    def validate_sms(self, valeur: str) -> str:
        return self._gabarit(valeur)


class VueModelesMessages(VuePerimetre):
    """ADM-04 : les modèles livrés se modifient (texte, activation) mais ne se créent ni ne se suppriment :
    chaque code est appelé par une règle de gestion."""

    queryset = ModeleMessage.objects.all()
    serializer_class = ModeleMessageSerializer
    actions_requises = {"lecture": "lire_message", "ecriture": "gerer_modele", "apercu": "lire_message"}
    http_method_names = ["get", "patch", "post", "head", "options"]
    pagination_class = None

    def create(self, request: Request, *args: Any, **kwargs: Any) -> Response:
        return Response({"code": "non_autorise", "message": "Les modèles sont livrés avec l'application."}, status=405)

    @extend_schema(request=None, responses={200: dict})
    @action(detail=True, methods=["post"])
    def apercu(self, request: Request, pk: str | None = None) -> Response:
        """Rendu avec des valeurs d'exemple, pour relire un modèle avant de l'enregistrer."""
        from ..services import rendre

        modele = self.get_object()
        exemple = {
            "contact": {"prenom": "Camille", "nom": "Exemple"},
            "usager": {"nom": "Association exemple"},
            "dossier": {"numero": "D2026-00001", "objet": "Entraînements", "pk": 1},
            "reservation": {"espace": {"nom": "Gymnase"}, "description": "tous les mardis de 18 h à 20 h"},
            "portail_url": settings.PORTAIL_URL,
            "lien": f"{settings.PORTAIL_URL}/exemple",
        }
        return Response(
            {"sujet": rendre(modele.sujet, exemple), "corps": rendre(modele.corps, exemple), "sms": rendre(modele.sms, exemple)}
        )


class NotificationSerializer(serializers.ModelSerializer):
    modele_libelle = serializers.CharField(source="modele.libelle", read_only=True, default="")

    class Meta:
        model = Notification
        fields = [
            "id",
            "canal",
            "modele",
            "modele_libelle",
            "destinataire",
            "sujet",
            "corps",
            "objet_type",
            "objet_id",
            "groupe",
            "statut",
            "tentatives",
            "erreur",
            "cree_le",
            "envoyee_le",
        ]
        read_only_fields = fields


class FiltreNotifications(django_filters.FilterSet):
    recherche = django_filters.CharFilter(method="filtrer")
    depuis = django_filters.IsoDateTimeFilter(field_name="cree_le", lookup_expr="gte")

    class Meta:
        model = Notification
        fields = ["statut", "canal", "groupe", "modele", "objet_type", "objet_id", "usager"]

    def filtrer(self, qs: QuerySet[Notification], nom: str, valeur: str) -> QuerySet[Notification]:
        valeur = valeur.strip()[:80]
        return qs.filter(Q(destinataire__icontains=valeur) | Q(sujet__icontains=valeur)) if valeur else qs


class VueJournalEnvois(VuePerimetre):
    """COM-04 : journal des envois ; réémission d'un envoi en échec."""

    queryset = Notification.objects.select_related("modele").order_by("-cree_le")
    serializer_class = NotificationSerializer
    actions_requises = {"lecture": "lire_message", "ecriture": "envoyer_message", "renvoyer": "envoyer_message"}
    http_method_names = ["get", "post", "head", "options"]
    filterset_class = FiltreNotifications

    def create(self, request: Request, *args: Any, **kwargs: Any) -> Response:
        return Response({"code": "non_autorise", "message": "Les envois naissent des règles de gestion."}, status=405)

    @extend_schema(request=None, responses=NotificationSerializer)
    @action(detail=True, methods=["post"])
    def renvoyer(self, request: Request, pk: str | None = None) -> Response:
        from ..tasks import envoyer_notification

        notification = self.get_object()
        if notification.statut != "echec":
            raise ErreurValidation("Seul un envoi en échec peut être renvoyé.", code="statut_envoi")
        Notification.objects.filter(pk=notification.pk).update(statut="a_envoyer", erreur="")
        journaliser("renvoyer_notification", notification, acteur=agent_courant(request))
        transaction.on_commit(lambda: envoyer_notification.delay(notification.pk))
        notification.refresh_from_db()
        return Response(NotificationSerializer(notification).data)


# --- Messagerie par dossier ---------------------------------------------------------------------------


class MessageSerializer(serializers.ModelSerializer):
    auteur = serializers.SerializerMethodField()
    de_la_ville = serializers.BooleanField(read_only=True)

    class Meta:
        model = Message
        fields = ["id", "dossier", "auteur", "de_la_ville", "corps", "cree_le", "lu_par_ville_le", "lu_par_usager_le"]
        read_only_fields = ["auteur", "de_la_ville", "cree_le", "lu_par_ville_le", "lu_par_usager_le"]

    def get_auteur(self, message: Message) -> str:
        return str(message.auteur_agent or message.auteur_contact or "")


def _dossiers_lisibles(request: Request, action_requise: str) -> QuerySet[Dossier]:
    agent = agent_courant(request)
    if not peut(agent, action_requise):
        return Dossier.objects.none()
    sites = sites_autorises(agent, action_requise)
    qs = Dossier.objects.all()
    if sites is not None:
        qs = qs.filter(
            Q(reservations__espace__batiment__site__in=sites) | Q(reservations__isnull=True, cree_par=agent)
        ).distinct()
    return qs


class VueMessages(VuePerimetre):
    """COM-02 : fil de messages d'un dossier, filtré par le périmètre des dossiers."""

    queryset = Message.objects.select_related("auteur_agent", "auteur_contact", "dossier")
    serializer_class = MessageSerializer
    actions_requises = {"lecture": "lire_message", "ecriture": "envoyer_message", "non_lus": "lire_message"}
    http_method_names = ["get", "post", "head", "options"]
    filterset_fields = ["dossier"]

    def get_queryset(self) -> QuerySet[Message]:
        if getattr(self, "swagger_fake_view", False):
            return Message.objects.none()
        lecture = self.request.method in ("GET", "HEAD", "OPTIONS")
        dossiers = _dossiers_lisibles(self.request, "lire_message" if lecture else "envoyer_message")
        return self.queryset.filter(dossier__in=dossiers).order_by("cree_le")

    def list(self, request: Request, *args: Any, **kwargs: Any) -> Response:
        reponse = super().list(request, *args, **kwargs)
        dossier = request.query_params.get("dossier", "")
        if dossier.isdigit():
            self.get_queryset().filter(
                dossier_id=int(dossier), auteur_contact__isnull=False, lu_par_ville_le__isnull=True
            ).update(lu_par_ville_le=timezone.now())
        return reponse

    def perform_create(self, serializer: Any) -> None:
        agent = agent_courant(self.request)
        dossier = serializer.validated_data["dossier"]
        if not _dossiers_lisibles(self.request, "envoyer_message").filter(pk=dossier.pk).exists():
            exiger(agent, "envoyer_message", dossier)
        with transaction.atomic():
            message = serializer.save(auteur_agent=agent)
            journaliser("ecrire_message", message, apres={"dossier": dossier.numero}, acteur=agent)
            notifier(
                "message_ville",
                {"dossier": dossier},
                contacts=[dossier.contact] if dossier.contact_id else [],
                usager=dossier.usager,
                objet=message,
            )

    @extend_schema(responses={200: dict})
    @action(detail=False, methods=["get"], url_path="non-lus")
    def non_lus(self, request: Request) -> Response:
        """Dossiers ayant des messages d'usagers non lus (tableau de bord, COM-02)."""
        qs = self.get_queryset().filter(auteur_contact__isnull=False, lu_par_ville_le__isnull=True)
        par_dossier: dict[int, dict[str, Any]] = {}
        for m in qs.select_related("dossier__usager"):
            ligne = par_dossier.setdefault(
                m.dossier_id, {"dossier": m.dossier_id, "numero": m.dossier.numero, "usager": m.dossier.usager.nom, "nombre": 0}
            )
            ligne["nombre"] += 1
        return Response(list(par_dossier.values()))


# --- Envois groupés (COM-03) -----------------------------------------------------------------------------


class EnvoiGroupeSerializer(serializers.Serializer):
    titre = serializers.CharField(max_length=150)
    texte = serializers.CharField(max_length=4000)
    usagers = serializers.ListField(child=serializers.IntegerField(min_value=1), required=False, default=list, max_length=500)
    espace = serializers.IntegerField(min_value=1, required=False)
    debut = serializers.DateTimeField(required=False)
    fin = serializers.DateTimeField(required=False)
    sms = serializers.BooleanField(default=False)

    def validate(self, donnees: dict[str, Any]) -> dict[str, Any]:
        if not donnees.get("usagers") and not donnees.get("espace"):
            raise serializers.ValidationError("Choisissez des usagers ou un espace et une période.")
        if donnees.get("espace") and not (donnees.get("debut") and donnees.get("fin")):
            raise serializers.ValidationError("Indiquez la période d'occupation de l'espace.")
        return donnees


class VueEnvoiGroupe(APIView):
    """COM-03 : information à un ensemble d'usagers (occupants d'un espace sur une période, ou liste choisie)."""

    actions_requises = {"post": "notifier_groupe"}

    @extend_schema(request=EnvoiGroupeSerializer, responses={201: dict})
    def post(self, request: Request) -> Response:
        agent = agent_courant(request)
        entree = EnvoiGroupeSerializer(data=request.data)
        entree.is_valid(raise_exception=True)
        d = entree.validated_data
        usagers: dict[int, Usager] = {}
        if d.get("espace"):
            from apps.referentiel.models import Espace

            espace = Espace.objects.filter(pk=d["espace"]).first()
            if espace is None:
                raise ErreurValidation("Espace inconnu.", code="espace_invalide")
            exiger(agent, "notifier_groupe", espace)
            debut: datetime = d["debut"]
            fin: datetime = d["fin"]
            occupations = Occurrence.objects.filter(
                espace_id__in=espace.ids_lies(), debut__lt=fin, fin__gt=debut, statut__in=["validee", "confirmee", "option"]
            ).select_related("reservation__dossier__usager")
            for o in occupations:
                usagers[o.reservation.dossier.usager_id] = o.reservation.dossier.usager
        for usager in Usager.objects.filter(pk__in=d.get("usagers", [])).exclude(statut="anonymise"):
            usagers[usager.pk] = usager
        if not usagers:
            raise ErreurValidation("Aucun usager concerné.", code="aucun_destinataire")
        with transaction.atomic():
            groupe = notifier_groupe(
                "information_generale",
                [(u, {"titre": d["titre"], "texte": d["texte"]}, None) for u in usagers.values()],
                sms=d["sms"],
            )
            journaliser(
                "envoi_groupe",
                objet_type="communication.notification",
                objet_id=groupe,
                apres={"titre": d["titre"], "usagers": len(usagers)},
                acteur=agent,
            )
        return Response({"groupe": groupe, "usagers": len(usagers)}, status=status.HTTP_201_CREATED)
