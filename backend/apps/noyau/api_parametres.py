"""Paramètres fonctionnels (ADM-02) : lecture par les agents, modification tracée par l'administration."""

from __future__ import annotations

from typing import Any

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
from .parametres import DEFINITIONS, PAR_CLE, invalider, tous


class ParametreSerializer(serializers.Serializer):
    cle = serializers.CharField()
    libelle = serializers.CharField()
    groupe = serializers.CharField()
    aide = serializers.CharField()
    valeur = serializers.JSONField()
    defaut = serializers.JSONField()


class ModificationSerializer(serializers.Serializer):
    valeurs = serializers.DictField(child=serializers.JSONField())


def _meme_type(defaut: Any, valeur: Any) -> bool:
    if isinstance(defaut, bool):
        return isinstance(valeur, bool)
    if isinstance(defaut, int):
        return isinstance(valeur, int) and not isinstance(valeur, bool) and valeur >= 0
    return isinstance(valeur, type(defaut))


class VueParametres(APIView):
    actions_requises = {"get": "lire_referentiel", "patch": "gerer_parametres"}

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
        exiger(agent, "gerer_parametres", Parametre(cle="*"))
        donnees = ModificationSerializer(data=request.data)
        donnees.is_valid(raise_exception=True)
        erreurs = {}
        for cle, valeur in donnees.validated_data["valeurs"].items():
            definition = PAR_CLE.get(cle)
            if definition is None:
                erreurs[cle] = ["Paramètre inconnu."]
            elif not _meme_type(definition.defaut, valeur):
                erreurs[cle] = [f"Valeur attendue du même type que la valeur par défaut ({type(definition.defaut).__name__})."]
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
        return self.get(request)
