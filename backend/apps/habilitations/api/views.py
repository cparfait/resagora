"""Connexion des agents (SEC-02, SEC-03, SEC-06), profil et administration des droits (ADM-03, ADM-06)."""

from __future__ import annotations

import logging
from typing import Any

from django.contrib.auth import authenticate, login, logout
from django.db import transaction
from django.middleware.csrf import get_token
from drf_spectacular.utils import extend_schema
from rest_framework import status
from rest_framework.authentication import SessionAuthentication
from rest_framework.decorators import action
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.audit.services import journaliser
from apps.noyau.api import VuePerimetre
from apps.noyau.chiffrement import empreinte_hmac
from apps.noyau.exceptions import ErreurValidation

from .. import totp
from ..actions import ACTIONS
from ..authentification import agent_courant
from ..models import GroupeAD, Habilitation, Perimetre, Role, Utilisateur
from ..permissions import CLE_SESSION_TOTP
from ..services import actions_par_perimetre, retirer, verifier_incompatibilites
from .serializers import (
    CodeTotpSerializer,
    ConnexionSerializer,
    EnrolementSerializer,
    EtapeConnexionSerializer,
    GroupeADSerializer,
    HabilitationSerializer,
    JetonEnrolementSerializer,
    JetonReinitialisationSerializer,
    MoiSerializer,
    PerimetreSerializer,
    RoleSerializer,
    UtilisateurSerializer,
)

CLE_SESSION_GRAINE = "graine_totp_en_attente"
CLE_SESSION_ENROLEMENT_AUTORISE = "enrolement_totp_autorise"
journal = logging.getLogger(__name__)


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
    if utilisateur.totp_actif:
        return "code_totp"
    return "jeton_enrolement" if utilisateur.totp_reinitialise else "enrolement_totp"


class VueCsrf(APIView):
    authentication_classes: list[type] = []
    permission_classes: list[type] = []

    @extend_schema(responses={204: None})
    def get(self, request: Request) -> Response:
        get_token(request)
        return Response(status=status.HTTP_204_NO_CONTENT)


def exiger_csrf(request: Request) -> None:
    """Le CSRF s'applique aussi à la connexion (protection contre la « connexion forcée »)."""
    SessionAuthentication().enforce_csrf(request)


def refus_verrouillage(request: Request, utilisateur: Utilisateur) -> Response:
    secondes = totp.secondes_verrou(utilisateur)
    logout(request._request)
    minutes = max(1, (secondes + 59) // 60)
    return Response(
        {"code": "compte_verrouille", "message": f"Trop de codes erronés. Réessayez dans {minutes} minute(s)."},
        status=status.HTTP_403_FORBIDDEN,
    )


class VueConnexion(APIView):
    """Mot de passe AD ; la double authentification suit si le rôle l'exige. Messages identiques
    en cas d'identifiant inconnu ou de mot de passe faux (pas d'énumération de comptes)."""

    permission_classes: list[type] = []
    throttle_scope = "connexion"

    @extend_schema(request=ConnexionSerializer, responses=EtapeConnexionSerializer)
    def post(self, request: Request) -> Response:
        exiger_csrf(request)
        donnees = ConnexionSerializer(data=request.data)
        donnees.is_valid(raise_exception=True)
        identifiant = donnees.validated_data["identifiant"]
        utilisateur = authenticate(request._request, username=identifiant, password=donnees.validated_data["mot_de_passe"])
        if utilisateur is None:
            # Seule l'empreinte de la saisie est conservée : un mot de passe tapé par erreur dans ce champ
            # ne doit pas rester lisible dans un journal immuable.
            journaliser(
                "connexion_echouee",
                objet_type="habilitations.utilisateur",
                apres={"identifiant_empreinte": empreinte_hmac(identifiant.strip().lower())[:16]},
            )
            raise ErreurValidation("Identifiant ou mot de passe incorrect.", code="identifiants_invalides")
        if totp.secondes_verrou(utilisateur):
            return refus_verrouillage(request, utilisateur)
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
        utilisateur = agent_courant(request)
        if totp.secondes_verrou(utilisateur):
            return refus_verrouillage(request, utilisateur)
        donnees = CodeTotpSerializer(data=request.data)
        donnees.is_valid(raise_exception=True)
        if not totp.verifier_utilisateur(utilisateur, donnees.validated_data["code"]):
            journaliser("totp_echoue", utilisateur, acteur=utilisateur)
            if totp.enregistrer_echec(utilisateur):
                journaliser("totp_verrouille", utilisateur, acteur=utilisateur)
                journal.error("Double authentification verrouillée après échecs répétés : agent %s", utilisateur.pk)
                return refus_verrouillage(request, utilisateur)
            raise ErreurValidation("Code incorrect ou expiré.", code="code_invalide")
        totp.reinitialiser_echecs(utilisateur)
        request.session.cycle_key()
        request.session[CLE_SESSION_TOTP] = True
        journaliser("totp_valide", utilisateur, acteur=utilisateur)
        return Response({"etape": "connecte", "utilisateur": profil(request)})


class VueJetonEnrolement(APIView):
    """Après une réinitialisation, l'agent saisit le code à usage unique remis par l'administrateur."""

    authentifie_seulement = True
    sans_double_authentification = True
    throttle_scope = "connexion"

    @extend_schema(request=JetonEnrolementSerializer, responses=EtapeConnexionSerializer)
    def post(self, request: Request) -> Response:
        utilisateur = agent_courant(request)
        if totp.secondes_verrou(utilisateur):
            return refus_verrouillage(request, utilisateur)
        donnees = JetonEnrolementSerializer(data=request.data)
        donnees.is_valid(raise_exception=True)
        if not totp.verifier_jeton_enrolement(utilisateur, donnees.validated_data["jeton"]):
            journaliser("jeton_enrolement_refuse", utilisateur, acteur=utilisateur)
            if totp.enregistrer_echec(utilisateur):
                return refus_verrouillage(request, utilisateur)
            raise ErreurValidation(
                "Code de réactivation incorrect ou expiré. Demandez-en un nouveau à l'administrateur.", code="jeton_invalide"
            )
        request.session[CLE_SESSION_ENROLEMENT_AUTORISE] = True
        return Response({"etape": "enrolement_totp"})


class VueEnrolementTotp(APIView):
    authentifie_seulement = True
    sans_double_authentification = True
    throttle_scope = "connexion"

    def _autoriser(self, request: Request, utilisateur: Utilisateur) -> None:
        if utilisateur.totp_actif and not request.session.get(CLE_SESSION_TOTP):
            raise ErreurValidation("Validez d'abord votre code actuel pour changer d'appareil.", code="totp_deja_actif")
        if utilisateur.totp_reinitialise and not request.session.get(CLE_SESSION_ENROLEMENT_AUTORISE):
            raise ErreurValidation("Saisissez d'abord le code de réactivation remis par l'administrateur.", code="jeton_requis")

    @extend_schema(request=None, responses=EnrolementSerializer)
    def get(self, request: Request) -> Response:
        utilisateur = agent_courant(request)
        self._autoriser(request, utilisateur)
        graine = totp.nouvelle_graine()
        request.session[CLE_SESSION_GRAINE] = totp.graine_en_session(graine)
        uri = totp.uri_enrolement(utilisateur, graine)
        return Response({"uri": uri, "qr_svg": totp.qr_svg(uri), "graine": graine})

    @extend_schema(request=CodeTotpSerializer, responses=EtapeConnexionSerializer)
    def post(self, request: Request) -> Response:
        utilisateur = agent_courant(request)
        self._autoriser(request, utilisateur)
        donnees = CodeTotpSerializer(data=request.data)
        donnees.is_valid(raise_exception=True)
        graine = totp.graine_depuis_session(request.session.get(CLE_SESSION_GRAINE))
        if not graine or not totp.activer(utilisateur, graine, donnees.validated_data["code"]):
            raise ErreurValidation("Code incorrect. Vérifiez l'heure de votre téléphone et réessayez.", code="code_invalide")
        request.session.pop(CLE_SESSION_GRAINE, None)
        request.session.pop(CLE_SESSION_ENROLEMENT_AUTORISE, None)
        request.session.cycle_key()
        request.session[CLE_SESSION_TOTP] = True
        journaliser("totp_active", utilisateur, acteur=utilisateur)
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

    def perform_create(self, serializer: Any) -> None:
        verifier_incompatibilites(serializer.validated_data["utilisateur"], serializer.validated_data["role"])
        super().perform_create(serializer)

    def perform_update(self, serializer: Any) -> None:
        instance: Habilitation = serializer.instance
        if instance.source == "ad":
            raise ErreurValidation(
                "Cette habilitation provient d'un groupe AD : modifiez la correspondance du groupe.", code="habilitation_ad"
            )
        verifier_incompatibilites(
            serializer.validated_data.get("utilisateur", instance.utilisateur),
            serializer.validated_data.get("role", instance.role),
            sauf=instance,
        )
        super().perform_update(serializer)

    def perform_destroy(self, instance: Habilitation) -> None:  # type: ignore[override]
        retirer(agent_courant(self.request), instance)


class VueUtilisateurs(VuePerimetre):
    queryset = Utilisateur.objects.prefetch_related("habilitations__role", "habilitations__perimetre")
    serializer_class = UtilisateurSerializer
    actions_requises = {"lecture": "administrer", "ecriture": "administrer"}
    http_method_names = ["get", "patch", "post", "head", "options"]
    filterset_fields = ["is_active", "source"]

    def create(self, request: Request, *args: Any, **kwargs: Any) -> Response:
        """Les agents naissent à leur première connexion par l'annuaire : pas de création manuelle."""
        return Response({"code": "non_autorise", "message": "Les agents sont créés par l'annuaire."}, status=405)

    @extend_schema(request=None, responses=JetonReinitialisationSerializer)
    @action(detail=True, methods=["post"], url_path="reinitialiser-totp")
    def reinitialiser_totp(self, request: Request, pk: str | None = None) -> Response:
        """Retire l'appareil de l'agent, ferme ses sessions et renvoie le code de réactivation (une seule fois)."""
        utilisateur = self.get_object()
        with transaction.atomic():
            jeton = totp.reinitialiser(utilisateur)
            journaliser("reinitialiser_totp", utilisateur)
        return Response({"jeton_enrolement": jeton, "expire_le": utilisateur.jeton_enrolement_expire})

    def perform_update(self, serializer: Any) -> None:
        super().perform_update(serializer)
        if not serializer.instance.is_active:
            totp.deconnecter_partout(serializer.instance)
