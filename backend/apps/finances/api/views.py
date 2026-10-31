"""API de gestion des finances : grilles, tarifs, majorations, prestations, réductions (TAR-01 à TAR-03), devis,
factures, acomptes, avoirs (TAR-04, TAR-05, TAR-09), titres Ciril (TAR-06), encaissements (TAR-13), retards
(TAR-10), cautions et états des lieux (CAU-01 à CAU-07)."""

from __future__ import annotations

from typing import Any

from django.db import transaction
from django.db.models import QuerySet
from django.http import FileResponse, HttpResponse
from django.utils import timezone
from drf_spectacular.utils import extend_schema, extend_schema_serializer
from rest_framework import serializers, status
from rest_framework.decorators import action
from rest_framework.exceptions import NotFound
from rest_framework.parsers import JSONParser, MultiPartParser
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.audit.services import journaliser
from apps.habilitations.authentification import agent_courant
from apps.habilitations.services import peut, sites_autorises
from apps.noyau import fichiers
from apps.noyau.api import VuePerimetre
from apps.noyau.exceptions import ErreurMetier, ErreurValidation
from apps.referentiel.models import Espace
from apps.reservations.models import Dossier, Occurrence
from apps.usagers.models import Usager

from .. import cautions as services_cautions
from .. import facturation, tarification, titres
from ..ciril import encaissements
from ..models import (
    Caution,
    EtatDesLieux,
    GrilleTarifaire,
    ImportEncaissements,
    LigneComptable,
    LotTitres,
    Majoration,
    PieceComptable,
    Prestation,
    Reduction,
    Tarif,
)

DROITS_TARIFS = {"lecture": "lire_finances", "ecriture": "gerer_tarifs"}


class GrilleSerializer(serializers.ModelSerializer):
    class Meta:
        model = GrilleTarifaire
        fields = ["id", "nom", "debut", "fin", "deliberation_reference", "deliberation_date", "statut", "heure_soiree", "cree_le"]
        read_only_fields = ["statut", "cree_le"]


class VueGrilles(VuePerimetre):
    """TAR-01 : une grille se prépare, puis est votée (délibération obligatoire) ; votée, elle ne se modifie plus."""

    queryset = GrilleTarifaire.objects.all()
    serializer_class = GrilleSerializer
    actions_requises = {**DROITS_TARIFS, "voter": "gerer_tarifs", "archiver": "gerer_tarifs", "dupliquer": "gerer_tarifs"}
    http_method_names = ["get", "post", "patch", "head", "options"]

    def perform_update(self, serializer: Any) -> None:
        if serializer.instance.statut != "brouillon":
            raise ErreurMetier(
                "Une grille votée ne se modifie plus : dupliquez-la pour préparer la suivante.", code="grille_votee"
            )
        super().perform_update(serializer)

    @extend_schema(request=None, responses=GrilleSerializer)
    @action(detail=True, methods=["post"])
    def voter(self, request: Request, pk: str | None = None) -> Response:
        grille = self.get_object()
        if grille.statut != "brouillon":
            raise ErreurMetier("Cette grille est déjà votée.", code="grille_votee")
        if not grille.deliberation_reference.strip() or grille.deliberation_date is None:
            raise ErreurValidation(
                "Indiquez la référence et la date de la délibération avant de déclarer la grille votée.",
                code="deliberation_requise",
            )
        if not grille.tarifs.exists():
            raise ErreurValidation("Une grille sans tarif ne peut pas être votée.", code="grille_vide")
        with transaction.atomic():
            grille.statut = "votee"
            grille.save(update_fields=["statut"])
            journaliser(
                "voter_grille", grille, apres={"deliberation": grille.deliberation_reference}, acteur=agent_courant(request)
            )
        return Response(GrilleSerializer(grille).data)

    @extend_schema(request=None, responses=GrilleSerializer)
    @action(detail=True, methods=["post"])
    def archiver(self, request: Request, pk: str | None = None) -> Response:
        """Une grille ne s'archive qu'au terme de sa période (elle reste la référence des pièces de cette période)."""
        grille = self.get_object()
        if grille.statut != "votee" or grille.fin is None or grille.fin >= timezone.localdate():
            raise ErreurMetier(
                "Seule une grille votée dont la période est achevée s'archive : fixez d'abord sa date de fin.",
                code="grille_en_vigueur",
            )
        with transaction.atomic():
            grille.statut = "archivee"
            grille.save(update_fields=["statut"])
            journaliser("archiver_grille", grille, acteur=agent_courant(request))
        return Response(GrilleSerializer(grille).data)

    @extend_schema(request=None, responses=GrilleSerializer)
    @action(detail=True, methods=["post"])
    def dupliquer(self, request: Request, pk: str | None = None) -> Response:
        """Prépare la grille suivante à partir d'une grille existante (tarifs, majorations, prestations copiés)."""
        source = self.get_object()
        with transaction.atomic():
            copie = GrilleTarifaire.objects.create(
                nom=f"{source.nom} (copie)", debut=timezone.localdate(), heure_soiree=source.heure_soiree, statut="brouillon"
            )
            for tarif in source.tarifs.all():
                tarif.pk, tarif.grille = None, copie
                tarif.save()
            for majoration in source.majorations.all():
                majoration.pk, majoration.grille = None, copie
                majoration.save()
            for prestation in source.prestations.all():
                prestation.pk, prestation.grille = None, copie
                prestation.save()
            journaliser("dupliquer_grille", copie, apres={"source": source.pk}, acteur=agent_courant(request))
        return Response(GrilleSerializer(copie).data, status=status.HTTP_201_CREATED)


class _VueContenuGrille(VuePerimetre):
    """Le contenu d'une grille votée est figé (RG-04 : les devis et factures s'y réfèrent)."""

    actions_requises = DROITS_TARIFS
    filterset_fields = ["grille"]

    def _verifier_grille(self, grille: GrilleTarifaire) -> None:
        if grille.statut != "brouillon":
            raise ErreurMetier("La grille est votée : son contenu ne se modifie plus.", code="grille_votee")

    def perform_create(self, serializer: Any) -> None:
        self._verifier_grille(serializer.validated_data["grille"])
        super().perform_create(serializer)

    def perform_update(self, serializer: Any) -> None:
        self._verifier_grille(serializer.instance.grille)
        if "grille" in serializer.validated_data:
            self._verifier_grille(serializer.validated_data["grille"])
        super().perform_update(serializer)

    def perform_destroy(self, instance: Any) -> None:
        self._verifier_grille(instance.grille)
        super().perform_destroy(instance)


class TarifSerializer(serializers.ModelSerializer):
    espace_nom = serializers.CharField(source="espace.nom", read_only=True, default="")
    famille_libelle = serializers.CharField(source="famille.libelle", read_only=True, default="")

    class Meta:
        model = Tarif
        fields = [
            "id",
            "grille",
            "espace",
            "espace_nom",
            "famille",
            "famille_libelle",
            "categorie",
            "unite",
            "prix_centimes",
            "caution_centimes",
        ]

    def validate_prix_centimes(self, valeur: int) -> int:
        if valeur < 1:
            raise serializers.ValidationError(
                "RG-05 : le tarif de référence n'est jamais nul ; une gratuité est une réduction de 100 %."
            )
        return valeur

    def validate(self, donnees: dict[str, Any]) -> dict[str, Any]:
        espace = donnees.get("espace", getattr(self.instance, "espace", None))
        famille = donnees.get("famille", getattr(self.instance, "famille", None))
        if bool(espace) == bool(famille):
            raise serializers.ValidationError("Le tarif porte sur un espace ou sur une famille d'espaces (l'un des deux).")
        return donnees


class VueTarifs(_VueContenuGrille):
    queryset = Tarif.objects.select_related("espace", "famille", "grille")
    serializer_class = TarifSerializer
    filterset_fields = ["grille", "espace", "famille", "categorie"]


class MajorationSerializer(serializers.ModelSerializer):
    class Meta:
        model = Majoration
        fields = ["id", "grille", "nature", "taux", "categories"]

    def validate_taux(self, valeur: int) -> int:
        if not 0 < valeur <= 10000:
            raise serializers.ValidationError("Taux entre 0,01 % et 100 % (dix-millièmes : 1 à 10000).")
        return valeur


class VueMajorations(_VueContenuGrille):
    queryset = Majoration.objects.all()
    serializer_class = MajorationSerializer


class PrestationSerializer(serializers.ModelSerializer):
    class Meta:
        model = Prestation
        fields = ["id", "grille", "code", "libelle", "unite", "prix_centimes"]


class VuePrestations(_VueContenuGrille):
    queryset = Prestation.objects.all()
    serializer_class = PrestationSerializer


class ReductionSerializer(serializers.ModelSerializer):
    usager_nom = serializers.CharField(source="usager.nom", read_only=True)

    class Meta:
        model = Reduction
        fields = ["id", "usager", "usager_nom", "type_reservation", "taux", "fondement", "debut", "fin", "cree_le"]
        read_only_fields = ["cree_le"]

    def validate(self, donnees: dict[str, Any]) -> dict[str, Any]:
        if self.instance is not None and set(donnees) - {"fin"}:
            raise serializers.ValidationError("Une réduction accordée ne se modifie plus : seule sa date de fin peut être fixée.")
        if self.instance is not None:
            return donnees
        tarification.verifier_reduction(
            donnees.get("taux", getattr(self.instance, "taux", 0)),
            donnees.get("fondement", getattr(self.instance, "fondement", "")),
        )
        return donnees


class VueReductions(VuePerimetre):
    """TAR-03, RG-05 : gratuité ou réduction, toujours fondée (délibération, convention)."""

    queryset = Reduction.objects.select_related("usager")
    serializer_class = ReductionSerializer
    actions_requises = DROITS_TARIFS
    filterset_fields = ["usager", "type_reservation"]
    # Une réduction appliquée fonde des pièces émises : elle se clôt (date de fin), elle ne se supprime pas.
    http_method_names = ["get", "post", "patch", "head", "options"]

    def perform_create(self, serializer: Any) -> None:
        serializer.validated_data["cree_par"] = agent_courant(self.request)
        super().perform_create(serializer)


class LigneSerializer(serializers.ModelSerializer):
    class Meta:
        model = LigneComptable
        fields = [
            "id",
            "rang",
            "libelle",
            "nature",
            "quantite",
            "unite",
            "prix_unitaire",
            "montant_reference",
            "taux_reduction",
            "montant_du",
            "fondement",
            "occurrence",
        ]


@extend_schema_serializer(component_name="PieceComptable")
class PieceSerializer(serializers.ModelSerializer):
    lignes = LigneSerializer(many=True, read_only=True)
    usager_nom = serializers.CharField(source="usager.nom", read_only=True)
    dossier_numero = serializers.CharField(source="dossier.numero", read_only=True)
    origine_numero = serializers.CharField(source="origine.numero", read_only=True, default="")
    reste_du = serializers.IntegerField(read_only=True)
    montant_titre = serializers.IntegerField(read_only=True)

    class Meta:
        model = PieceComptable
        fields = [
            "id",
            "nature",
            "numero",
            "exercice",
            "dossier",
            "dossier_numero",
            "usager",
            "usager_nom",
            "origine",
            "origine_numero",
            "objet",
            "statut",
            "emise_le",
            "echeance",
            "validite",
            "total_reference",
            "total_du",
            "acompte_deduit",
            "montant_regle",
            "montant_avoirs",
            "montant_titre",
            "reste_du",
            "reglement",
            "motif",
            "reference_virement",
            "titre_numero",
            "titre_le",
            "solde_le",
            "accepte_le",
            "document",
            "lignes",
        ]
        read_only_fields = fields


def _pieces_lisibles(request: Request, action_requise: str) -> QuerySet[PieceComptable]:
    agent = agent_courant(request)
    qs = PieceComptable.objects.select_related("usager", "dossier", "origine").prefetch_related("lignes")
    if not peut(agent, action_requise):
        return qs.none()
    sites = sites_autorises(agent, action_requise)
    return qs if sites is None else qs.filter(dossier__reservations__espace__batiment__site__in=sites).distinct()


class PrestationDemandeeSerializer(serializers.Serializer):
    code = serializers.SlugField(max_length=40)
    quantite = serializers.IntegerField(min_value=1, max_value=999, default=1)


class DevisSerializer(serializers.Serializer):
    dossier = serializers.PrimaryKeyRelatedField(queryset=Dossier.objects.all())
    prestations = PrestationDemandeeSerializer(many=True, required=False, default=list)


class DossierSerializer(serializers.Serializer):
    dossier = serializers.PrimaryKeyRelatedField(queryset=Dossier.objects.all())
    seances = serializers.ListField(child=serializers.IntegerField(min_value=1), required=False, max_length=500)


class AvoirSerializer(serializers.Serializer):
    motif = serializers.CharField(max_length=300)
    lignes = serializers.ListField(child=serializers.IntegerField(min_value=1), required=False, default=list)


class PointageSerializer(serializers.Serializer):
    montant = serializers.IntegerField(min_value=1)
    date = serializers.DateField()
    reference = serializers.CharField(max_length=100)


class TitreSerializer(serializers.Serializer):
    titre = serializers.CharField(max_length=40)
    date = serializers.DateField(required=False)


class VuePieces(VuePerimetre):
    """Devis, factures, acomptes, avoirs : lecture dans le périmètre des dossiers ; écritures par les services."""

    queryset = PieceComptable.objects.none()
    serializer_class = PieceSerializer
    actions_requises = {
        "lecture": "lire_finances",
        "list": "lire_finances",
        "retrieve": "lire_finances",
        "devis": "emettre_facture",
        "accepter": "emettre_facture",
        "acompte": "emettre_facture",
        "facturer": "emettre_facture",
        "avoir": "emettre_avoir",
        "pointer": "encaisser",
        "titre": "exporter_titres",
        "retards": "lire_finances",
        "fichier": "lire_finances",
    }
    http_method_names = ["get", "post", "head", "options"]
    filterset_fields = ["nature", "statut", "dossier", "usager", "exercice"]

    def get_queryset(self) -> QuerySet[PieceComptable]:
        if getattr(self, "swagger_fake_view", False):
            return PieceComptable.objects.none()
        return _pieces_lisibles(self.request, "lire_finances").order_by("-cree_le")

    def create(self, request: Request, *args: Any, **kwargs: Any) -> Response:
        return Response({"code": "non_autorise", "message": "Utilisez « devis », « facturer » ou « acompte »."}, status=405)

    def _piece(self) -> PieceComptable:
        identifiant = str(self.kwargs.get("pk", ""))
        piece = self.get_queryset().filter(pk=identifiant).first() if identifiant.isdigit() else None
        if piece is None:
            raise NotFound()
        return piece

    def _repondre(self, piece: PieceComptable, statut: int = status.HTTP_200_OK) -> Response:
        return Response(PieceSerializer(PieceComptable.objects.prefetch_related("lignes").get(pk=piece.pk)).data, status=statut)

    @extend_schema(request=DevisSerializer, responses=PieceSerializer)
    @action(detail=False, methods=["post"])
    def devis(self, request: Request) -> Response:
        entree = DevisSerializer(data=request.data)
        entree.is_valid(raise_exception=True)
        piece = facturation.etablir_devis(
            entree.validated_data["dossier"], acteur=agent_courant(request), prestations=entree.validated_data["prestations"]
        )
        return self._repondre(piece, status.HTTP_201_CREATED)

    @extend_schema(request=None, responses=PieceSerializer)
    @action(detail=True, methods=["post"])
    def accepter(self, request: Request, pk: str | None = None) -> Response:
        """Acceptation enregistrée par un agent (devis signé reçu au guichet)."""
        return self._repondre(facturation.accepter_devis(self._piece(), acteur=agent_courant(request)))

    @extend_schema(request=DossierSerializer, responses=PieceSerializer)
    @action(detail=False, methods=["post"])
    def acompte(self, request: Request) -> Response:
        entree = DossierSerializer(data=request.data)
        entree.is_valid(raise_exception=True)
        return self._repondre(
            facturation.facturer_acompte(entree.validated_data["dossier"], acteur=agent_courant(request)), status.HTTP_201_CREATED
        )

    @extend_schema(request=DossierSerializer, responses=PieceSerializer)
    @action(detail=False, methods=["post"])
    def facturer(self, request: Request) -> Response:
        entree = DossierSerializer(data=request.data)
        entree.is_valid(raise_exception=True)
        dossier = entree.validated_data["dossier"]
        seances = None
        if entree.validated_data.get("seances"):
            seances = list(Occurrence.objects.filter(pk__in=entree.validated_data["seances"], reservation__dossier=dossier))
        return self._repondre(
            facturation.facturer(dossier, acteur=agent_courant(request), occurrences=seances), status.HTTP_201_CREATED
        )

    @extend_schema(request=AvoirSerializer, responses=PieceSerializer)
    @action(detail=True, methods=["post"])
    def avoir(self, request: Request, pk: str | None = None) -> Response:
        entree = AvoirSerializer(data=request.data)
        entree.is_valid(raise_exception=True)
        avoir = facturation.emettre_avoir(
            self._piece(),
            acteur=agent_courant(request),
            motif=entree.validated_data["motif"],
            lignes=entree.validated_data["lignes"] or None,
        )
        return self._repondre(avoir, status.HTTP_201_CREATED)

    @extend_schema(request=PointageSerializer, responses=PieceSerializer)
    @action(detail=True, methods=["post"])
    def pointer(self, request: Request, pk: str | None = None) -> Response:
        entree = PointageSerializer(data=request.data)
        entree.is_valid(raise_exception=True)
        d = entree.validated_data
        return self._repondre(
            facturation.pointer(
                self._piece(), acteur=agent_courant(request), montant=d["montant"], jour=d["date"], reference=d["reference"]
            )
        )

    @extend_schema(request=TitreSerializer, responses=PieceSerializer)
    @action(detail=True, methods=["post"])
    def titre(self, request: Request, pk: str | None = None) -> Response:
        entree = TitreSerializer(data=request.data)
        entree.is_valid(raise_exception=True)
        piece = titres.reporter_titre(
            self._piece(),
            acteur=agent_courant(request),
            titre=entree.validated_data["titre"],
            jour=entree.validated_data.get("date"),
        )
        return self._repondre(piece)

    @extend_schema(responses=PieceSerializer(many=True))
    @action(detail=False, methods=["get"])
    def retards(self, request: Request) -> Response:
        """TAR-10 : factures non soldées après l'échéance, dans le périmètre de l'agent."""
        retards = facturation.en_retard().filter(pk__in=self.get_queryset().values("pk"))
        return Response(PieceSerializer(retards[:500], many=True).data)

    @extend_schema(responses={(200, "application/pdf"): bytes})
    @action(detail=True, methods=["get"])
    def fichier(self, request: Request, pk: str | None = None) -> FileResponse:
        piece = self._piece()
        if piece.document is None:
            raise ErreurMetier("Aucun document PDF pour cette pièce.", code="fichier_absent")
        journaliser("telecharger_piece_comptable", piece, acteur=agent_courant(request))
        return fichiers.reponse_telechargement(piece.document.fichier_courant)  # type: ignore[arg-type]


class LotTitresSerializer(serializers.ModelSerializer):
    pieces = serializers.SerializerMethodField()

    class Meta:
        model = LotTitres
        fields = ["id", "numero", "format", "pieces", "total_centimes", "cree_le", "annule_le", "motif_annulation"]

    def get_pieces(self, lot: LotTitres) -> list[str]:
        return sorted(str(n) for n in lot.numeros) if lot.numeros else sorted(p.numero or "" for p in lot.pieces.all())


class ExportSerializer(serializers.Serializer):
    pieces = serializers.ListField(child=serializers.IntegerField(min_value=1), required=False, default=list, max_length=1000)
    format = serializers.ChoiceField(choices=["csv", "xlsx", "xml"], required=False)


class VueLotsTitres(VuePerimetre):
    """TAR-06 : lots d'export vers Ciril, rejouables (le fichier du lot est conservé à l'identique)."""

    queryset = LotTitres.objects.prefetch_related("pieces")
    serializer_class = LotTitresSerializer
    actions_requises = {
        "lecture": "exporter_titres",
        "ecriture": "exporter_titres",
        "a_titrer": "exporter_titres",
        "fichier": "exporter_titres",
        "annuler": "exporter_titres",
    }
    http_method_names = ["get", "post", "head", "options"]

    def initial(self, request: Request, *args: Any, **kwargs: Any) -> None:
        super().initial(request, *args, **kwargs)
        titres.exiger_ville_entiere(agent_courant(request), "exporter_titres")

    @extend_schema(responses=PieceSerializer(many=True))
    @action(detail=False, methods=["get"], url_path="a-titrer")
    def a_titrer(self, request: Request) -> Response:
        return Response(PieceSerializer(titres.a_titrer()[:1000], many=True).data)

    @extend_schema(
        request={"application/json": {"type": "object", "properties": {"motif": {"type": "string"}}}},
        responses=LotTitresSerializer,
    )
    @action(detail=True, methods=["post"])
    def annuler(self, request: Request, pk: str | None = None) -> Response:
        """TAR-06 : lot rejeté par Ciril ; ses pièces redeviennent à exporter, le fichier reste consultable."""
        motif = str(request.data.get("motif", "")) if isinstance(request.data, dict) else ""
        return Response(
            LotTitresSerializer(titres.annuler_lot(self.get_object(), acteur=agent_courant(request), motif=motif)).data
        )

    @extend_schema(request=ExportSerializer, responses=LotTitresSerializer)
    def create(self, request: Request, *args: Any, **kwargs: Any) -> Response:
        entree = ExportSerializer(data=request.data)
        entree.is_valid(raise_exception=True)
        candidates = titres.a_titrer()
        if entree.validated_data["pieces"]:
            candidates = candidates.filter(pk__in=entree.validated_data["pieces"])
        lot = titres.exporter(list(candidates), acteur=agent_courant(request), format_export=entree.validated_data.get("format"))
        return Response(LotTitresSerializer(lot).data, status=status.HTTP_201_CREATED)

    @extend_schema(responses={(200, "application/octet-stream"): bytes})
    @action(detail=True, methods=["get"])
    def fichier(self, request: Request, pk: str | None = None) -> FileResponse:
        lot = self.get_object()
        journaliser("telecharger_lot_titres", lot, acteur=agent_courant(request))
        return fichiers.reponse_telechargement(lot.fichier)


class ImportSerializer(serializers.ModelSerializer):
    class Meta:
        model = ImportEncaissements
        fields = ["id", "lignes_lues", "rapprochees", "rejets", "cree_le"]


class DepotImportSerializer(serializers.Serializer):
    fichier = serializers.FileField()


class VueImportsEncaissements(VuePerimetre):
    """TAR-13 : import de l'état des titres soldés (CSV ou XLSX exporté de Ciril)."""

    queryset = ImportEncaissements.objects.all()
    serializer_class = ImportSerializer
    actions_requises = {"lecture": "encaisser", "ecriture": "encaisser"}
    http_method_names = ["get", "post", "head", "options"]
    parser_classes = [MultiPartParser]

    @extend_schema(request={"multipart/form-data": DepotImportSerializer}, responses=ImportSerializer)
    def create(self, request: Request, *args: Any, **kwargs: Any) -> Response:
        entree = DepotImportSerializer(data=request.data)
        entree.is_valid(raise_exception=True)
        televerse = entree.validated_data["fichier"]
        if televerse.size is None or televerse.size > fichiers.TAILLE_MAX:
            raise ErreurValidation("Le fichier est trop volumineux.", code="fichier_trop_gros")
        lot = encaissements.importer(televerse.name or "etat.csv", televerse.read(), acteur=agent_courant(request))
        return Response(ImportSerializer(lot).data, status=status.HTTP_201_CREATED)


class CautionSerializer(serializers.ModelSerializer):
    usager_nom = serializers.CharField(source="usager.nom", read_only=True)
    dossier_numero = serializers.CharField(source="dossier.numero", read_only=True)
    espace_nom = serializers.CharField(source="reservation.espace.nom", read_only=True)
    fin_occupation = serializers.DateField(source="reservation.date_fin", read_only=True)
    mouvements = serializers.SerializerMethodField()
    derniere_seance = serializers.SerializerMethodField()
    etat_sortie = serializers.SerializerMethodField()
    photos_retenue = serializers.SerializerMethodField()

    class Meta:
        model = Caution
        fields = [
            "id",
            "dossier",
            "dossier_numero",
            "reservation",
            "usager",
            "usager_nom",
            "espace_nom",
            "fin_occupation",
            "montant",
            "statut",
            "mode",
            "reference",
            "recue_le",
            "montant_retenu",
            "motif_retenue",
            "restituee_le",
            "mouvements",
            "derniere_seance",
            "etat_sortie",
            "photos_retenue",
        ]
        read_only_fields = fields

    def get_photos_retenue(self, caution: Caution) -> list[int]:
        return [f.pk for f in caution.photos_retenue.all()]

    def get_derniere_seance(self, caution: Caution) -> int | None:
        derniere = caution.reservation.occurrences.exclude(statut__in=["annulee", "refusee"]).order_by("-debut").first()
        return derniere.pk if derniere else None

    def get_etat_sortie(self, caution: Caution) -> str | None:
        etat = services_cautions.etat_de_sortie(caution)
        return etat.constat if etat else None

    def get_mouvements(self, caution: Caution) -> list[dict[str, Any]]:
        return [
            {
                "action": m.action,
                "de": m.statut_avant,
                "vers": m.statut_apres,
                "montant": m.montant,
                "motif": m.motif,
                "agent": m.agent,
                "le": m.le,
            }
            for m in caution.mouvements.all()
        ]


class ReceptionSerializer(serializers.Serializer):
    mode = serializers.ChoiceField(choices=[m for m, _ in Caution.MODES])
    reference = serializers.CharField(max_length=100)
    date = serializers.DateField(required=False)


class RetenueSerializer(serializers.Serializer):
    montant = serializers.IntegerField(min_value=1)
    motif = serializers.CharField(max_length=2000)
    photos = serializers.ListField(child=serializers.FileField(), max_length=10)


class ValidationRetenueSerializer(serializers.Serializer):
    accepter = serializers.BooleanField()
    commentaire = serializers.CharField(max_length=500, required=False, allow_blank=True, default="")


def enregistrer_photos(televerses: list[Any], agent: Any) -> list[Any]:
    """Photos contrôlées (type réel, ClamAV) et débarrassées des métadonnées EXIF (géolocalisation)."""
    return [
        fichiers.enregistrer(
            p.name or "photo.jpg",
            fichiers.sans_metadonnees(p.read()),
            types_autorises=("image/jpeg", "image/png"),
            depose_par=str(agent),
        )
        for p in televerses
    ]


class VueCautions(VuePerimetre):
    queryset = Caution.objects.select_related("usager", "dossier", "reservation__espace").prefetch_related("mouvements")
    serializer_class = CautionSerializer
    chemin_site = "reservation__espace__batiment__site"
    actions_requises = {
        "lecture": "lire_finances",
        "list": "lire_finances",
        "retrieve": "lire_finances",
        "recevoir": "gerer_caution",
        "restituer": "gerer_caution",
        "retenue": "proposer_retenue",
        "valider_retenue": "valider_retenue",
        "encaisser": "gerer_caution",
        "alertes": "lire_finances",
        "export": "lire_finances",
        "photo": "lire_finances",
    }
    http_method_names = ["get", "post", "head", "options"]
    filterset_fields = ["statut", "dossier", "usager"]

    def create(self, request: Request, *args: Any, **kwargs: Any) -> Response:
        return Response(
            {"code": "non_autorise", "message": "Les cautions naissent de la validation des réservations."}, status=405
        )

    def _repondre(self, caution: Caution) -> Response:
        return Response(CautionSerializer(Caution.objects.get(pk=caution.pk)).data)

    @extend_schema(request=ReceptionSerializer, responses=CautionSerializer)
    @action(detail=True, methods=["post"], parser_classes=[JSONParser])
    def recevoir(self, request: Request, pk: str | None = None) -> Response:
        entree = ReceptionSerializer(data=request.data)
        entree.is_valid(raise_exception=True)
        d = entree.validated_data
        return self._repondre(
            services_cautions.recevoir(
                self.get_object(), acteur=agent_courant(request), mode=d["mode"], reference=d["reference"], jour=d.get("date")
            )
        )

    @extend_schema(request=None, responses=CautionSerializer)
    @action(detail=True, methods=["post"])
    def restituer(self, request: Request, pk: str | None = None) -> Response:
        return self._repondre(services_cautions.restituer(self.get_object(), acteur=agent_courant(request)))

    @extend_schema(request={"multipart/form-data": RetenueSerializer}, responses=CautionSerializer)
    @action(detail=True, methods=["post"], parser_classes=[MultiPartParser])
    def retenue(self, request: Request, pk: str | None = None) -> Response:
        entree = RetenueSerializer(data=request.data)
        entree.is_valid(raise_exception=True)
        agent = agent_courant(request)
        caution = self.get_object()  # contrôle d'objet avant tout enregistrement de fichier
        if caution.statut not in {"recue", "restituable"}:
            raise ErreurMetier("Une retenue se propose sur une caution reçue, avant toute décision.", code="transition_caution")
        photos = enregistrer_photos(entree.validated_data["photos"], agent)
        caution = services_cautions.proposer_retenue(
            caution,
            acteur=agent,
            montant=entree.validated_data["montant"],
            motif=entree.validated_data["motif"],
            photos=photos,
        )
        return self._repondre(caution)

    @extend_schema(request=ValidationRetenueSerializer, responses=CautionSerializer)
    @action(detail=True, methods=["post"], url_path="valider-retenue", parser_classes=[JSONParser])
    def valider_retenue(self, request: Request, pk: str | None = None) -> Response:
        entree = ValidationRetenueSerializer(data=request.data)
        entree.is_valid(raise_exception=True)
        return self._repondre(
            services_cautions.valider_retenue(self.get_object(), acteur=agent_courant(request), **entree.validated_data)
        )

    @extend_schema(
        request={"application/json": {"type": "object", "properties": {"reference": {"type": "string"}}}},
        responses=CautionSerializer,
    )
    @action(detail=True, methods=["post"], parser_classes=[JSONParser])
    def encaisser(self, request: Request, pk: str | None = None) -> Response:
        reference = str(request.data.get("reference", "")) if isinstance(request.data, dict) else ""
        return self._repondre(
            services_cautions.encaisser_retenue(self.get_object(), acteur=agent_courant(request), reference=reference)
        )

    @extend_schema(responses={(200, "image/jpeg"): bytes})
    @action(detail=True, methods=["get"], url_path=r"photos/(?P<photo>\d+)")
    def photo(self, request: Request, pk: str | None = None, photo: str = "") -> FileResponse:
        """CAU-05 : le second agent examine les photos de la retenue avant de statuer."""
        caution = self.get_object()
        fichier = caution.photos_retenue.filter(pk=int(photo)).first()
        if fichier is None:
            raise NotFound()
        journaliser("consulter_photo_retenue", caution, apres={"photo": fichier.pk}, acteur=agent_courant(request))
        return fichiers.reponse_telechargement(fichier, en_ligne=True)

    @extend_schema(responses=CautionSerializer(many=True))
    @action(detail=False, methods=["get"])
    def alertes(self, request: Request) -> Response:
        """CAU-07 : cautions à restituer dont le délai est dépassé."""
        return Response(
            CautionSerializer(services_cautions.en_alerte().filter(pk__in=self.get_queryset().values("pk"))[:500], many=True).data
        )

    @extend_schema(responses={(200, "text/csv"): bytes})
    @action(detail=False, methods=["get"])
    def export(self, request: Request) -> HttpResponse:
        """CAU-06 : état des cautions (tableur)."""
        journaliser("exporter_cautions", objet_type="finances.caution", objet_id="*", acteur=agent_courant(request))
        reponse = HttpResponse(
            services_cautions.etat_csv(self.filter_queryset(self.get_queryset())), content_type="text/csv; charset=utf-8"
        )
        reponse["Content-Disposition"] = f'attachment; filename="etat-cautions-{timezone.localdate():%Y%m%d}.csv"'
        return reponse


class EtatDesLieuxSerializer(serializers.ModelSerializer):
    class Meta:
        model = EtatDesLieux
        fields = ["id", "occurrence", "moment", "constat", "observations", "source", "constate_le", "cree_le"]
        read_only_fields = fields


class SaisieEtatSerializer(serializers.Serializer):
    occurrence = serializers.PrimaryKeyRelatedField(queryset=Occurrence.objects.all())
    constat = serializers.ChoiceField(choices=["conforme", "degats"])
    observations = serializers.CharField(max_length=4000, required=False, allow_blank=True, default="")
    photos = serializers.ListField(child=serializers.FileField(), required=False, default=list, max_length=10)


class VueEtatsDesLieux(VuePerimetre):
    queryset = EtatDesLieux.objects.select_related("occurrence__espace__batiment")
    serializer_class = EtatDesLieuxSerializer
    chemin_site = "occurrence__espace__batiment__site"
    actions_requises = {"lecture": "lire_finances", "ecriture": "gerer_caution"}
    http_method_names = ["get", "post", "head", "options"]
    filterset_fields = ["occurrence", "moment", "occurrence__reservation__dossier"]
    parser_classes = [MultiPartParser, JSONParser]

    @extend_schema(request={"multipart/form-data": SaisieEtatSerializer}, responses=EtatDesLieuxSerializer)
    def create(self, request: Request, *args: Any, **kwargs: Any) -> Response:
        entree = SaisieEtatSerializer(data=request.data)
        entree.is_valid(raise_exception=True)
        agent = agent_courant(request)
        d = entree.validated_data
        self._verifier_objet(d["occurrence"])  # contrôle d'objet avant tout enregistrement de fichier
        photos = enregistrer_photos(d["photos"], agent)
        etat = services_cautions.constater_sortie(
            d["occurrence"], acteur=agent, constat=d["constat"], observations=d["observations"], photos=photos
        )
        return Response(EtatDesLieuxSerializer(etat).data, status=status.HTTP_201_CREATED)


class SimulationGestionSerializer(serializers.Serializer):
    espace = serializers.PrimaryKeyRelatedField(queryset=Espace.objects.all())
    usager = serializers.PrimaryKeyRelatedField(queryset=Usager.objects.all())
    date = serializers.DateField()
    heure_debut = serializers.TimeField()
    heure_fin = serializers.TimeField()


class VueSimulationGestion(APIView):
    """TAR-11 au guichet : chiffrage d'un créneau pour un usager donné (réductions comprises)."""

    actions_requises = {"post": "lire_finances"}

    @extend_schema(request=SimulationGestionSerializer, responses={200: dict})
    def post(self, request: Request) -> Response:
        entree = SimulationGestionSerializer(data=request.data)
        entree.is_valid(raise_exception=True)
        d = entree.validated_data
        debut, fin = tarification._debut_fin(d["date"], d["heure_debut"], d["heure_fin"])
        lignes = tarification.calculer_seance(espace=d["espace"], usager=d["usager"], debut=debut, fin=fin)
        return Response(
            {
                "lignes": [
                    {
                        "libelle": ligne.libelle,
                        "reference": ligne.montant_reference,
                        "du": ligne.montant_du,
                        "reduction": ligne.taux_reduction,
                        "fondement": ligne.fondement,
                    }
                    for ligne in lignes
                ],
                "total_reference": sum(ligne.montant_reference for ligne in lignes),
                "total_du": sum(ligne.montant_du for ligne in lignes),
            }
        )
