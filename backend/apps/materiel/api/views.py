"""API de gestion du matériel (lot 5) : catalogue, stocks et mouvements, prêts, contrôles et pannes. Droits rôle ×
périmètre sur chaque objet (RG-14) ; les règles sont dans `apps.materiel.services`."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from django.http import HttpResponse
from django.utils import timezone
from drf_spectacular.utils import OpenApiParameter, extend_schema
from rest_framework import serializers, status
from rest_framework.decorators import action
from rest_framework.request import Request
from rest_framework.response import Response

from apps.audit.services import journaliser
from apps.habilitations.authentification import agent_courant
from apps.noyau.api import VuePerimetre
from apps.noyau.exceptions import ErreurMetier, ErreurValidation
from apps.noyau.tableur import cellule_sure
from apps.referentiel.models import Espace, Site
from apps.reservations.models import Dossier, Reservation

from .. import services
from ..models import Controle, Materiel, Mouvement, Panne, ReservationMateriel, Stock


class MaterielSerializer(serializers.ModelSerializer):
    class Meta:
        model = Materiel
        fields = [
            "id",
            "code",
            "libelle",
            "nature",
            "description",
            "unite",
            "valeur_journaliere_centimes",
            "prestation_code",
            "reservable",
            "propose_portail",
            "periodicite_controle_jours",
            "seuil_alerte",
            "actif",
        ]

        # Prix et valeur de référence relèvent de l'ordonnateur : ils se fixent par l'action « tarif » (gerer_tarifs).
        read_only_fields = ["valeur_journaliere_centimes", "prestation_code"]

    def validate(self, donnees: dict[str, Any]) -> dict[str, Any]:
        instance = self.instance
        if instance is not None and "nature" in donnees and donnees["nature"] != instance.nature and instance.stocks.exists():
            raise serializers.ValidationError({"nature": "Un article déjà en stock ne change pas de nature."})
        return donnees


class TarifMaterielSerializer(serializers.ModelSerializer):
    class Meta:
        model = Materiel
        fields = ["valeur_journaliere_centimes", "prestation_code"]

    def validate_valeur_journaliere_centimes(self, valeur: int) -> int:
        if valeur < 1:
            raise serializers.ValidationError("La valeur de référence d'une journée est d'au moins 1 centime (RG-05).")
        return valeur

    def validate_prestation_code(self, code: str) -> str:
        from apps.finances.models import Prestation
        from apps.finances.tarification import grille_en_vigueur

        if not code:
            return code
        try:
            grille = grille_en_vigueur(timezone.localdate())
        except ErreurMetier as erreur:
            raise serializers.ValidationError(erreur.message) from erreur
        if not Prestation.objects.filter(grille=grille, code=code).exists():
            raise serializers.ValidationError("Prestation absente de la grille tarifaire en vigueur.")
        return code


class VueMateriels(VuePerimetre):
    """MAT-01 : catalogue (transversal) ; un article ne se supprime pas, il se désactive."""

    queryset = Materiel.objects.all()
    serializer_class = MaterielSerializer
    actions_requises = {"lecture": "lire_materiel", "ecriture": "gerer_materiel", "tarif": "gerer_tarifs"}
    filterset_fields = ["nature", "actif", "reservable", "propose_portail"]
    search_fields = ["libelle", "code"]
    http_method_names = ["get", "post", "patch", "head", "options"]

    @extend_schema(request=TarifMaterielSerializer, responses=MaterielSerializer)
    @action(detail=True, methods=["post"])
    def tarif(self, request: Request, pk: str | None = None) -> Response:
        """Valeur de référence et prestation facturée, fixées par l'ordonnateur (séparation des tâches, ADR 0005)."""
        materiel = self.get_object()
        entree = TarifMaterielSerializer(materiel, data=request.data, partial=True)
        entree.is_valid(raise_exception=True)
        avant = {"valeur": materiel.valeur_journaliere_centimes, "prestation": materiel.prestation_code}
        entree.save()
        journaliser("tarifer_materiel", materiel, avant=avant, apres=dict(entree.validated_data), acteur=agent_courant(request))
        return Response(MaterielSerializer(materiel).data)


class StockMaterielSerializer(serializers.ModelSerializer):
    materiel_libelle = serializers.CharField(source="materiel.libelle", read_only=True)
    nature = serializers.CharField(source="materiel.nature", read_only=True)
    unite = serializers.CharField(source="materiel.unite", read_only=True)
    site_nom = serializers.CharField(source="site.nom", read_only=True)
    espace_nom = serializers.CharField(source="espace.nom", read_only=True, default="")
    en_etat = serializers.IntegerField(read_only=True)
    echeance_controle = serializers.SerializerMethodField()

    class Meta:
        model = Stock
        fields = [
            "id",
            "materiel",
            "materiel_libelle",
            "nature",
            "unite",
            "site",
            "site_nom",
            "espace",
            "espace_nom",
            "quantite",
            "hors_service",
            "en_etat",
            "dernier_controle",
            "echeance_controle",
        ]
        read_only_fields = fields

    def get_echeance_controle(self, stock: Stock) -> str | None:
        echeance = services.echeance_controle(stock)
        return echeance.isoformat() if echeance else None


class EntreeSerializer(serializers.Serializer):
    materiel = serializers.PrimaryKeyRelatedField(queryset=Materiel.objects.filter(actif=True))
    site = serializers.PrimaryKeyRelatedField(queryset=Site.objects.all())
    espace = serializers.PrimaryKeyRelatedField(
        queryset=Espace.objects.select_related("batiment"), allow_null=True, required=False
    )
    quantite = serializers.IntegerField(min_value=1, max_value=100_000)
    motif = serializers.CharField(max_length=300, required=False, allow_blank=True, default="")


class QuantiteStockSerializer(serializers.Serializer):
    quantite = serializers.IntegerField(min_value=0, max_value=100_000)
    motif = serializers.CharField(max_length=300, required=False, allow_blank=True, default="")


class TransfertSerializer(QuantiteStockSerializer):
    site = serializers.PrimaryKeyRelatedField(queryset=Site.objects.all())
    espace = serializers.PrimaryKeyRelatedField(
        queryset=Espace.objects.select_related("batiment"), allow_null=True, required=False
    )


class PanneSaisieSerializer(serializers.Serializer):
    quantite = serializers.IntegerField(min_value=1, max_value=100_000, default=1)
    description = serializers.CharField(max_length=2000)


class ControleSaisieSerializer(serializers.Serializer):
    nature = serializers.ChoiceField(choices=Controle.NATURES, default="controle")
    realise_le = serializers.DateField()
    conforme = serializers.BooleanField(default=True)
    observations = serializers.CharField(max_length=4000, required=False, allow_blank=True, default="")
    prestataire = serializers.CharField(max_length=150, required=False, allow_blank=True, default="")


def _periode(request: Request) -> tuple[datetime, datetime]:
    try:
        debut = datetime.fromisoformat(request.query_params["debut"])
        fin = datetime.fromisoformat(request.query_params["fin"])
    except (KeyError, ValueError) as erreur:
        raise ErreurValidation("Indiquez debut et fin au format ISO 8601.", code="periode_invalide") from erreur
    debut = timezone.make_aware(debut) if timezone.is_naive(debut) else debut
    fin = timezone.make_aware(fin) if timezone.is_naive(fin) else fin
    if fin <= debut:
        raise ErreurValidation("La fin doit suivre le début.", code="periode_invalide")
    return debut, fin


class VueStocks(VuePerimetre):
    """MAT-01, MAT-03 : stocks par site et espace ; les quantités ne changent que par les mouvements."""

    queryset = Stock.objects.select_related("materiel", "site", "espace")
    serializer_class = StockMaterielSerializer
    chemin_site = "site"
    actions_requises = {
        "lecture": "lire_materiel",
        "ecriture": "gerer_materiel",
        "entrer": "gerer_materiel",
        "transferer": "gerer_materiel",
        "perte": "gerer_materiel",
        "inventaire": "gerer_materiel",
        "panne": "signaler_panne_materiel",
        "controle": "gerer_materiel",
        "disponibilite": "lire_materiel",
        "etat": "lire_materiel",
        "alertes": "lire_materiel",
    }
    filterset_fields = ["materiel", "site", "espace", "materiel__nature"]
    http_method_names = ["get", "post", "head", "options"]

    def create(self, request: Request, *args: Any, **kwargs: Any) -> Response:
        return Response({"code": "non_autorise", "message": "Un stock naît d'une entrée de matériel."}, status=405)

    @extend_schema(request=EntreeSerializer, responses=StockMaterielSerializer)
    @action(detail=False, methods=["post"])
    def entrer(self, request: Request) -> Response:
        entree = EntreeSerializer(data=request.data)
        entree.is_valid(raise_exception=True)
        d = entree.validated_data
        self._verifier_objet(d["site"])
        stock = services.entrer(
            d["materiel"], d["site"], d["quantite"], acteur=agent_courant(request), espace=d.get("espace"), motif=d["motif"]
        )
        return Response(StockMaterielSerializer(stock).data, status=status.HTTP_201_CREATED)

    @extend_schema(request=TransfertSerializer, responses=StockMaterielSerializer)
    @action(detail=True, methods=["post"])
    def transferer(self, request: Request, pk: str | None = None) -> Response:
        entree = TransfertSerializer(data=request.data)
        entree.is_valid(raise_exception=True)
        d = entree.validated_data
        destination = services.transferer(
            self.get_object(), d["site"], d["quantite"], acteur=agent_courant(request), espace=d.get("espace"), motif=d["motif"]
        )
        return Response(StockMaterielSerializer(destination).data)

    @extend_schema(request=QuantiteStockSerializer, responses=StockMaterielSerializer)
    @action(detail=True, methods=["post"])
    def perte(self, request: Request, pk: str | None = None) -> Response:
        entree = QuantiteStockSerializer(data=request.data)
        entree.is_valid(raise_exception=True)
        d = entree.validated_data
        return Response(
            StockMaterielSerializer(
                services.declarer_perte(self.get_object(), d["quantite"], acteur=agent_courant(request), motif=d["motif"])
            ).data
        )

    @extend_schema(request=QuantiteStockSerializer, responses=StockMaterielSerializer)
    @action(detail=True, methods=["post"])
    def inventaire(self, request: Request, pk: str | None = None) -> Response:
        entree = QuantiteStockSerializer(data=request.data)
        entree.is_valid(raise_exception=True)
        d = entree.validated_data
        return Response(
            StockMaterielSerializer(
                services.inventorier(self.get_object(), d["quantite"], acteur=agent_courant(request), motif=d["motif"])
            ).data
        )

    @extend_schema(request=PanneSaisieSerializer, responses={201: dict})
    @action(detail=True, methods=["post"])
    def panne(self, request: Request, pk: str | None = None) -> Response:
        """MAT-05 : tout agent qui voit le matériel peut signaler une panne (gardien, planificateur, technicien)."""
        entree = PanneSaisieSerializer(data=request.data)
        entree.is_valid(raise_exception=True)
        d = entree.validated_data
        panne = services.signaler_panne(
            self.get_object(), acteur=agent_courant(request), quantite=d["quantite"], description=d["description"]
        )
        return Response(PanneMaterielSerializer(panne).data, status=status.HTTP_201_CREATED)

    @extend_schema(request=ControleSaisieSerializer, responses={201: dict})
    @action(detail=True, methods=["post"])
    def controle(self, request: Request, pk: str | None = None) -> Response:
        entree = ControleSaisieSerializer(data=request.data)
        entree.is_valid(raise_exception=True)
        controle = services.enregistrer_controle(self.get_object(), acteur=agent_courant(request), **entree.validated_data)
        return Response(ControleMaterielSerializer(controle).data, status=status.HTTP_201_CREATED)

    @extend_schema(parameters=[OpenApiParameter("debut", str), OpenApiParameter("fin", str)], responses={200: dict})
    @action(detail=True, methods=["get"])
    def disponibilite(self, request: Request, pk: str | None = None) -> Response:
        """MAT-02 : quantité disponible sur une période (unités en état moins le plus fort engagement)."""
        stock = self.get_object()
        debut, fin = _periode(request)
        return Response({"stock": stock.pk, "disponible": services.disponible(stock, debut, fin), "en_etat": stock.en_etat})

    @extend_schema(parameters=[OpenApiParameter("format", str)], responses={200: dict})
    @action(detail=False, methods=["get"])
    def etat(self, request: Request) -> Response | HttpResponse:
        """MAT-03 : état du stock (sur place, sortis, hors service, prêts à venir, contrôle), exportable."""
        lignes = services.etat_du_stock(self.filter_queryset(self.get_queryset()))
        if request.query_params.get("export") == "csv":
            import csv
            import io

            sortie = io.StringIO()
            ecrivain = csv.writer(sortie, delimiter=";")
            ecrivain.writerow(
                [
                    "Matériel",
                    "Site",
                    "Espace",
                    "Quantité",
                    "Hors service",
                    "Sortis",
                    "Sur place",
                    "Prêts à venir",
                    "Contrôle attendu",
                ]
            )
            for ligne in lignes:
                stock = ligne["stock"]
                ecrivain.writerow(
                    [
                        cellule_sure(stock.materiel.libelle),
                        cellule_sure(stock.site.nom),
                        cellule_sure(stock.espace.nom if stock.espace else ""),
                        ligne["quantite"],
                        ligne["hors_service"],
                        ligne["sortis"],
                        ligne["sur_place"],
                        ligne["prets_a_venir"],
                        f"{ligne['echeance_controle']:%d/%m/%Y}" if ligne["echeance_controle"] else "",
                    ]
                )
            reponse = HttpResponse(("﻿" + sortie.getvalue()).encode("utf-8"), content_type="text/csv; charset=utf-8")
            reponse["Content-Disposition"] = 'attachment; filename="etat-du-stock.csv"'
            return reponse
        return Response(
            [
                {
                    **StockMaterielSerializer(ligne["stock"]).data,
                    **{k: v for k, v in ligne.items() if k not in ("stock", "echeance_controle")},
                    "echeance_controle": ligne["echeance_controle"].isoformat() if ligne["echeance_controle"] else None,
                }
                for ligne in lignes
            ]
        )

    @extend_schema(responses={200: dict})
    @action(detail=False, methods=["get"])
    def alertes(self, request: Request) -> Response:
        """MAT-04, DSH-03 : contrôles dépassés et consommables sous le seuil, dans le périmètre."""
        stocks = list(self.get_queryset().filter(materiel__actif=True))
        return Response(
            {
                "controles": [
                    {**StockMaterielSerializer(s).data, "echeance": e.isoformat()}
                    for s, e in services.controles_en_retard(stocks)
                ],
                "seuils": [StockMaterielSerializer(s).data for s in services.stocks_sous_seuil(stocks)],
            }
        )


class PretSerializer(serializers.ModelSerializer):
    materiel_libelle = serializers.CharField(source="stock.materiel.libelle", read_only=True)
    unite = serializers.CharField(source="stock.materiel.unite", read_only=True)
    site_nom = serializers.CharField(source="stock.site.nom", read_only=True)
    dossier_numero = serializers.CharField(source="dossier.numero", read_only=True)
    usager_nom = serializers.CharField(source="dossier.usager.nom", read_only=True)

    class Meta:
        model = ReservationMateriel
        fields = [
            "id",
            "dossier",
            "dossier_numero",
            "usager_nom",
            "reservation",
            "occurrence",
            "stock",
            "materiel_libelle",
            "unite",
            "site_nom",
            "quantite",
            "debut",
            "fin",
            "statut",
            "quantite_sortie",
            "quantite_rendue",
            "manquants",
            "manquants_regles",
            "origine",
            "commentaire",
            "motif",
            "signalement",
            "cree_le",
        ]
        read_only_fields = [
            "manquants_regles",
            "statut",
            "quantite_sortie",
            "quantite_rendue",
            "manquants",
            "origine",
            "motif",
            "signalement",
            "cree_le",
        ]
        extra_kwargs = {"debut": {"required": False}, "fin": {"required": False}}


class MotifPretSerializer(serializers.Serializer):
    motif = serializers.CharField(max_length=300)


class DecisionSerializer(serializers.Serializer):
    decision = serializers.CharField(max_length=250)


class RetourPretSerializer(serializers.Serializer):
    quantite = serializers.IntegerField(min_value=0, max_value=100_000)
    observations = serializers.CharField(max_length=300, required=False, allow_blank=True, default="")
    solde = serializers.BooleanField(default=True, help_text="Faux : retour partiel, le prêt reste sorti.")


class SortiePretSerializer(serializers.Serializer):
    quantite = serializers.IntegerField(min_value=1, max_value=100_000, required=False)


class VuePrets(VuePerimetre):
    """MAT-02, MAT-03 : prêts rattachés aux dossiers (site du matériel dans le périmètre)."""

    queryset = ReservationMateriel.objects.select_related("stock__materiel", "stock__site", "dossier__usager")
    serializer_class = PretSerializer
    chemin_site = "stock__site"
    actions_requises = {
        "lecture": "lire_materiel",
        "ecriture": "creer_reservation",
        "valider": "creer_reservation",
        "refuser": "creer_reservation",
        "sortir": "gerer_materiel",
        "rendre": "gerer_materiel",
        "retrouver": "gerer_materiel",
        "regler_manquants": "gerer_materiel",
    }
    filterset_fields = {
        "dossier": ["exact"],
        "statut": ["exact", "in"],
        "stock__site": ["exact"],
        "stock__materiel": ["exact"],
        "debut": ["gte", "lt"],
    }
    http_method_names = ["get", "post", "head", "options"]

    @extend_schema(request=PretSerializer, responses={201: PretSerializer(many=True)})
    def create(self, request: Request, *args: Any, **kwargs: Any) -> Response:
        """Un prêt par séance à venir de la réservation choisie, ou pour une séance, ou sur une période du dossier."""
        entree = PretSerializer(data=request.data)
        entree.is_valid(raise_exception=True)
        d = entree.validated_data
        dossier: Dossier = d["dossier"]
        reservation: Reservation | None = d.get("reservation")
        occurrence = d.get("occurrence")
        self._verifier_objet(d["stock"])
        acteur = agent_courant(request)
        if reservation is not None and reservation.dossier_id != dossier.pk:
            raise ErreurValidation("Cette réservation n'appartient pas au dossier.", code="reservation_autre_dossier")
        if occurrence is not None:
            prets = [
                services.reserver(
                    dossier, d["stock"], d["quantite"], acteur=acteur, occurrence=occurrence, commentaire=d.get("commentaire", "")
                )
            ]
        elif reservation is not None:
            prets = services.reserver_pour_reservation(
                reservation, d["stock"], d["quantite"], acteur=acteur, commentaire=d.get("commentaire", "")
            )
        else:
            prets = [
                services.reserver(
                    dossier,
                    d["stock"],
                    d["quantite"],
                    acteur=acteur,
                    debut=d.get("debut"),
                    fin=d.get("fin"),
                    commentaire=d.get("commentaire", ""),
                )
            ]
        return Response(PretSerializer(prets, many=True).data, status=status.HTTP_201_CREATED)

    @extend_schema(request=None, responses=PretSerializer)
    @action(detail=True, methods=["post"])
    def valider(self, request: Request, pk: str | None = None) -> Response:
        return Response(PretSerializer(services.valider(self.get_object(), acteur=agent_courant(request))).data)

    @extend_schema(request=MotifPretSerializer, responses=PretSerializer)
    @action(detail=True, methods=["post"])
    def refuser(self, request: Request, pk: str | None = None) -> Response:
        entree = MotifPretSerializer(data=request.data)
        entree.is_valid(raise_exception=True)
        pret = services.refuser(self.get_object(), acteur=agent_courant(request), motif=entree.validated_data["motif"])
        return Response(PretSerializer(pret).data)

    @extend_schema(request=SortiePretSerializer, responses=PretSerializer)
    @action(detail=True, methods=["post"])
    def sortir(self, request: Request, pk: str | None = None) -> Response:
        entree = SortiePretSerializer(data=request.data)
        entree.is_valid(raise_exception=True)
        pret = services.sortir(self.get_object(), acteur=agent_courant(request), quantite=entree.validated_data.get("quantite"))
        return Response(PretSerializer(pret).data)

    @extend_schema(request=RetourPretSerializer, responses=PretSerializer)
    @action(detail=True, methods=["post"])
    def rendre(self, request: Request, pk: str | None = None) -> Response:
        entree = RetourPretSerializer(data=request.data)
        entree.is_valid(raise_exception=True)
        d = entree.validated_data
        pret = services.rendre(
            self.get_object(),
            acteur=agent_courant(request),
            quantite=d["quantite"],
            observations=d["observations"],
            solde=d["solde"],
        )
        return Response(PretSerializer(pret).data)

    @extend_schema(request=DecisionSerializer, responses=PretSerializer)
    @action(detail=True, methods=["post"], url_path="regler-manquants")
    def regler_manquants(self, request: Request, pk: str | None = None) -> Response:
        """Décision du service sur les manquants (retenue proposée, prise en charge) : débloque la caution."""
        entree = DecisionSerializer(data=request.data)
        entree.is_valid(raise_exception=True)
        pret = services.regler_manquants(
            self.get_object(), acteur=agent_courant(request), decision=entree.validated_data["decision"]
        )
        return Response(PretSerializer(pret).data)

    @extend_schema(request=SortiePretSerializer, responses=PretSerializer)
    @action(detail=True, methods=["post"])
    def retrouver(self, request: Request, pk: str | None = None) -> Response:
        entree = SortiePretSerializer(data=request.data)
        entree.is_valid(raise_exception=True)
        pret = services.retrouver(
            self.get_object(), acteur=agent_courant(request), quantite=entree.validated_data.get("quantite") or 1
        )
        return Response(PretSerializer(pret).data)


class MouvementStockSerializer(serializers.ModelSerializer):
    type_libelle = serializers.CharField(source="get_type_display", read_only=True)
    stock_libelle = serializers.CharField(source="stock.__str__", read_only=True)
    destination_libelle = serializers.CharField(source="stock_destination.__str__", read_only=True, default="")

    class Meta:
        model = Mouvement
        fields = [
            "id",
            "type",
            "type_libelle",
            "stock",
            "stock_libelle",
            "stock_destination",
            "destination_libelle",
            "quantite",
            "reservation",
            "motif",
            "acteur_libelle",
            "horodatage",
        ]
        read_only_fields = fields


class VueMouvements(VuePerimetre):
    """MAT-03 : journal des mouvements, en lecture seule (immuable en base)."""

    queryset = Mouvement.objects.select_related("stock__materiel", "stock__site", "stock_destination__site")
    serializer_class = MouvementStockSerializer
    chemin_site = "stock__site"
    actions_requises = {"lecture": "lire_materiel"}
    filterset_fields = {
        "stock": ["exact"],
        "type": ["exact"],
        "reservation": ["exact"],
        "stock__materiel": ["exact"],
        "horodatage": ["gte", "lt"],
    }
    http_method_names = ["get", "head", "options"]


class ControleMaterielSerializer(serializers.ModelSerializer):
    stock_libelle = serializers.CharField(source="stock.__str__", read_only=True)

    class Meta:
        model = Controle
        fields = [
            "id",
            "stock",
            "stock_libelle",
            "nature",
            "realise_le",
            "conforme",
            "observations",
            "prestataire",
            "prochain_le",
            "cree_le",
        ]
        read_only_fields = fields


class VueControles(VuePerimetre):
    """MAT-04 : historique des contrôles, maintenances et réparations (saisie par l'action « controle » du stock)."""

    queryset = Controle.objects.select_related("stock__materiel", "stock__site", "stock__espace")
    serializer_class = ControleMaterielSerializer
    chemin_site = "stock__site"
    actions_requises = {"lecture": "lire_materiel"}
    filterset_fields = ["stock", "nature", "conforme"]
    http_method_names = ["get", "head", "options"]


class PanneMaterielSerializer(serializers.ModelSerializer):
    stock_libelle = serializers.CharField(source="stock.__str__", read_only=True)

    class Meta:
        model = Panne
        fields = [
            "id",
            "stock",
            "stock_libelle",
            "quantite",
            "description",
            "source",
            "statut",
            "signalee_le",
            "resolue_le",
            "resolution",
        ]
        read_only_fields = fields


class ResolutionPanneSerializer(serializers.Serializer):
    issue = serializers.ChoiceField(choices=[("reparee", "Réparée"), ("rebut", "Mise au rebut")])
    resolution = serializers.CharField(max_length=2000, required=False, allow_blank=True, default="")


class VuePannes(VuePerimetre):
    """MAT-05 : pannes ouvertes et résolues (signalement par l'action « panne » du stock)."""

    queryset = Panne.objects.select_related("stock__materiel", "stock__site", "stock__espace")
    serializer_class = PanneMaterielSerializer
    chemin_site = "stock__site"
    actions_requises = {"lecture": "lire_materiel", "resoudre": "gerer_materiel"}
    filterset_fields = ["stock", "statut", "source"]
    http_method_names = ["get", "post", "head", "options"]

    def create(self, request: Request, *args: Any, **kwargs: Any) -> Response:
        return Response({"code": "non_autorise", "message": "Une panne se signale sur un stock."}, status=405)

    @extend_schema(request=ResolutionPanneSerializer, responses=PanneMaterielSerializer)
    @action(detail=True, methods=["post"])
    def resoudre(self, request: Request, pk: str | None = None) -> Response:
        entree = ResolutionPanneSerializer(data=request.data)
        entree.is_valid(raise_exception=True)
        d = entree.validated_data
        panne = services.resoudre_panne(
            self.get_object(), acteur=agent_courant(request), issue=d["issue"], resolution=d["resolution"]
        )
        return Response(PanneMaterielSerializer(panne).data)
