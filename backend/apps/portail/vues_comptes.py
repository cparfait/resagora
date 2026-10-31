"""Portail : inscription, connexion, mot de passe, double authentification, compte et export RGPD (POR-01, SEC-04, USR-06)."""

from __future__ import annotations

import json
from typing import Any

from django.db import transaction
from django.http import HttpResponse
from django.utils import timezone
from drf_spectacular.utils import extend_schema
from rest_framework import serializers, status
from rest_framework.request import Request
from rest_framework.response import Response

from apps.communication.models import PreferenceNotification
from apps.communication.services import confirmer_telephone, demander_verification_telephone
from apps.communication.sms import normaliser_mobile
from apps.comptes import services
from apps.comptes.models import JetonPortail
from apps.noyau.exceptions import ErreurValidation
from apps.usagers.models import TYPES_USAGER
from apps.usagers.rgpd import exporter_contact

from .authentification import compte_courant
from .securite import VueContact, VuePublique

TYPES_INSCRIPTION = [t for t in TYPES_USAGER if t[0] != "service_municipal"]


class ConnexionSerializer(serializers.Serializer):
    identifiant = serializers.CharField(max_length=254)
    mot_de_passe = serializers.CharField(max_length=256, trim_whitespace=False)


class DefiSerializer(serializers.Serializer):
    defi = serializers.CharField(max_length=100)
    code = serializers.CharField(max_length=10)


class ContactInscriptionSerializer(serializers.Serializer):
    civilite = serializers.ChoiceField(choices=["", "Madame", "Monsieur"], required=False, default="")
    prenom = serializers.CharField(max_length=100)
    nom = serializers.CharField(max_length=100)
    courriel = serializers.EmailField(max_length=254)
    telephone = serializers.CharField(max_length=20, required=False, allow_blank=True, default="")


class UsagerInscriptionSerializer(serializers.Serializer):
    type = serializers.ChoiceField(choices=TYPES_INSCRIPTION)
    nom = serializers.CharField(max_length=200, required=False, allow_blank=True, default="")
    sigle = serializers.CharField(max_length=40, required=False, allow_blank=True, default="")
    siret = serializers.RegexField(r"^(\d{14})?$", required=False, allow_blank=True, default="")
    rna = serializers.RegexField(r"^(W\d{9})?$", required=False, allow_blank=True, default="")
    adresse = serializers.CharField(max_length=250)
    code_postal = serializers.RegexField(r"^\d{5}$")
    commune = serializers.CharField(max_length=80)
    telephone = serializers.CharField(max_length=20, required=False, allow_blank=True, default="")
    role_contact = serializers.ChoiceField(
        choices=["president", "tresorier", "secretaire", "referent", "directeur", "responsable", "autre"],
        required=False,
        default="responsable",
    )

    def validate(self, donnees: dict[str, Any]) -> dict[str, Any]:
        if donnees["type"] != "particulier" and not donnees.get("nom", "").strip():
            raise serializers.ValidationError({"nom": "Indiquez le nom de la structure."})
        return donnees


class InscriptionSerializer(serializers.Serializer):
    contact = ContactInscriptionSerializer()
    usager = UsagerInscriptionSerializer()
    mot_de_passe = serializers.CharField(max_length=256, trim_whitespace=False)
    consentement = serializers.BooleanField()


class JetonSerializer(serializers.Serializer):
    jeton = serializers.CharField(max_length=100)


class ReinitialisationSerializer(JetonSerializer):
    mot_de_passe = serializers.CharField(max_length=256, trim_whitespace=False)


class IdentifiantSerializer(serializers.Serializer):
    identifiant = serializers.CharField(max_length=254)


def message(texte: str, statut: int = status.HTTP_200_OK) -> Response:
    return Response({"message": texte}, status=statut)


class VueConnexion(VuePublique):
    throttle_scope = "connexion"

    @extend_schema(request=ConnexionSerializer, responses={200: dict})
    def post(self, request: Request) -> Response:
        entree = ConnexionSerializer(data=request.data)
        entree.is_valid(raise_exception=True)
        return Response(services.connecter(entree.validated_data["identifiant"], entree.validated_data["mot_de_passe"]))


class VueDefiTotp(VuePublique):
    throttle_scope = "connexion"

    @extend_schema(request=DefiSerializer, responses={200: dict})
    def post(self, request: Request) -> Response:
        entree = DefiSerializer(data=request.data)
        entree.is_valid(raise_exception=True)
        return Response(services.valider_defi_totp(entree.validated_data["defi"], entree.validated_data["code"]))


class VueDeconnexion(VueContact):
    @extend_schema(request=None, responses={204: None})
    def post(self, request: Request) -> Response:
        if isinstance(request.auth, JetonPortail):
            services.revoquer(request.auth)
        return Response(status=status.HTTP_204_NO_CONTENT)


class VueInscription(VuePublique):
    throttle_scope = "inscription"

    @extend_schema(request=InscriptionSerializer, responses={202: dict})
    def post(self, request: Request) -> Response:
        entree = InscriptionSerializer(data=request.data)
        entree.is_valid(raise_exception=True)
        d = entree.validated_data
        resultat = services.inscrire(
            contact=d["contact"], usager=d["usager"], mot_de_passe=d["mot_de_passe"], consentement=d["consentement"]
        )
        return message(resultat.message, status.HTTP_202_ACCEPTED)


class VueConfirmation(VuePublique):
    throttle_scope = "inscription"

    @extend_schema(request=JetonSerializer, responses={200: dict})
    def post(self, request: Request) -> Response:
        entree = JetonSerializer(data=request.data)
        entree.is_valid(raise_exception=True)
        return message(services.confirmer_courriel(entree.validated_data["jeton"]).message)


class VueConfirmationNouvelleAdresse(VuePublique):
    throttle_scope = "inscription"

    @extend_schema(request=JetonSerializer, responses={200: dict})
    def post(self, request: Request) -> Response:
        entree = JetonSerializer(data=request.data)
        entree.is_valid(raise_exception=True)
        return message(services.confirmer_changement_courriel(entree.validated_data["jeton"]).message)


class VueInvitation(VuePublique):
    throttle_scope = "reinitialisation"

    @extend_schema(request=ReinitialisationSerializer, responses={200: dict})
    def post(self, request: Request) -> Response:
        entree = ReinitialisationSerializer(data=request.data)
        entree.is_valid(raise_exception=True)
        d = entree.validated_data
        return message(services.accepter_invitation(d["jeton"], d["mot_de_passe"]).message)


class VueMotDePasseOublie(VuePublique):
    throttle_scope = "reinitialisation"

    @extend_schema(request=IdentifiantSerializer, responses={202: dict})
    def post(self, request: Request) -> Response:
        entree = IdentifiantSerializer(data=request.data)
        entree.is_valid(raise_exception=True)
        return message(services.demander_reinitialisation(entree.validated_data["identifiant"]).message, status.HTTP_202_ACCEPTED)


class VueReinitialisation(VuePublique):
    throttle_scope = "reinitialisation"

    @extend_schema(request=ReinitialisationSerializer, responses={200: dict})
    def post(self, request: Request) -> Response:
        entree = ReinitialisationSerializer(data=request.data)
        entree.is_valid(raise_exception=True)
        d = entree.validated_data
        return message(services.reinitialiser(d["jeton"], d["mot_de_passe"]).message)


# --- Compte --------------------------------------------------------------------------------------


class CompteSerializer(serializers.Serializer):
    civilite = serializers.ChoiceField(choices=["", "Madame", "Monsieur"], required=False)
    prenom = serializers.CharField(max_length=100, required=False)
    nom = serializers.CharField(max_length=100, required=False)
    telephone = serializers.CharField(max_length=20, required=False, allow_blank=True)


def representation_compte(compte: Any) -> dict[str, Any]:
    c = compte.contact
    return {
        "identifiant": compte.identifiant,
        "civilite": c.civilite,
        "prenom": c.prenom,
        "nom": c.nom,
        "courriel": c.courriel,
        "telephone": c.telephone,
        "totp": compte.totp_actif,
        "derniere_connexion": compte.derniere_connexion,
        "mot_de_passe_modifie_le": compte.mot_de_passe_modifie_le,
        "usagers": [
            {
                "id": r.usager_id,
                "nom": r.usager.nom,
                "role": r.get_role_display(),
                "statut": r.usager.statut,
                "peut_signer": r.peut_signer,
            }
            for r in c.rattachements.select_related("usager").exclude(usager__statut="anonymise")
        ],
    }


class VueCompte(VueContact):
    @extend_schema(responses={200: dict})
    def get(self, request: Request) -> Response:
        return Response(representation_compte(compte_courant(request)))

    @extend_schema(request=CompteSerializer, responses={200: dict})
    def patch(self, request: Request) -> Response:
        from apps.audit.services import instantane, journaliser

        compte = compte_courant(request)
        entree = CompteSerializer(data=request.data, partial=True)
        entree.is_valid(raise_exception=True)
        contact = compte.contact
        avant = instantane(contact)
        for champ, valeur in entree.validated_data.items():
            setattr(contact, champ, valeur)
        contact.save()
        journaliser("modifier_contact_portail", contact, avant=avant, apres=instantane(contact), acteur=contact)
        return Response(representation_compte(compte))


class ChangementMotDePasseSerializer(serializers.Serializer):
    actuel = serializers.CharField(max_length=256, trim_whitespace=False)
    nouveau = serializers.CharField(max_length=256, trim_whitespace=False)


class VueMotDePasse(VueContact):
    throttle_scope = "connexion"

    @extend_schema(request=ChangementMotDePasseSerializer, responses={200: dict})
    def post(self, request: Request) -> Response:
        entree = ChangementMotDePasseSerializer(data=request.data)
        entree.is_valid(raise_exception=True)
        services.changer_mot_de_passe(
            compte_courant(request),
            entree.validated_data["actuel"],
            entree.validated_data["nouveau"],
            jeton=request.auth if isinstance(request.auth, JetonPortail) else None,
        )
        return message("Votre mot de passe est modifié. Vos autres sessions ont été fermées.")


class ChangementCourrielSerializer(serializers.Serializer):
    nouveau = serializers.EmailField(max_length=254)
    mot_de_passe = serializers.CharField(max_length=256, trim_whitespace=False)


class VueCourrielCompte(VueContact):
    """Changement d'adresse : confirmé par la nouvelle adresse, signalé à l'ancienne."""

    throttle_scope = "connexion"

    @extend_schema(request=ChangementCourrielSerializer, responses={200: dict})
    def post(self, request: Request) -> Response:
        entree = ChangementCourrielSerializer(data=request.data)
        entree.is_valid(raise_exception=True)
        d = entree.validated_data
        return message(services.demander_changement_courriel(compte_courant(request), d["nouveau"], d["mot_de_passe"]).message)


class CodeSerializer(serializers.Serializer):
    code = serializers.CharField(max_length=10)


class MotDePasseSerializer(serializers.Serializer):
    mot_de_passe = serializers.CharField(max_length=256, trim_whitespace=False)


class ActivationTotpSerializer(serializers.Serializer):
    code = serializers.CharField(max_length=10)
    mot_de_passe = serializers.CharField(max_length=256, trim_whitespace=False)


class VueTotpCompte(VueContact):
    throttle_scope = "connexion"

    @extend_schema(responses={200: dict})
    def get(self, request: Request) -> Response:
        compte = compte_courant(request)
        if compte.totp_actif:
            return Response({"actif": True})
        return Response({"actif": False, **services.commencer_totp(compte)})

    @extend_schema(request=ActivationTotpSerializer, responses={200: dict})
    def post(self, request: Request) -> Response:
        entree = ActivationTotpSerializer(data=request.data)
        entree.is_valid(raise_exception=True)
        services.activer_totp(compte_courant(request), entree.validated_data["code"], entree.validated_data["mot_de_passe"])
        return message("La double authentification est activée.")

    @extend_schema(request=MotDePasseSerializer, responses={200: dict})
    def delete(self, request: Request) -> Response:
        entree = MotDePasseSerializer(data=request.data)
        entree.is_valid(raise_exception=True)
        services.desactiver_totp(compte_courant(request), entree.validated_data["mot_de_passe"])
        return message("La double authentification est désactivée.")


class PreferencesSerializer(serializers.ModelSerializer):
    telephone_confirme = serializers.SerializerMethodField()

    class Meta:
        model = PreferenceNotification
        fields = ["sms", "telephone_sms", "telephone_confirme", "rappels", "informations"]

    def get_telephone_confirme(self, preferences: PreferenceNotification) -> bool:
        return bool(preferences.telephone_sms) and preferences.telephone_sms == preferences.telephone_verifie

    def validate_telephone_sms(self, valeur: str) -> str:
        return (normaliser_mobile(valeur) or valeur) if valeur else ""

    def validate(self, donnees: dict[str, Any]) -> dict[str, Any]:
        sms = donnees.get("sms", getattr(self.instance, "sms", False))
        telephone = donnees.get("telephone_sms", getattr(self.instance, "telephone_sms", ""))
        if sms and normaliser_mobile(telephone) is None:
            raise ErreurValidation(
                "Indiquez un numéro de téléphone mobile (06 ou 07) pour recevoir les SMS.", code="mobile_invalide"
            )
        return donnees


class VuePreferences(VueContact):
    """COM-04 : préférences de notification du contact connecté."""

    @extend_schema(responses={200: PreferencesSerializer})
    def get(self, request: Request) -> Response:
        preferences, _ = PreferenceNotification.objects.get_or_create(contact=compte_courant(request).contact)
        return Response(PreferencesSerializer(preferences).data)

    @extend_schema(request=PreferencesSerializer, responses={200: PreferencesSerializer})
    def patch(self, request: Request) -> Response:
        preferences, _ = PreferenceNotification.objects.get_or_create(contact=compte_courant(request).contact)
        entree = PreferencesSerializer(preferences, data=request.data, partial=True)
        entree.is_valid(raise_exception=True)
        with transaction.atomic():
            preferences = entree.save()
            if preferences.sms and preferences.telephone_sms != preferences.telephone_verifie:
                demander_verification_telephone(preferences, preferences.telephone_sms)
        return Response(PreferencesSerializer(preferences).data)


class CodeTelephoneSerializer(serializers.Serializer):
    code = serializers.CharField(max_length=10)


class VueVerificationTelephone(VueContact):
    """COM-05 : confirmation du numéro de mobile par le code reçu ; « renvoyer » en demande un nouveau."""

    throttle_scope = "connexion"

    @extend_schema(request=CodeTelephoneSerializer, responses={200: PreferencesSerializer})
    def post(self, request: Request) -> Response:
        preferences, _ = PreferenceNotification.objects.get_or_create(contact=compte_courant(request).contact)
        if isinstance(request.data, dict) and request.data.get("renvoyer") is True:
            if not preferences.telephone_sms:
                raise ErreurValidation("Indiquez d'abord un numéro de mobile.", code="mobile_invalide")
            demander_verification_telephone(preferences, preferences.telephone_sms)
            return Response(PreferencesSerializer(preferences).data)
        entree = CodeTelephoneSerializer(data=request.data)
        entree.is_valid(raise_exception=True)
        confirmer_telephone(preferences, entree.validated_data["code"])
        return Response(PreferencesSerializer(preferences).data)


class VueExportCompte(VueContact):
    """USR-06 : export des données personnelles du contact et des structures qu'il représente."""

    @extend_schema(responses={(200, "application/json"): bytes})
    def get(self, request: Request) -> HttpResponse:
        compte = compte_courant(request)
        donnees = exporter_contact(compte.contact)
        reponse = HttpResponse(
            json.dumps(donnees, ensure_ascii=False, indent=2, default=str), content_type="application/json; charset=utf-8"
        )
        reponse["Content-Disposition"] = f'attachment; filename="mes-donnees-{timezone.localdate():%Y%m%d}.json"'
        return reponse
