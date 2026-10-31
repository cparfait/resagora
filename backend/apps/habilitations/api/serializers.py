from __future__ import annotations

from typing import Any

from rest_framework import serializers

from apps.referentiel.models import Site

from ..actions import ACTIONS_SENSIBLES
from ..models import GroupeAD, Habilitation, Perimetre, Role, Utilisateur
from ..services import verifier_actions


class ConnexionSerializer(serializers.Serializer):
    identifiant = serializers.CharField(max_length=128)
    mot_de_passe = serializers.CharField(max_length=256, trim_whitespace=False, style={"input_type": "password"})


class CodeTotpSerializer(serializers.Serializer):
    code = serializers.RegexField(r"^\s*\d{3}\s?\d{3}\s*$", error_messages={"invalid": "Le code comporte 6 chiffres."})


class JetonEnrolementSerializer(serializers.Serializer):
    jeton = serializers.RegexField(
        r"^\s*[0-9]{8}\s*$", error_messages={"invalid": "Le code de réactivation comporte 8 chiffres."}
    )


class JetonReinitialisationSerializer(serializers.Serializer):
    jeton_enrolement = serializers.CharField()
    expire_le = serializers.DateTimeField()


class HabilitationMoiSerializer(serializers.Serializer):
    role = serializers.CharField()
    role_libelle = serializers.CharField()
    perimetre = serializers.CharField()
    tous_sites = serializers.BooleanField()
    sites = serializers.ListField(child=serializers.IntegerField())
    actions = serializers.ListField(child=serializers.CharField())


class MoiSerializer(serializers.Serializer):
    id = serializers.IntegerField()
    identifiant = serializers.CharField()
    nom_affiche = serializers.CharField()
    courriel = serializers.EmailField(allow_blank=True)
    double_authentification_exigee = serializers.BooleanField()
    double_authentification_active = serializers.BooleanField()
    double_authentification_validee = serializers.BooleanField()
    habilitations = HabilitationMoiSerializer(many=True)


class EtapeConnexionSerializer(serializers.Serializer):
    etape = serializers.ChoiceField(choices=["connecte", "code_totp", "enrolement_totp", "jeton_enrolement"])
    utilisateur = MoiSerializer(required=False)


class EnrolementSerializer(serializers.Serializer):
    uri = serializers.CharField()
    qr_svg = serializers.CharField()
    graine = serializers.CharField()


class RoleSerializer(serializers.ModelSerializer):
    class Meta:
        model = Role
        fields = ["id", "code", "libelle", "actions", "double_authentification"]

    def validate_actions(self, valeur: list[str]) -> list[str]:
        verifier_actions(valeur)
        return sorted(set(valeur))

    def validate(self, donnees: dict[str, Any]) -> dict[str, Any]:
        actions = set(donnees.get("actions", getattr(self.instance, "actions", [])))
        exigee = donnees.get("double_authentification")
        sensibles = sorted(actions & ACTIONS_SENSIBLES)
        if sensibles and exigee is False:
            raise serializers.ValidationError(
                {
                    "double_authentification": "Ce rôle porte des actions sensibles ("
                    + ", ".join(sensibles)
                    + ") : la double authentification est obligatoire."
                }
            )
        return donnees


class PerimetreSerializer(serializers.ModelSerializer):
    sites = serializers.PrimaryKeyRelatedField(many=True, queryset=Site.objects.all(), required=False)

    class Meta:
        model = Perimetre
        fields = ["id", "nom", "tous_sites", "sites"]

    def validate(self, donnees: dict[str, Any]) -> dict[str, Any]:
        if not donnees.get("tous_sites", getattr(self.instance, "tous_sites", False)) and not donnees.get(
            "sites", list(self.instance.sites.all()) if self.instance else []
        ):
            raise serializers.ValidationError("Choisissez au moins un site ou cochez « tous les sites ».")
        return donnees


class GroupeADSerializer(serializers.ModelSerializer):
    class Meta:
        model = GroupeAD
        fields = ["id", "dn", "libelle", "role", "perimetre", "actif"]


class HabilitationSerializer(serializers.ModelSerializer):
    role_libelle = serializers.CharField(source="role.libelle", read_only=True)
    perimetre_nom = serializers.CharField(source="perimetre.nom", read_only=True)

    class Meta:
        model = Habilitation
        fields = ["id", "utilisateur", "role", "role_libelle", "perimetre", "perimetre_nom", "source", "debut", "fin"]
        read_only_fields = ["source"]


class UtilisateurSerializer(serializers.ModelSerializer):
    habilitations = HabilitationSerializer(many=True, read_only=True)
    nom_affiche = serializers.CharField(read_only=True)

    class Meta:
        model = Utilisateur
        fields = [
            "id",
            "username",
            "first_name",
            "last_name",
            "email",
            "nom_affiche",
            "is_active",
            "source",
            "totp_actif",
            "last_login",
            "derniere_synchronisation_ad",
            "habilitations",
        ]
        read_only_fields = [
            "username",
            "first_name",
            "last_name",
            "email",
            "source",
            "totp_actif",
            "last_login",
            "derniere_synchronisation_ad",
        ]
