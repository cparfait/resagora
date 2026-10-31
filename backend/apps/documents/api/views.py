"""API de gestion des modèles, documents, lots et signatures (DOC-01 à DOC-07, SIG-01 à SIG-05, ADM-04)."""

from __future__ import annotations

from typing import Any

from django.db.models import QuerySet
from django.http import FileResponse
from drf_spectacular.utils import extend_schema
from rest_framework import serializers, status
from rest_framework.decorators import action
from rest_framework.exceptions import NotFound
from rest_framework.parsers import JSONParser, MultiPartParser
from rest_framework.request import Request
from rest_framework.response import Response

from apps.audit.services import journaliser
from apps.habilitations.authentification import agent_courant
from apps.habilitations.services import peut, sites_autorises
from apps.noyau import fichiers
from apps.noyau.api import VuePerimetre
from apps.noyau.exceptions import ErreurMetier, ErreurValidation
from apps.referentiel.models import Fermeture
from apps.reservations.models import Dossier, Occurrence
from apps.usagers.models import Usager

from .. import services
from ..contexte import VARIABLES
from ..models import CircuitSignature, Document, LotGeneration, ModeleDocument, VersionModele


class VersionSerializer(serializers.ModelSerializer):
    nom_fichier = serializers.CharField(source="fichier.nom_origine", read_only=True)
    sha256 = serializers.CharField(source="fichier.sha256", read_only=True)

    class Meta:
        model = VersionModele
        fields = ["id", "numero", "nom_fichier", "sha256", "commentaire", "deposee_par", "deposee_le"]


class ModeleDocumentSerializer(serializers.ModelSerializer):
    version_active_numero = serializers.IntegerField(source="version_active.numero", read_only=True, default=None)
    variables = serializers.SerializerMethodField()

    class Meta:
        model = ModeleDocument
        fields = [
            "id",
            "code",
            "libelle",
            "nature",
            "description",
            "signature_requise",
            "signataires",
            "actif",
            "version_active",
            "version_active_numero",
            "variables",
        ]
        read_only_fields = ["code", "nature", "version_active", "version_active_numero", "variables"]

    def get_variables(self, modele: ModeleDocument) -> list[str]:
        return VARIABLES.get(modele.nature, [])

    def validate_signataires(self, valeur: list[str]) -> list[str]:
        if not isinstance(valeur, list) or any(v not in {"usager", "elu", "agent"} for v in valeur) or len(valeur) > 4:
            raise serializers.ValidationError("Signataires : liste ordonnée parmi « usager », « elu », « agent ».")
        return valeur


class DepotVersionSerializer(serializers.Serializer):
    fichier = serializers.FileField()
    commentaire = serializers.CharField(max_length=250, required=False, allow_blank=True, default="")


class VueModelesDocuments(VuePerimetre):
    """DOC-01, ADM-04 : modèles livrés, versions déposées (.docx éditables dans Word)."""

    queryset = ModeleDocument.objects.select_related("version_active")
    serializer_class = ModeleDocumentSerializer
    actions_requises = {
        "lecture": "lire_document",
        "ecriture": "gerer_modele",
        "versions": "lire_document",
        "deposer_version": "gerer_modele",
        "activer_version": "gerer_modele",
        "telecharger_version": "lire_document",
    }
    http_method_names = ["get", "patch", "post", "head", "options"]
    pagination_class = None

    def create(self, request: Request, *args: Any, **kwargs: Any) -> Response:
        return Response(
            {"code": "non_autorise", "message": "Les modèles sont livrés ; déposez une nouvelle version."}, status=405
        )

    @extend_schema(responses=VersionSerializer(many=True))
    @action(detail=True, methods=["get"])
    def versions(self, request: Request, pk: str | None = None) -> Response:
        return Response(VersionSerializer(self.get_object().versions.select_related("fichier"), many=True).data)

    @extend_schema(request={"multipart/form-data": DepotVersionSerializer}, responses=VersionSerializer)
    @action(detail=True, methods=["post"], url_path="deposer-version", parser_classes=[MultiPartParser])
    def deposer_version(self, request: Request, pk: str | None = None) -> Response:
        entree = DepotVersionSerializer(data=request.data)
        entree.is_valid(raise_exception=True)
        televerse = entree.validated_data["fichier"]
        if televerse.size is None or televerse.size > fichiers.TAILLE_MAX:
            raise ErreurValidation("Le fichier est trop volumineux.", code="fichier_trop_gros")
        version = services.deposer_version(
            self.get_object(),
            televerse.name or "modele.docx",
            televerse.read(),
            acteur=agent_courant(request),
            commentaire=entree.validated_data["commentaire"],
        )
        return Response(VersionSerializer(version).data, status=status.HTTP_201_CREATED)

    @extend_schema(
        request={"application/json": {"type": "object", "properties": {"version": {"type": "integer"}}}},
        responses=ModeleDocumentSerializer,
    )
    @action(detail=True, methods=["post"], url_path="activer-version", parser_classes=[JSONParser])
    def activer_version(self, request: Request, pk: str | None = None) -> Response:
        modele = self.get_object()
        identifiant = str(request.data.get("version", "")) if isinstance(request.data, dict) else ""
        version = modele.versions.filter(pk=identifiant).first() if identifiant.isdigit() else None
        if version is None:
            raise ErreurValidation("Version inconnue pour ce modèle.", code="version_inconnue")
        return Response(ModeleDocumentSerializer(services.activer_version(version, acteur=agent_courant(request))).data)

    @extend_schema(responses={(200, "application/octet-stream"): bytes})
    @action(detail=True, methods=["get"], url_path=r"versions/(?P<version>\d+)/fichier")
    def telecharger_version(self, request: Request, pk: str | None = None, version: str | None = None) -> FileResponse:
        trouvee = self.get_object().versions.select_related("fichier").filter(pk=version).first()
        if trouvee is None:
            raise ErreurValidation("Version inconnue pour ce modèle.", code="version_inconnue")
        return fichiers.reponse_telechargement(trouvee.fichier)


class SignataireSerializer(serializers.Serializer):
    ordre = serializers.IntegerField()
    role = serializers.CharField()
    nom = serializers.CharField()
    courriel = serializers.EmailField()
    statut = serializers.CharField()
    signe_le = serializers.DateTimeField(allow_null=True)


class CircuitSerializer(serializers.ModelSerializer):
    signataires = SignataireSerializer(many=True, read_only=True)

    class Meta:
        model = CircuitSignature
        fields = [
            "id",
            "mode",
            "statut",
            "envoye_le",
            "expire_le",
            "relance_le",
            "termine_le",
            "purge_le",
            "erreur",
            "signataires",
        ]


class DocumentSerializer(serializers.ModelSerializer):
    modele_libelle = serializers.CharField(source="modele.libelle", read_only=True)
    version_numero = serializers.IntegerField(source="version.numero", read_only=True)
    dossier_numero = serializers.CharField(source="dossier.numero", read_only=True, default="")
    usager_nom = serializers.CharField(source="usager.nom", read_only=True, default="")
    signature_requise = serializers.BooleanField(source="modele.signature_requise", read_only=True)
    parent_numero = serializers.CharField(source="parent.numero", read_only=True, default="")
    circuits = CircuitSerializer(many=True, read_only=True)

    class Meta:
        model = Document
        fields = [
            "id",
            "numero",
            "modele",
            "modele_libelle",
            "version_numero",
            "nature",
            "titre",
            "dossier",
            "dossier_numero",
            "usager",
            "usager_nom",
            "parent",
            "parent_numero",
            "sha256",
            "statut",
            "signe_le",
            "signe_par",
            "signature_requise",
            "visible_portail",
            "motif_annulation",
            "cree_par",
            "cree_le",
            "circuits",
        ]
        read_only_fields = fields


class GenerationSerializer(serializers.Serializer):
    """L'objet dépend de la nature du modèle : un dossier, une séance (état des lieux) ou une fermeture et un usager
    (avis de fermeture)."""

    modele = serializers.SlugRelatedField(slug_field="code", queryset=ModeleDocument.objects.filter(actif=True))
    dossier = serializers.PrimaryKeyRelatedField(queryset=Dossier.objects.all(), required=False)
    seance = serializers.PrimaryKeyRelatedField(
        queryset=Occurrence.objects.select_related("reservation__dossier"), required=False
    )
    fermeture = serializers.PrimaryKeyRelatedField(queryset=Fermeture.objects.all(), required=False)
    usager = serializers.PrimaryKeyRelatedField(queryset=Usager.objects.all(), required=False)

    def validate(self, donnees: dict[str, Any]) -> dict[str, Any]:
        attendu = services.NATURES_PAR_OBJET.get(donnees["modele"].nature, "dossier")
        if attendu == "seance":
            if "seance" not in donnees:
                raise serializers.ValidationError({"seance": "Indiquez la séance de l'état des lieux."})
            donnees["objet"] = donnees["seance"]
        elif attendu == "fermeture":
            if "fermeture" not in donnees or "usager" not in donnees:
                raise serializers.ValidationError({"fermeture": "Indiquez la fermeture et l'usager prévenu."})
            donnees["objet"] = (donnees["fermeture"], donnees["usager"])
        else:
            if "dossier" not in donnees:
                raise serializers.ValidationError({"dossier": "Indiquez le dossier."})
            donnees["objet"] = donnees["dossier"]
        return donnees


class VisibiliteSerializer(serializers.Serializer):
    visible_portail = serializers.BooleanField()


class ControleScanSerializer(serializers.Serializer):
    accepter = serializers.BooleanField()
    motif = serializers.CharField(max_length=300, required=False, allow_blank=True, default="")


class MotifSerializer(serializers.Serializer):
    motif = serializers.CharField(max_length=300)


class EnvoiSignatureSerializer(serializers.Serializer):
    mode = serializers.ChoiceField(choices=["docuseal", "manuel"], required=False)


class ScanSerializer(serializers.Serializer):
    fichier = serializers.FileField()


def _documents_lisibles(request: Request, action_requise: str) -> QuerySet[Document]:
    agent = agent_courant(request)
    qs = Document.objects.select_related("modele", "version", "dossier", "usager", "parent").prefetch_related(
        "circuits__signataires"
    )
    if not peut(agent, action_requise):
        return qs.none()
    sites = sites_autorises(agent, action_requise)
    if sites is None:
        return qs
    # Un document sans dossier (avis de fermeture, attestation annuelle) concerne l'usager sur tous les sites :
    # il n'est lisible qu'avec un périmètre « tous sites » (RG-14).
    return qs.filter(dossier__reservations__espace__batiment__site__in=sites).distinct()


class VueDocuments(VuePerimetre):
    """DOC-02 à DOC-07, SIG-01 à SIG-05 : documents d'un dossier, génération, signature, avenants."""

    queryset = Document.objects.none()
    serializer_class = DocumentSerializer
    actions_requises = {
        "lecture": "lire_document",
        "list": "lire_document",
        "retrieve": "lire_document",
        "generer": "generer_document",
        "fichier": "lire_document",
        "original": "lire_document",
        "preuve": "lire_document",
        "avenant": "generer_document",
        "annuler": "generer_document",
        "envoyer_signature": "envoyer_signature",
        "annuler_signature": "envoyer_signature",
        "scan_signe": "envoyer_signature",
        "controler_scan": "envoyer_signature",
        "visibilite": "generer_document",
        "scan": "lire_document",
    }
    http_method_names = ["get", "post", "head", "options"]
    filterset_fields = ["dossier", "nature", "statut", "usager", "modele"]

    def get_queryset(self) -> QuerySet[Document]:
        if getattr(self, "swagger_fake_view", False):
            return Document.objects.none()
        lecture = self.request.method in ("GET", "HEAD", "OPTIONS")
        return _documents_lisibles(self.request, "lire_document" if lecture else "generer_document").order_by("-cree_le")

    def create(self, request: Request, *args: Any, **kwargs: Any) -> Response:
        return Response({"code": "non_autorise", "message": "Utilisez « générer »."}, status=405)

    def _document(self) -> Document:
        """Lecture dans le périmètre de l'agent, puis contrôle de l'action sur l'objet (service)."""
        identifiant = str(self.kwargs.get("pk", ""))
        document = (
            _documents_lisibles(self.request, "lire_document").filter(pk=identifiant).first() if identifiant.isdigit() else None
        )
        if document is None:
            raise NotFound()
        return document

    def _repondre(self, document: Document, statut: int = status.HTTP_200_OK) -> Response:
        return Response(DocumentSerializer(self.get_queryset().model.objects.get(pk=document.pk)).data, status=statut)

    @extend_schema(request=GenerationSerializer, responses=DocumentSerializer)
    @action(detail=False, methods=["post"])
    def generer(self, request: Request) -> Response:
        entree = GenerationSerializer(data=request.data)
        entree.is_valid(raise_exception=True)
        document = services.generer(
            entree.validated_data["modele"], entree.validated_data["objet"], acteur=agent_courant(request)
        )
        return self._repondre(document, status.HTTP_201_CREATED)

    def _telecharger(self, request: Request, attribut: str) -> FileResponse:
        document = self._document()
        fichier = getattr(document, attribut)
        if fichier is None:
            raise ErreurMetier("Ce fichier n'existe pas pour ce document.", code="fichier_absent")
        if attribut == "fichier" and fichier.sha256 != document.sha256:
            raise ErreurMetier(
                "Le fichier ne correspond plus à l'empreinte du document : téléchargement refusé.", code="fichier_altere"
            )
        journaliser("telecharger_document", document, apres={"fichier": attribut}, acteur=agent_courant(request))
        return fichiers.reponse_telechargement(fichier)

    @extend_schema(responses={(200, "application/pdf"): bytes})
    @action(detail=True, methods=["get"])
    def fichier(self, request: Request, pk: str | None = None) -> FileResponse:
        """Exemplaire de référence : le PDF signé s'il existe, sinon le PDF généré."""
        document = self._document()
        return self._telecharger(request, "fichier_signe" if document.fichier_signe_id else "fichier")

    @extend_schema(responses={(200, "application/pdf"): bytes})
    @action(detail=True, methods=["get"])
    def original(self, request: Request, pk: str | None = None) -> FileResponse:
        return self._telecharger(request, "fichier")

    @extend_schema(responses={(200, "application/pdf"): bytes})
    @action(detail=True, methods=["get"])
    def preuve(self, request: Request, pk: str | None = None) -> FileResponse:
        return self._telecharger(request, "preuve")

    @extend_schema(request=MotifSerializer, responses=DocumentSerializer)
    @action(detail=True, methods=["post"])
    def avenant(self, request: Request, pk: str | None = None) -> Response:
        entree = MotifSerializer(data=request.data)
        entree.is_valid(raise_exception=True)
        avenant = services.generer_avenant(self._document(), acteur=agent_courant(request), motif=entree.validated_data["motif"])
        return self._repondre(avenant, status.HTTP_201_CREATED)

    @extend_schema(request=MotifSerializer, responses=DocumentSerializer)
    @action(detail=True, methods=["post"])
    def annuler(self, request: Request, pk: str | None = None) -> Response:
        entree = MotifSerializer(data=request.data)
        entree.is_valid(raise_exception=True)
        return self._repondre(
            services.annuler(self._document(), acteur=agent_courant(request), motif=entree.validated_data["motif"])
        )

    @extend_schema(request=EnvoiSignatureSerializer, responses=DocumentSerializer)
    @action(detail=True, methods=["post"], url_path="envoyer-signature")
    def envoyer_signature(self, request: Request, pk: str | None = None) -> Response:
        entree = EnvoiSignatureSerializer(data=request.data)
        entree.is_valid(raise_exception=True)
        document = self._document()
        services.envoyer_en_signature(document, acteur=agent_courant(request), mode=entree.validated_data.get("mode"))
        return self._repondre(document)

    @extend_schema(request=MotifSerializer, responses=DocumentSerializer)
    @action(detail=True, methods=["post"], url_path="annuler-signature")
    def annuler_signature(self, request: Request, pk: str | None = None) -> Response:
        entree = MotifSerializer(data=request.data)
        entree.is_valid(raise_exception=True)
        document = self._document()
        circuit = document.circuits.filter(statut__in=["envoye", "preparation", "erreur"]).first()
        if circuit is None:
            raise ErreurMetier("Aucune signature en cours.", code="statut_signature")
        services.annuler_circuit(circuit, acteur=agent_courant(request), motif=entree.validated_data["motif"])
        return self._repondre(document)

    @extend_schema(request={"multipart/form-data": ScanSerializer}, responses=DocumentSerializer)
    @action(detail=True, methods=["post"], url_path="scan-signe", parser_classes=[MultiPartParser])
    def scan_signe(self, request: Request, pk: str | None = None) -> Response:
        entree = ScanSerializer(data=request.data)
        entree.is_valid(raise_exception=True)
        televerse = entree.validated_data["fichier"]
        if televerse.size is None or televerse.size > fichiers.TAILLE_MAX:
            raise ErreurValidation("Le fichier est trop volumineux.", code="fichier_trop_gros")
        document = services.deposer_scan_signe(
            self._document(), televerse.name or "scan.pdf", televerse.read(), acteur=agent_courant(request)
        )
        return self._repondre(document)

    @extend_schema(request=VisibiliteSerializer, responses=DocumentSerializer)
    @action(detail=True, methods=["post"])
    def visibilite(self, request: Request, pk: str | None = None) -> Response:
        """DOC-07 : un document peut être retiré du portail (ou y être remis) ; il reste dans le dossier."""
        entree = VisibiliteSerializer(data=request.data)
        entree.is_valid(raise_exception=True)
        document = self._document()
        services.controler(agent_courant(request), "generer_document", document)
        Document.objects.filter(pk=document.pk).update(visible_portail=entree.validated_data["visible_portail"])
        journaliser("visibilite_document", document, apres=entree.validated_data, acteur=agent_courant(request))
        return self._repondre(document)

    @extend_schema(responses={(200, "application/pdf"): bytes})
    @action(detail=True, methods=["get"])
    def scan(self, request: Request, pk: str | None = None) -> FileResponse:
        """SIG-05 : scan déposé par l'usager, à contrôler."""
        return self._telecharger(request, "scan_depose")

    @extend_schema(request=ControleScanSerializer, responses=DocumentSerializer)
    @action(detail=True, methods=["post"], url_path="controler-scan")
    def controler_scan(self, request: Request, pk: str | None = None) -> Response:
        entree = ControleScanSerializer(data=request.data)
        entree.is_valid(raise_exception=True)
        document = services.controler_scan(self._document(), acteur=agent_courant(request), **entree.validated_data)
        return self._repondre(document)


class LotSerializer(serializers.ModelSerializer):
    modele_code = serializers.SlugRelatedField(
        source="modele", slug_field="code", queryset=ModeleDocument.objects.filter(actif=True)
    )
    dossiers = serializers.PrimaryKeyRelatedField(queryset=Dossier.objects.all(), many=True, write_only=True)

    class Meta:
        model = LotGeneration
        fields = [
            "id",
            "modele_code",
            "libelle",
            "dossiers",
            "envoyer_signature",
            "statut",
            "total",
            "faits",
            "erreurs",
            "cree_le",
            "termine_le",
        ]
        read_only_fields = ["statut", "total", "faits", "erreurs", "cree_le", "termine_le"]


class VueLots(VuePerimetre):
    """DOC-06 : génération en lot en tâche de fond, avec progression et rapport d'erreurs."""

    queryset = LotGeneration.objects.select_related("modele")
    serializer_class = LotSerializer
    actions_requises = {"lecture": "lire_document", "ecriture": "generer_document"}
    http_method_names = ["get", "post", "head", "options"]

    def perform_create(self, serializer: Any) -> None:
        d = serializer.validated_data
        serializer.instance = services.creer_lot(
            d["modele"],
            d["dossiers"],
            acteur=agent_courant(self.request),
            libelle=d["libelle"],
            envoyer_signature=d.get("envoyer_signature", False),
        )

    @extend_schema(request=None, responses=LotSerializer)
    @action(detail=True, methods=["post"])
    def relancer(self, request: Request, pk: str | None = None) -> Response:
        """DOC-06 : relance d'un lot en échec ou interrompu (les dossiers déjà traités sont ignorés)."""
        lot = services.relancer_lot(self.get_object(), acteur=agent_courant(request))
        return Response(LotSerializer(lot).data)
