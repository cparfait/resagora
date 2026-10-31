"""Paramètres fonctionnels (ADM-02) : lecture par les agents, modification tracée par l'administration."""

from __future__ import annotations

from django.db import transaction
from drf_spectacular.utils import extend_schema
from rest_framework import serializers
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.audit.services import journaliser
from apps.habilitations.authentification import agent_courant
from apps.habilitations.services import exiger

from .exceptions import ErreurValidation
from .models import Parametre
from .parametres import DEFINITIONS, PARAMETRES_FINANCIERS, invalider, tous, valider_valeur


class ParametreSerializer(serializers.Serializer):
    cle = serializers.CharField()
    libelle = serializers.CharField()
    groupe = serializers.CharField()
    aide = serializers.CharField()
    valeur = serializers.JSONField()
    defaut = serializers.JSONField()


class ModificationSerializer(serializers.Serializer):
    valeurs = serializers.DictField(child=serializers.JSONField())


class VueParametres(APIView):
    # PATCH : le service contrôle gerer_parametres ou, pour les paramètres financiers, gerer_tarifs.
    actions_requises = {"get": "lire_referentiel", "patch": "lire_referentiel"}

    @extend_schema(responses=ParametreSerializer(many=True))
    def get(self, request: Request) -> Response:
        valeurs = tous()
        return Response(
            [
                {
                    "cle": d.cle,
                    "libelle": d.libelle,
                    "groupe": d.groupe,
                    "aide": d.aide,
                    "valeur": valeurs[d.cle],
                    "defaut": d.defaut,
                }
                for d in DEFINITIONS
            ]
        )

    @extend_schema(request=ModificationSerializer, responses=ParametreSerializer(many=True))
    def patch(self, request: Request) -> Response:
        agent = agent_courant(request)
        donnees = ModificationSerializer(data=request.data)
        donnees.is_valid(raise_exception=True)
        # Coordonnées bancaires du comptable et seuils financiers : réservés à l'ordonnateur (gerer_tarifs), jamais à
        # l'administrateur fonctionnel (séparation des tâches, revue sécurité du lot 3, M5).
        cles = set(donnees.validated_data["valeurs"])
        if cles & PARAMETRES_FINANCIERS:
            exiger(agent, "gerer_tarifs", Parametre(cle="*"))
        if cles - PARAMETRES_FINANCIERS:
            exiger(agent, "gerer_parametres", Parametre(cle="*"))
        erreurs = {}
        for cle, valeur in donnees.validated_data["valeurs"].items():
            message = valider_valeur(cle, valeur)
            if message:
                erreurs[cle] = [message]
        if erreurs:
            raise ErreurValidation("Certains paramètres sont invalides.", code="validation", details={"champs": erreurs})
        anciennes = tous()
        with transaction.atomic():
            for cle, valeur in donnees.validated_data["valeurs"].items():
                Parametre.objects.update_or_create(cle=cle, defaults={"valeur": valeur, "modifie_par": agent})
                journaliser(
                    "modifier_parametre",
                    objet_type="noyau.parametre",
                    objet_id=cle,
                    avant={"valeur": anciennes[cle]},
                    apres={"valeur": valeur},
                )
        invalider()
        financiers = sorted(cles & PARAMETRES_FINANCIERS)
        if financiers:
            from django.db import transaction as transaction_notif

            from apps.communication.services import notifier
            from apps.noyau.parametres import parametre

            with transaction_notif.atomic():
                notifier(
                    "parametre_financier_modifie",
                    {"agent": str(agent), "parametres": ", ".join(financiers)},
                    courriels=[str(parametre("portail.service_courriel"))],
                )
        return self.get(request)
