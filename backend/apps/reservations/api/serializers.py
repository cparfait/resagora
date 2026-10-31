from __future__ import annotations

from typing import Any

from rest_framework import serializers

from apps.referentiel.models import Espace

from ..conditions import conditions_manquantes
from ..models import Campagne, Dossier, ListeAttente, Occurrence, Reservation, TypeReservation, VueEnregistree


class TypeReservationSerializer(serializers.ModelSerializer):
    class Meta:
        model = TypeReservation
        fields = [
            "id",
            "code",
            "libelle",
            "exige_pieces",
            "exige_convention",
            "exige_acompte",
            "exige_caution",
            "ouvert_portail",
            "types_usager",
            "ordre",
        ]


class OccurrenceSerializer(serializers.ModelSerializer):
    espace_nom = serializers.CharField(source="espace.nom", read_only=True)
    bloquante = serializers.BooleanField(read_only=True)

    class Meta:
        model = Occurrence
        fields = [
            "id",
            "reservation",
            "espace",
            "espace_nom",
            "debut",
            "fin",
            "statut",
            "bloquante",
            "presence",
            "debut_reel",
            "fin_reel",
            "annulee_le",
            "motif_annulation",
            "annulation_tardive",
            "annulee_par_usager",
            "signalement",
            "debut_origine",
            "modifiee_individuellement",
        ]
        read_only_fields = fields


class ReservationSerializer(serializers.ModelSerializer):
    espace_nom = serializers.CharField(source="espace.nom", read_only=True)
    site_nom = serializers.CharField(source="espace.batiment.site.nom", read_only=True)
    site = serializers.IntegerField(source="espace.batiment.site_id", read_only=True)
    description = serializers.CharField(read_only=True)
    nombre_occurrences = serializers.SerializerMethodField()
    conditions_manquantes = serializers.SerializerMethodField()

    class Meta:
        model = Reservation
        fields = [
            "id",
            "dossier",
            "espace",
            "espace_nom",
            "site_nom",
            "site",
            "statut",
            "recurrence",
            "description",
            "date_debut",
            "date_fin",
            "heure_debut",
            "heure_fin",
            "exclure_vacances",
            "exclure_feries",
            "exdates",
            "option_expire_le",
            "option_relancee_le",
            "motif_refus",
            "motif_annulation",
            "annulee_le",
            "valide_le",
            "confirme_le",
            "nombre_occurrences",
            "conditions_manquantes",
        ]
        read_only_fields = fields

    def get_nombre_occurrences(self, reservation: Reservation) -> int:
        return reservation.occurrences.exclude(statut="annulee").count()

    def get_conditions_manquantes(self, reservation: Reservation) -> list[str]:
        if self.context.get("liste") or reservation.statut not in {"validee", "option", "en_instruction", "demande"}:
            return []
        return conditions_manquantes(reservation)


class NouvelleReservationSerializer(serializers.Serializer):
    espace = serializers.PrimaryKeyRelatedField(queryset=Espace.objects.filter(actif=True))
    date_debut = serializers.DateField()
    date_fin = serializers.DateField()
    heure_debut = serializers.TimeField()
    heure_fin = serializers.TimeField()
    recurrence = serializers.CharField(required=False, allow_blank=True, default="", max_length=200)
    exclure_vacances = serializers.BooleanField(default=True)
    exclure_feries = serializers.BooleanField(default=True)
    exdates = serializers.ListField(child=serializers.DateField(), required=False, default=list, max_length=200)
    forcer_horaires = serializers.BooleanField(default=False)
    motif_forcage = serializers.CharField(required=False, allow_blank=True, default="", max_length=250)

    def validate(self, donnees: dict[str, Any]) -> dict[str, Any]:
        if donnees["date_fin"] < donnees["date_debut"]:
            raise serializers.ValidationError({"date_fin": "La date de fin doit suivre la date de début."})
        if (
            not donnees.get("recurrence")
            and donnees["date_fin"] == donnees["date_debut"]
            and donnees["heure_fin"] == donnees["heure_debut"]
        ):
            raise serializers.ValidationError({"heure_fin": "L'heure de fin doit différer de l'heure de début."})
        return donnees


class ModificationSerieSerializer(serializers.Serializer):
    espace = serializers.PrimaryKeyRelatedField(queryset=Espace.objects.filter(actif=True), required=False)
    heure_debut = serializers.TimeField(required=False)
    heure_fin = serializers.TimeField(required=False)
    date_fin = serializers.DateField(required=False)
    recurrence = serializers.CharField(required=False, allow_blank=True, max_length=200)
    exclure_vacances = serializers.BooleanField(required=False)
    exclure_feries = serializers.BooleanField(required=False)
    exdates = serializers.ListField(child=serializers.DateField(), required=False, max_length=200)


class DossierSerializer(serializers.ModelSerializer):
    usager_nom = serializers.CharField(source="usager.nom", read_only=True)
    usager_type = serializers.CharField(source="usager.type", read_only=True)
    type_reservation_libelle = serializers.CharField(source="type_reservation.libelle", read_only=True)
    statut = serializers.CharField(read_only=True)
    reservations = ReservationSerializer(many=True, read_only=True)

    class Meta:
        model = Dossier
        fields = [
            "id",
            "numero",
            "usager",
            "usager_nom",
            "usager_type",
            "contact",
            "type_reservation",
            "type_reservation_libelle",
            "objet",
            "activite",
            "effectif",
            "saison",
            "campagne",
            "origine",
            "observations",
            "statut",
            "cree_le",
            "depose_le",
            "conditions_attestees",
            "reservations",
        ]
        read_only_fields = ["numero", "origine", "cree_le", "depose_le", "statut", "reservations", "conditions_attestees"]


class MotifSerializer(serializers.Serializer):
    motif = serializers.CharField(max_length=300)


class AnnulationSerializer(MotifSerializer):
    par_usager = serializers.BooleanField(
        default=False, help_text="Annulation demandée par l'usager (tardive dans le délai paramétré, RG-08)."
    )


class AttestationSerializer(serializers.Serializer):
    condition = serializers.ChoiceField(choices=["pieces", "convention", "acompte", "caution"])
    motif = serializers.CharField(max_length=300)


class RefusSerializer(MotifSerializer):
    alternatives = serializers.CharField(max_length=500, required=False, allow_blank=True, default="")


class OptionSerializer(serializers.Serializer):
    jours = serializers.IntegerField(min_value=1, max_value=60, required=False)


class DeplacementSerializer(serializers.Serializer):
    espace = serializers.PrimaryKeyRelatedField(queryset=Espace.objects.filter(actif=True))
    debut = serializers.DateTimeField()
    fin = serializers.DateTimeField()
    forcer_horaires = serializers.BooleanField(default=False)
    motif_forcage = serializers.CharField(required=False, allow_blank=True, default="", max_length=250)


class PresenceSerializer(serializers.Serializer):
    presence = serializers.ChoiceField(choices=["present", "absent_signale", "absent_non_signale"])
    debut_reel = serializers.DateTimeField(required=False, allow_null=True)
    fin_reel = serializers.DateTimeField(required=False, allow_null=True)


class ConflitSerializer(serializers.Serializer):
    occurrence = serializers.IntegerField()
    reservation = serializers.IntegerField()
    dossier = serializers.CharField()
    usager = serializers.CharField()
    espace = serializers.CharField()
    debut = serializers.DateTimeField()
    fin = serializers.DateTimeField()


class AlternativeSerializer(serializers.Serializer):
    espace = serializers.IntegerField()
    espace_nom = serializers.CharField()
    debut = serializers.DateTimeField()
    fin = serializers.DateTimeField()
    raison = serializers.CharField()


class ControleSerializer(serializers.Serializer):
    possible = serializers.BooleanField()
    hors_horaires = serializers.BooleanField()
    fermeture = serializers.BooleanField()
    conflits = ConflitSerializer(many=True)
    alternatives = AlternativeSerializer(many=True)


class ApercuSerializer(serializers.Serializer):
    seances = serializers.ListField(child=serializers.DictField())
    conflits = ConflitSerializer(many=True)
    hors_horaires = serializers.ListField(child=serializers.DateTimeField())
    fermetures = serializers.ListField(child=serializers.DateTimeField())
    description = serializers.CharField()


def _cles_entieres(valeur: dict[str, Any]) -> dict[str, Any]:
    if any(not str(k).isdigit() or len(str(k)) > 12 for k in valeur):
        raise serializers.ValidationError("Les clés doivent être des identifiants numériques.")
    return valeur


class PrioriteMunicipaleSerializer(serializers.Serializer):
    motif = serializers.CharField(max_length=300)
    deplacements = serializers.DictField(child=DeplacementSerializer(), required=False, default=dict)

    def validate_deplacements(self, valeur: dict[str, Any]) -> dict[str, Any]:
        return _cles_entieres(valeur)


class CampagneSerializer(serializers.ModelSerializer):
    saison_nom = serializers.CharField(source="saison.nom", read_only=True)
    nombre_demandes = serializers.SerializerMethodField()

    class Meta:
        model = Campagne
        fields = [
            "id",
            "saison",
            "saison_nom",
            "nom",
            "ouverture",
            "cloture",
            "date_commission",
            "statut",
            "sites",
            "nombre_demandes",
        ]
        read_only_fields = ["statut"]

    def validate(self, donnees: dict[str, Any]) -> dict[str, Any]:
        campagne = self.instance
        if campagne is not None and campagne.statut != "preparation":
            figes = {"saison", "sites", "ouverture"} & set(donnees)
            changes = [
                c
                for c in figes
                if (set(donnees[c]) != set(campagne.sites.all()) if c == "sites" else donnees[c] != getattr(campagne, c))
            ]
            if changes:
                raise serializers.ValidationError(
                    "Saison, sites et date d'ouverture ne changent plus après l'ouverture de la campagne."
                )
            if campagne.statut in {"attribuee", "close"} and set(donnees) - {"nom"}:
                raise serializers.ValidationError("Une campagne attribuée ou close ne se modifie plus.")
        return donnees

    def get_nombre_demandes(self, campagne: Campagne) -> int:
        return Reservation.objects.filter(dossier__campagne=campagne).count()


class StatutCampagneSerializer(serializers.Serializer):
    statut = serializers.ChoiceField(choices=[s for s, _ in Campagne.STATUTS])


class DecisionSerializer(serializers.Serializer):
    decision = serializers.ChoiceField(choices=["attribuer", "refuser"])
    motif = serializers.CharField(max_length=300, required=False, allow_blank=True, default="")


class AttributionSerializer(serializers.Serializer):
    decisions = serializers.DictField(child=DecisionSerializer())

    def validate_decisions(self, valeur: dict[str, Any]) -> dict[str, Any]:
        return _cles_entieres(valeur)


class ListeAttenteSerializer(serializers.ModelSerializer):
    usager_nom = serializers.CharField(source="usager.nom", read_only=True)
    espace_nom = serializers.CharField(source="espace.nom", read_only=True)

    class Meta:
        model = ListeAttente
        fields = [
            "id",
            "espace",
            "espace_nom",
            "debut",
            "fin",
            "usager",
            "usager_nom",
            "contact",
            "statut",
            "cree_le",
            "notifie_le",
        ]
        read_only_fields = ["statut", "cree_le", "notifie_le"]


class VueEnregistreeSerializer(serializers.ModelSerializer):
    class Meta:
        model = VueEnregistree
        fields = ["id", "nom", "mode", "filtres", "coloration", "par_defaut"]


class SeancePlanningSerializer(serializers.Serializer):
    id = serializers.IntegerField()
    reservation = serializers.IntegerField()
    dossier = serializers.IntegerField()
    numero = serializers.CharField()
    objet = serializers.CharField()
    usager = serializers.CharField()
    type_usager = serializers.CharField()
    espace = serializers.IntegerField()
    espace_nom = serializers.CharField()
    site = serializers.IntegerField()
    debut = serializers.DateTimeField()
    fin = serializers.DateTimeField()
    statut = serializers.CharField()
    signalement = serializers.CharField()
