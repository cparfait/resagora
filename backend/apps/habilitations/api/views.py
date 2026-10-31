"""Connexion des agents (SEC-02, SEC-03, SEC-06), profil et administration des droits (ADM-03, ADM-06)."""

from __future__ import annotations

from typing import Any

from django.contrib.auth import authenticate, login, logout
from django.db import transaction
from django.middleware.csrf import get_token
from drf_spectacular.utils import extend_schema
from rest_framework import status
from rest_framework.decorators import action
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.audit.services import journaliser
from apps.noyau.api import VuePerimetre
from apps.noyau.exceptions import ErreurValidation

from .. import totp
from ..actions import ACTIONS
from ..authentification import agent_courant
from ..models import GroupeAD, Habilitation, Perimetre, Role, Utilisateur
from ..permissions import CLE_SESSION_TOTP
from ..services import actions_par_perimetre, retirer
from .serializers import (
    CodeTotpSerializer,
    ConnexionSerializer,
    EnrolementSerializer,
    EtapeConnexionSerializer,
    GroupeADSerializer,
    HabilitationSerializer,
    MoiSerializer,
    PerimetreSerializer,
    RoleSerializer,
    UtilisateurSerializer,
)

CLE_SESSION_GRAINE = "graine_totp_en_attente"


def profil(request: Request, utilisateur: Utilisateur | None = None) -> dict[str, Any]:
    utilisateur = utilisateur or agent_courant(request)
    return {
        "id": utilisateur.pk,
        "identifiant": utilisateur.username,
        "nom_affiche": utilisateur.nom_affiche,
        "courriel": utilisateur.email,
        "double_authentification_exigee": utilisateur.exige_double_authentification(),
        "double_authentification_active": utilisateur.totp_actif,
        "double_authentification_validee": bool(request.session.get(CLE_SESSION_TOTP)),
        "habilitations": actions_par_perimetre(utilisateur),
    }


def etape_apres_mot_de_passe(utilisateur: Utilisateur) -> str:
    if not utilisateur.exige_double_authentification():
        return "connecte"
    return "code_totp" if utilisateur.totp_actif else "enrolement_totp"


class VueCsrf(APIView):
    authentication_classes: list[type] = []
    permission_classes: list[type] = []

    @extend_schema(responses={204: None})
    def get(self, request: Request) -> Response:
        get_token(request)
        return Response(status=status.HTTP_204_NO_CONTENT)


class VueConnexion(APIView):
    """Mot de passe AD ; la double authentification suit si le rôle l'exige. Messages identiques
    en cas d'identifiant inconnu ou de mot de passe faux (pas d'énumération de comptes)."""

    permission_classes: list[type] = []
    throttle_scope = "connexion"

    @extend_schema(request=ConnexionSerializer, responses=EtapeConnexionSerializer)
    def post(self, request: Request) -> Response:
        donnees = ConnexionSerializer(data=request.data)
        donnees.is_valid(raise_exception=True)
        utilisateur = authenticate(
            request._request, username=donnees.validated_data["identifiant"], password=donnees.validated_data["mot_de_passe"]
        )
        if utilisateur is None:
            journaliser(
                "connexion_echouee",
                objet_type="habilitations.utilisateur",
                apres={"identifiant": donnees.validated_data["identifiant"][:64]},
            )
            raise ErreurValidation("Identifiant ou mot de passe incorrect.", code="identifiants_invalides")
        login(request._request, utilisateur, backend="apps.habilitations.ldap.LdapBackend")
        request.session[CLE_SESSION_TOTP] = False
        etape = etape_apres_mot_de_passe(utilisateur)
        journaliser("connexion", utilisateur, acteur=utilisateur, apres={"etape": etape})
        corps: dict[str, Any] = {"etape": etape}
        if etape == "connecte":
            corps["utilisateur"] = profil(request, utilisateur)
        return Response(corps)


class VueDeconnexion(APIView):
    authentifie_seulement = True
    sans_double_authentification = True

    @extend_schema(request=None, responses={204: None})
    def post(self, request: Request) -> Response:
        journaliser("deconnexion", agent_courant(request), acteur=agent_courant(request))
        logout(request._request)
        return Response(status=status.HTTP_204_NO_CONTENT)


class VueTotp(APIView):
    """Saisie du code de l'application d'authentification après le mot de passe (SEC-03)."""

    authentifie_seulement = True
    sans_double_authentification = True
    throttle_scope = "connexion"

    @extend_schema(request=CodeTotpSerializer, responses=EtapeConnexionSerializer)
    def post(self, request: Request) -> Response:
        donnees = CodeTotpSerializer(data=request.data)
        donnees.is_valid(raise_exception=True)
        if not totp.verifier_utilisateur(agent_courant(request), donnees.validated_data["code"]):
            journaliser("totp_echoue", agent_courant(request), acteur=agent_courant(request))
            raise ErreurValidation("Code incorrect ou expiré.", code="code_invalide")
        request.session.cycle_key()
        request.session[CLE_SESSION_TOTP] = True
        journaliser("totp_valide", agent_courant(request), acteur=agent_courant(request))
        return Response({"etape": "connecte", "utilisateur": profil(request)})


class VueEnrolementTotp(APIView):
    authentifie_seulement = True
    sans_double_authentification = True
    throttle_scope = "connexion"

    @extend_schema(request=None, responses=EnrolementSerializer)
    def get(self, request: Request) -> Response:
        if agent_courant(request).totp_actif and not request.session.get(CLE_SESSION_TOTP):
            raise ErreurValidation("Validez d'abord votre code actuel pour changer d'appareil.", code="totp_deja_actif")
        graine = totp.nouvelle_graine()
        request.session[CLE_SESSION_GRAINE] = graine
        uri = totp.uri_enrolement(agent_courant(request), graine)
        return Response({"uri": uri, "qr_svg": totp.qr_svg(uri), "graine": graine})

    @extend_schema(request=CodeTotpSerializer, responses=EtapeConnexionSerializer)
    def post(self, request: Request) -> Response:
        donnees = CodeTotpSerializer(data=request.data)
        donnees.is_valid(raise_exception=True)
        graine = request.session.get(CLE_SESSION_GRAINE)
        if not graine or not totp.activer(agent_courant(request), graine, donnees.validated_data["code"]):
            raise ErreurValidation("Code incorrect. Vérifiez l'heure de votre téléphone et réessayez.", code="code_invalide")
        request.session.pop(CLE_SESSION_GRAINE, None)
        request.session.cycle_key()
        request.session[CLE_SESSION_TOTP] = True
        journaliser("totp_active", agent_courant(request), acteur=agent_courant(request))
        return Response({"etape": "connecte", "utilisateur": profil(request)})


class VueMoi(APIView):
    """Profil et actions autorisées par périmètre : l'interface masque, l'API refuse."""

    authentifie_seulement = True
    sans_double_authentification = True

    @extend_schema(responses=MoiSerializer)
    def get(self, request: Request) -> Response:
        return Response(profil(request))


class VueCatalogueActions(APIView):
    actions_requises = {"get": "administrer"}

    @extend_schema(responses={200: dict})
    def get(self, request: Request) -> Response:
        return Response(ACTIONS)


class VueRoles(VuePerimetre):
    queryset = Role.objects.all()
    serializer_class = RoleSerializer
    actions_requises = {"lecture": "administrer", "ecriture": "administrer"}


class VuePerimetres(VuePerimetre):
    queryset = Perimetre.objects.prefetch_related("sites")
    serializer_class = PerimetreSerializer
    actions_requises = {"lecture": "administrer", "ecriture": "administrer"}


class VueGroupesAD(VuePerimetre):
    queryset = GroupeAD.objects.select_related("role", "perimetre")
    serializer_class = GroupeADSerializer
    actions_requises = {"lecture": "administrer", "ecriture": "administrer"}


class VueHabilitations(VuePerimetre):
    queryset = Habilitation.objects.select_related("role", "perimetre", "utilisateur")
    serializer_class = HabilitationSerializer
    actions_requises = {"lecture": "administrer", "ecriture": "administrer"}
    filterset_fields = ["utilisateur", "role", "perimetre", "source"]

    def perform_destroy(self, instance: Habilitation) -> None:  # type: ignore[override]
        retirer(agent_courant(self.request), instance)


class VueUtilisateurs(VuePerimetre):
    queryset = Utilisateur.objects.prefetch_related("habilitations__role", "habilitations__perimetre")
    serializer_class = UtilisateurSerializer
    actions_requises = {"lecture": "administrer", "ecriture": "administrer"}
    http_method_names = ["get", "patch", "post", "head", "options"]
    filterset_fields = ["is_active", "source"]

    @extend_schema(request=None, responses={204: None})
    @action(detail=True, methods=["post"], url_path="reinitialiser-totp")
    def reinitialiser_totp(self, request: Request, pk: str | None = None) -> Response:
        utilisateur = self.get_object()
        with transaction.atomic():
            totp.reinitialiser(utilisateur)
            journaliser("reinitialiser_totp", utilisateur)
        return Response(status=status.HTTP_204_NO_CONTENT)
