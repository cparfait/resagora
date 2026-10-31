"""API de la valorisation des avantages en nature (VAL-01 à VAL-08)."""

from __future__ import annotations

from datetime import date
from typing import Any

from django.db.models import Q
from django.http import HttpResponse
from django.utils import timezone
from drf_spectacular.utils import OpenApiParameter, extend_schema
from rest_framework import serializers, status
from rest_framework.decorators import action
from rest_framework.parsers import MultiPartParser
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.routers import SimpleRouter

from apps.habilitations.authentification import agent_courant
from apps.noyau.api import VuePerimetre
from apps.noyau.exceptions import ErreurMetier, ErreurValidation
from apps.usagers.models import Usager

from . import services
from .models import Exercice, LigneValorisation, MethodeValorisation, SubventionNumeraire, Valorisation


class ExerciceSerializer(serializers.ModelSerializer):
    date_limite = serializers.SerializerMethodField()
    cout_personnel = serializers.SerializerMethodField()
    absences_valorisees = serializers.SerializerMethodField()

    class Meta:
        model = Exercice
        fields = [
            "id",
            "annee",
            "statut",
            "date_limite_attestations",
            "date_limite",
            "cloture_le",
            "cout_horaire_personnel_centimes",
            "absences_non_signalees_valorisees",
            "cout_personnel",
            "absences_valorisees",
        ]
        read_only_fields = ["statut", "cloture_le"]

    def get_date_limite(self, exercice: Exercice) -> date:
        return exercice.date_limite()

    def get_cout_personnel(self, exercice: Exercice) -> int:
        return exercice.cout_personnel()

    def get_absences_valorisees(self, exercice: Exercice) -> bool:
        return exercice.absences_valorisees()

    def validate_annee(self, annee: int) -> int:
        if self.instance is not None and annee != self.instance.annee:
            raise serializers.ValidationError("L'année d'un exercice ne change pas.")
        if not 2000 <= annee <= timezone.localdate().year + 1:
            raise serializers.ValidationError("Année hors bornes.")
        return annee

    def validate_cout_horaire_personnel_centimes(self, valeur: int | None) -> int | None:
        if valeur is not None and valeur > 50_000:
            raise serializers.ValidationError("500 € de l'heure au plus.")
        return valeur

    def validate(self, donnees: dict[str, Any]) -> dict[str, Any]:
        if self.instance is not None and self.instance.statut == "cloture":
            changes = {k for k in donnees if k != "date_limite_attestations"}
            if changes:
                raise serializers.ValidationError("Exercice clôturé : ses paramètres de calcul sont figés (VAL-08).")
        return donnees

    def create(self, donnees: dict[str, Any]) -> Exercice:
        # M8 : les paramètres généraux du moment deviennent ceux de l'exercice.
        from apps.noyau.parametres import parametre

        donnees.setdefault("cout_horaire_personnel_centimes", int(parametre("valorisation.cout_horaire_personnel_centimes")))
        donnees.setdefault("absences_non_signalees_valorisees", bool(parametre("valorisation.absences_non_signalees_valorisees")))
        return super().create(donnees)


class MethodeSerializer(serializers.ModelSerializer):
    famille_libelle = serializers.CharField(source="famille.libelle", read_only=True)

    class Meta:
        model = MethodeValorisation
        fields = [
            "id",
            "exercice",
            "famille",
            "famille_libelle",
            "methode",
            "cout_horaire_centimes",
            "loyer_m2_annuel_centimes",
            "heures_annuelles_reference",
            "deliberation_reference",
        ]

    def validate(self, donnees: dict[str, Any]) -> dict[str, Any]:
        if self.instance is not None:
            for champ in ("exercice", "famille"):
                if champ in donnees and donnees[champ] != getattr(self.instance, champ):
                    raise serializers.ValidationError({champ: "Ne change pas : créez une méthode pour l'autre exercice."})
            if self.instance.exercice.statut == "cloture":
                raise serializers.ValidationError("L'exercice est clôturé : sa méthode ne change plus (VAL-01).")
        exercice = donnees.get("exercice") or getattr(self.instance, "exercice", None)
        if exercice is not None and exercice.statut == "cloture":
            raise serializers.ValidationError("L'exercice est clôturé : sa méthode ne change plus (VAL-01).")
        methode = donnees.get("methode", getattr(self.instance, "methode", "tarif_reference"))
        if methode == "cout_revient" and not donnees.get(
            "cout_horaire_centimes", getattr(self.instance, "cout_horaire_centimes", None)
        ):
            raise serializers.ValidationError({"cout_horaire_centimes": "Indiquez le coût de revient horaire."})
        if methode == "valeur_locative" and not donnees.get(
            "loyer_m2_annuel_centimes", getattr(self.instance, "loyer_m2_annuel_centimes", None)
        ):
            raise serializers.ValidationError({"loyer_m2_annuel_centimes": "Indiquez la valeur locative annuelle du m²."})
        if methode != "tarif_reference" and not donnees.get(
            "deliberation_reference", getattr(self.instance, "deliberation_reference", "")
        ):
            raise serializers.ValidationError(
                {"deliberation_reference": "Une méthode autre que le tarif voté se fonde sur une délibération."}
            )
        return donnees


class LigneSerializer(serializers.ModelSerializer):
    class Meta:
        model = LigneValorisation
        fields = [
            "id",
            "nature",
            "libelle",
            "methode",
            "quantite",
            "part",
            "montant_reference",
            "montant_paye",
            "montant_valorise",
            "observation",
        ]


class ValorisationSerializer(serializers.ModelSerializer):
    usager_nom = serializers.CharField(source="usager.nom", read_only=True)
    usager_type = serializers.CharField(source="usager.type", read_only=True)
    annee = serializers.IntegerField(source="exercice.annee", read_only=True)
    lignes = serializers.SerializerMethodField()

    class Meta:
        model = Valorisation
        fields = [
            "id",
            "exercice",
            "annee",
            "usager",
            "usager_nom",
            "usager_type",
            "version",
            "actuelle",
            "figee",
            "minutes",
            "montant_espaces",
            "montant_materiel",
            "montant_personnel",
            "total",
            "calcule_le",
            "calcule_par",
            "motif_recalcul",
            "document",
            "deposee_le",
            "lignes",
        ]
        read_only_fields = fields

    def get_lignes(self, valorisation: Valorisation) -> list[dict[str, Any]]:
        """Détail des séances et prêts ; un agent limité à des sites n'en voit que les lignes de ses sites (m4)."""
        if not self.context.get("detail"):
            return []
        lignes = valorisation.lignes.all()
        sites = self.context.get("sites")
        if sites is not None:
            lignes = lignes.filter(
                Q(espace__batiment__site__in=sites)
                | Q(pret__stock__site__in=sites)
                | Q(occurrence__espace__batiment__site__in=sites)
            ).distinct()
        return list(LigneSerializer(lignes[:2000], many=True).data)


def _ligne_resultat(ligne: services.LigneCalculee) -> dict[str, Any]:
    return {
        "nature": ligne.nature,
        "libelle": ligne.libelle,
        "methode": ligne.methode,
        "quantite": ligne.quantite,
        "part": ligne.part,
        "montant_reference": ligne.montant_reference,
        "montant_paye": ligne.montant_paye,
        "montant_valorise": ligne.montant_valorise,
        "observation": ligne.observation,
    }


def _etat_attestation(valorisation: Valorisation | None) -> str | None:
    if valorisation is None or not valorisation.document_id:
        return None
    return "deposee" if valorisation.deposee_le else "en_signature"


class VueExercices(VuePerimetre):
    """VAL-02, VAL-05 à VAL-08 : exercices, calcul, clôture, synthèse avec alertes de seuil, annexe, simulation."""

    queryset = Exercice.objects.all()
    serializer_class = ExerciceSerializer
    actions_requises = {
        "lecture": "lire_valorisation",
        "ecriture": "calculer_valorisation",
        "calculer": "calculer_valorisation",
        "cloturer": "cloturer_valorisation",
        "synthese": "lire_valorisation",
        "annexe": "lire_valorisation",
        "subventions": "calculer_valorisation",
        "simulation": "calculer_valorisation",
    }
    http_method_names = ["get", "post", "patch", "head", "options"]

    @extend_schema(
        request={"application/json": {"type": "object", "properties": {"usager": {"type": "integer"}}}}, responses={200: dict}
    )
    @action(detail=True, methods=["post"])
    def calculer(self, request: Request, pk: str | None = None) -> Response:
        """Calcul d'un bénéficiaire (nouvelle version), ou de tous ; refusé sur un exercice clos (VAL-08)."""
        exercice = self.get_object()
        acteur = agent_courant(request)
        identifiant = request.data.get("usager") if isinstance(request.data, dict) else None
        if identifiant:
            usager = Usager.objects.filter(pk=int(identifiant)).first() if str(identifiant).isdecimal() else None
            if usager is None or usager.type in services.TYPES_EXCLUS:
                raise ErreurValidation("Bénéficiaire inconnu ou non valorisé (D-061).", code="usager_inconnu")
            valorisation = services.valoriser(usager, exercice, acteur=acteur)
            return Response(ValorisationSerializer(valorisation).data)
        return Response(services.valoriser_exercice(exercice, acteur=acteur))

    @extend_schema(request=None, responses=ExerciceSerializer)
    @action(detail=True, methods=["post"])
    def cloturer(self, request: Request, pk: str | None = None) -> Response:
        return Response(ExerciceSerializer(services.cloturer(self.get_object(), acteur=agent_courant(request))).data)

    @extend_schema(responses={200: dict})
    @action(detail=True, methods=["get"])
    def synthese(self, request: Request, pk: str | None = None) -> Response:
        """VAL-05, VAL-06 : par bénéficiaire, concours en nature et en numéraire, alertes de seuil."""
        convention, compte_rendu = services.seuils()
        return Response(
            {
                "seuils": {"convention": convention, "compte_rendu": compte_rendu},
                "lignes": [
                    {
                        "usager": ligne["usager"].pk,
                        "usager_nom": ligne["usager"].nom,
                        "usager_type": ligne["usager"].type,
                        "valorisation": ligne["valorisation"].pk if ligne["valorisation"] else None,
                        "nature": ligne["nature"],
                        "numeraire": ligne["numeraire"],
                        "total": ligne["total"],
                        "alertes": ligne["alertes"],
                        "attestation": _etat_attestation(ligne["valorisation"]),
                        "figee": bool(ligne["valorisation"] and ligne["valorisation"].figee),
                    }
                    for ligne in services.synthese(self.get_object())
                ],
            }
        )

    @extend_schema(responses={(200, "text/csv"): bytes})
    @action(detail=True, methods=["get"])
    def annexe(self, request: Request, pk: str | None = None) -> HttpResponse:
        """VAL-05 : état annexé au compte administratif (tableur)."""
        exercice = self.get_object()
        from apps.audit.services import journaliser

        journaliser("exporter_annexe_valorisation", exercice, acteur=agent_courant(request))
        reponse = HttpResponse(services.annexe_csv(exercice), content_type="text/csv; charset=utf-8")
        reponse["Content-Disposition"] = f'attachment; filename="annexe-concours-{exercice.annee}.csv"'
        return reponse

    @extend_schema(
        request={"multipart/form-data": {"type": "object", "properties": {"fichier": {"type": "string", "format": "binary"}}}},
        responses={200: dict},
    )
    @action(detail=True, methods=["post"], parser_classes=[MultiPartParser])
    def subventions(self, request: Request, pk: str | None = None) -> Response:
        """VAL-06 : import des subventions en numéraire (CSV issu du logiciel financier)."""
        fichier = request.FILES.get("fichier")
        if fichier is None:
            raise ErreurValidation("Joignez le fichier des subventions.", code="fichier_absent")
        if fichier.size and fichier.size > 2_000_000:
            raise ErreurValidation("Fichier trop volumineux (2 Mo au plus).", code="fichier_trop_gros")
        donnees = request.data if isinstance(request.data, dict) else {}
        confirmer = str(donnees.get("confirmer", "")).lower() in {"1", "true", "oui"}
        return Response(
            services.importer_subventions(
                self.get_object(), fichier.read(2_000_001), acteur=agent_courant(request), confirmer=confirmer
            )
        )

    @extend_schema(parameters=[OpenApiParameter("usager", int), OpenApiParameter("jusqu_au", str)], responses={200: dict})
    @action(detail=True, methods=["get"])
    def simulation(self, request: Request, pk: str | None = None) -> Response:
        """VAL-07 : simulation en cours d'année (rien n'est enregistré)."""
        exercice = self.get_object()
        identifiant = request.query_params.get("usager", "")
        usager = Usager.objects.filter(pk=int(identifiant)).first() if identifiant.isdecimal() else None
        if usager is None or usager.type in services.TYPES_EXCLUS:
            raise ErreurValidation("Choisissez le bénéficiaire (associations, écoles, entreprises).", code="usager_inconnu")
        try:
            jusqu_au = (
                date.fromisoformat(request.query_params.get("jusqu_au", "")) if request.query_params.get("jusqu_au") else None
            )
        except ValueError as erreur:
            raise ErreurValidation("Date au format AAAA-MM-JJ.", code="date_invalide") from erreur
        resultat = services.calculer(usager, exercice, jusqu_au=jusqu_au)
        return Response(
            {
                "usager": usager.pk,
                "usager_nom": usager.nom,
                "jusqu_au": resultat.jusqu_au,
                "montant_espaces": resultat.somme("espace"),
                "montant_materiel": resultat.somme("materiel"),
                "montant_personnel": resultat.somme("personnel"),
                "total": resultat.total,
                "anomalies": resultat.anomalies,
                "lignes": [_ligne_resultat(ligne) for ligne in resultat.lignes[:2000]],
            }
        )


class VueMethodes(VuePerimetre):
    """VAL-01 : méthode par famille d'espaces et par exercice."""

    queryset = MethodeValorisation.objects.select_related("exercice", "famille")
    serializer_class = MethodeSerializer
    actions_requises = {"lecture": "lire_valorisation", "ecriture": "calculer_valorisation"}
    filterset_fields = ["exercice", "famille"]
    http_method_names = ["get", "post", "patch", "head", "options"]


class VueValorisations(VuePerimetre):
    """VAL-02, VAL-04, VAL-08 : versions calculées, détail des lignes, attestation, recalcul après clôture."""

    queryset = Valorisation.objects.select_related("exercice", "usager")
    serializer_class = ValorisationSerializer
    actions_requises = {
        "lecture": "lire_valorisation",
        "attestation": "calculer_valorisation",
        "recalculer": "cloturer_valorisation",
    }
    filterset_fields = ["exercice", "usager", "actuelle"]
    http_method_names = ["get", "post", "head", "options"]

    def get_serializer_context(self) -> dict[str, Any]:
        from apps.habilitations.services import sites_autorises

        contexte = {**super().get_serializer_context(), "detail": self.action == "retrieve"}
        if self.action == "retrieve":
            contexte["sites"] = sites_autorises(agent_courant(self.request), "lire_valorisation")
        return contexte

    def create(self, request: Request, *args: Any, **kwargs: Any) -> Response:
        return Response({"code": "non_autorise", "message": "Une valorisation se calcule depuis l'exercice."}, status=405)

    @extend_schema(request=None, responses=ValorisationSerializer)
    @action(detail=True, methods=["post"])
    def attestation(self, request: Request, pk: str | None = None) -> Response:
        """VAL-04 : attestation PDF/A de la version actuelle, déposée sur le portail de l'association."""
        valorisation = services.editer_attestation(self.get_object(), acteur=agent_courant(request))
        return Response(ValorisationSerializer(valorisation).data)

    @extend_schema(
        request={"application/json": {"type": "object", "properties": {"motif": {"type": "string"}}}},
        responses=ValorisationSerializer,
    )
    @action(detail=True, methods=["post"])
    def recalculer(self, request: Request, pk: str | None = None) -> Response:
        """VAL-08 : procédure tracée de recalcul d'un exercice clos (motif obligatoire)."""
        motif = str(request.data.get("motif", "")) if isinstance(request.data, dict) else ""
        valorisation = services.recalculer_apres_cloture(self.get_object(), acteur=agent_courant(request), motif=motif)
        return Response(ValorisationSerializer(valorisation).data, status=status.HTTP_201_CREATED)


class SubventionSerializer(serializers.ModelSerializer):
    usager_nom = serializers.CharField(source="usager.nom", read_only=True)

    class Meta:
        model = SubventionNumeraire
        fields = [
            "id",
            "exercice",
            "usager",
            "usager_nom",
            "montant_centimes",
            "objet",
            "deliberation_reference",
            "reference_import",
            "importe_le",
        ]
        read_only_fields = ["reference_import", "importe_le"]

    def validate_exercice(self, exercice: Exercice) -> Exercice:
        if exercice.statut == "cloture":
            raise serializers.ValidationError("Exercice clôturé.")
        return exercice


class VueSubventions(VuePerimetre):
    """VAL-06 : subventions en numéraire (importées ou saisies)."""

    queryset = SubventionNumeraire.objects.select_related("usager", "exercice")
    serializer_class = SubventionSerializer
    actions_requises = {"lecture": "lire_valorisation", "ecriture": "calculer_valorisation"}
    filterset_fields = ["exercice", "usager"]
    http_method_names = ["get", "post", "head", "options"]

    def perform_create(self, serializer: Any) -> None:
        if serializer.validated_data["exercice"].statut == "cloture":
            raise ErreurMetier("Exercice clôturé.", code="exercice_cloture")
        if serializer.validated_data["usager"].type in services.TYPES_EXCLUS:
            raise ErreurValidation("Ce bénéficiaire n'est pas valorisé (D-061).", code="beneficiaire_exclu")
        super().perform_create(serializer)


routeur = SimpleRouter(trailing_slash=False)
routeur.register("valorisation/exercices", VueExercices, basename="exercices-valorisation")
routeur.register("valorisation/methodes", VueMethodes, basename="methodes-valorisation")
routeur.register("valorisation/valorisations", VueValorisations, basename="valorisations")
routeur.register("valorisation/subventions", VueSubventions, basename="subventions-numeraire")
urlpatterns = routeur.urls
