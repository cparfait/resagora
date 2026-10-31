"""API de gestion du personnel (PER-01 à PER-09) : fiches et habilitations, besoins, vacations et affectation,
trames, absences, compteurs et export paie, abonnement iCal, incidents, appareils mobiles, saisies reçues."""

from __future__ import annotations

from datetime import date, datetime, time, timedelta
from typing import Any

from django.db.models import Q, QuerySet
from django.http import HttpResponse
from django.utils import timezone
from drf_spectacular.utils import OpenApiParameter, extend_schema
from rest_framework import serializers, status
from rest_framework.decorators import action
from rest_framework.exceptions import NotFound
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.audit.services import journaliser
from apps.habilitations.authentification import agent_courant
from apps.habilitations.services import sites_autorises
from apps.noyau.api import VuePerimetre
from apps.noyau.exceptions import ErreurMetier, ErreurValidation
from apps.reservations.recurrence import PARIS

from .. import services
from ..mobile import empreinte_certificat
from ..models import (
    Absence,
    Agent,
    Appareil,
    Besoin,
    HabilitationAgent,
    Incident,
    LigneTrame,
    SaisieMobile,
    Trame,
    TypeHabilitation,
    Vacation,
)

LECTURE_ECRITURE = {"lecture": "lire_personnel", "ecriture": "planifier_personnel"}


class HabilitationSerializer(serializers.ModelSerializer):
    type_libelle = serializers.CharField(source="type.libelle", read_only=True)
    valide = serializers.SerializerMethodField()

    class Meta:
        model = HabilitationAgent
        fields = ["id", "agent", "type", "type_libelle", "obtenue_le", "valide_jusqu_au", "valide"]

    def get_valide(self, h: HabilitationAgent) -> bool:
        return h.valide_jusqu_au is None or h.valide_jusqu_au >= timezone.localdate()


class AgentSerializer(serializers.ModelSerializer):
    habilitations = HabilitationSerializer(many=True, read_only=True)
    sites_noms = serializers.SerializerMethodField()

    class Meta:
        model = Agent
        fields = [
            "id",
            "utilisateur",
            "matricule",
            "identifiant_ad",
            "prenom",
            "nom",
            "courriel",
            "telephone",
            "sites",
            "sites_noms",
            "site_prefere",
            "duree_hebdo_minutes",
            "actif",
            "habilitations",
        ]
        read_only_fields = ["utilisateur"]  # rattachement par l'identifiant de l'annuaire à la connexion

    def get_sites_noms(self, agent: Agent) -> list[str]:
        return [s.nom for s in agent.sites.all()]


class VueAgents(VuePerimetre):
    """PER-01 : un agent est lisible si l'un de ses sites est dans le périmètre."""

    queryset = Agent.objects.prefetch_related("sites", "habilitations__type").distinct()
    serializer_class = AgentSerializer
    chemin_site = "sites"
    actions_requises = {
        "lecture": "lire_personnel",
        "ecriture": "gerer_agents",
        "ical": "planifier_personnel",
        "revoquer_ical": "planifier_personnel",
    }
    filterset_fields = ["actif", "sites"]
    http_method_names = ["get", "post", "patch", "head", "options"]

    @extend_schema(request=None, responses={201: dict})
    @action(detail=True, methods=["post"])
    def ical(self, request: Request, pk: str | None = None) -> Response:
        """PER-08 : nouveau lien d'abonnement (le précédent est révoqué) ; affiché une seule fois."""
        jeton = services.emettre_jeton_ical(self.get_object(), acteur=agent_courant(request))
        return Response(
            {"url": request.build_absolute_uri(f"/api/gestion/personnel/ical/{jeton}.ics")}, status=status.HTTP_201_CREATED
        )

    @extend_schema(request=None, responses={200: dict})
    @action(detail=True, methods=["post"], url_path="revoquer-ical")
    def revoquer_ical(self, request: Request, pk: str | None = None) -> Response:
        return Response({"revoques": services.revoquer_jetons_ical(self.get_object(), acteur=agent_courant(request))})


class VueHabilitations(VuePerimetre):
    queryset = HabilitationAgent.objects.select_related("type", "agent")
    serializer_class = HabilitationSerializer
    chemin_site = "agent__sites"
    actions_requises = {"lecture": "lire_personnel", "ecriture": "gerer_agents"}
    filterset_fields = ["agent", "type"]


class TypeHabilitationSerializer(serializers.ModelSerializer):
    class Meta:
        model = TypeHabilitation
        fields = ["id", "code", "libelle", "exigee_pour_gardiennage"]


class VueTypesHabilitation(VuePerimetre):
    queryset = TypeHabilitation.objects.all()
    serializer_class = TypeHabilitationSerializer
    actions_requises = {"lecture": "lire_personnel", "ecriture": "gerer_agents"}
    pagination_class = None


class BesoinSerializer(serializers.ModelSerializer):
    site_nom = serializers.CharField(source="site.nom", read_only=True)
    seances = serializers.SerializerMethodField()

    class Meta:
        model = Besoin
        fields = ["id", "site", "site_nom", "debut", "fin", "statut", "seances"]
        read_only_fields = fields

    def get_seances(self, besoin: Besoin) -> list[str]:
        return [
            f"{o.espace.nom} {timezone.localtime(o.debut, PARIS):%H:%M}–{timezone.localtime(o.fin, PARIS):%H:%M}"
            for o in besoin.occurrences.all()
        ]


class VueBesoins(VuePerimetre):
    """PER-02, DSH-02 : besoins de gardiennage, couverts ou non."""

    queryset = Besoin.objects.select_related("site").prefetch_related("occurrences__espace").exclude(statut="supprime")
    serializer_class = BesoinSerializer
    chemin_site = "site"
    actions_requises = {
        "lecture": "lire_personnel",
        "ecriture": "planifier_personnel",
        "vacation": "planifier_personnel",
        "recalculer": "planifier_personnel",
    }
    filterset_fields = {"site": ["exact"], "statut": ["exact"], "debut": ["gte", "lt"]}
    http_method_names = ["get", "post", "head", "options"]

    def create(self, request: Request, *args: Any, **kwargs: Any) -> Response:
        return Response({"code": "non_autorise", "message": "Les besoins naissent des réservations."}, status=405)

    @extend_schema(request=None, responses={201: dict})
    @action(detail=True, methods=["post"])
    def vacation(self, request: Request, pk: str | None = None) -> Response:
        vacation = services.creer_vacation_pour_besoin(self.get_object(), acteur=agent_courant(request))
        return Response(VacationSerializer(vacation).data, status=status.HTTP_201_CREATED)

    @extend_schema(
        request={
            "application/json": {
                "type": "object",
                "properties": {"site": {"type": "integer"}, "du": {"type": "string"}, "au": {"type": "string"}},
            }
        },
        responses={200: dict},
    )
    @action(detail=False, methods=["post"])
    def recalculer(self, request: Request) -> Response:
        """Recalcul explicite (après une reprise de données) des besoins d'un site sur une période (31 jours au plus)."""
        from apps.referentiel.models import Site

        donnees = request.data if isinstance(request.data, dict) else {}
        site = Site.objects.filter(pk=int(donnees.get("site") or 0)).first() if str(donnees.get("site", "")).isdigit() else None
        try:
            du, au = date.fromisoformat(str(donnees.get("du"))), date.fromisoformat(str(donnees.get("au")))
        except ValueError as erreur:
            raise ErreurValidation("Dates au format AAAA-MM-JJ attendues.", code="dates_invalides") from erreur
        if site is None or au < du or (au - du).days > 31:
            raise ErreurValidation("Indiquez un site et une période de 31 jours au plus.", code="periode_invalide")
        self._verifier_objet(site)
        bilan: dict[str, int] = {}
        jour = du
        while jour <= au:
            for cle, valeur in services.recalculer_besoins(site.pk, jour).items():
                bilan[cle] = bilan.get(cle, 0) + valeur
            jour += timedelta(days=1)
        return Response(bilan)


class VacationSerializer(serializers.ModelSerializer):
    site_nom = serializers.CharField(source="site.nom", read_only=True)
    agent_nom = serializers.CharField(source="agent.__str__", read_only=True, default="")
    duree_minutes = serializers.IntegerField(read_only=True)

    class Meta:
        model = Vacation
        fields = [
            "id",
            "site",
            "site_nom",
            "agent",
            "agent_nom",
            "debut",
            "fin",
            "duree_minutes",
            "type",
            "statut",
            "violations",
            "forcee",
            "motif_forcage",
            "arrivee_reelle",
            "depart_reel",
            "signalement",
            "trame",
        ]
        read_only_fields = [
            "agent",
            "statut",
            "violations",
            "forcee",
            "motif_forcage",
            "arrivee_reelle",
            "depart_reel",
            "signalement",
            "trame",
        ]

    def validate(self, donnees: dict[str, Any]) -> dict[str, Any]:
        debut = donnees.get("debut", getattr(self.instance, "debut", None))
        fin = donnees.get("fin", getattr(self.instance, "fin", None))
        if debut and fin and fin <= debut:
            raise serializers.ValidationError("La fin doit suivre le début.")
        return donnees


class AffectationSerializer(serializers.Serializer):
    agent = serializers.PrimaryKeyRelatedField(queryset=Agent.objects.all(), allow_null=True)
    forcer = serializers.BooleanField(default=False)
    motif = serializers.CharField(max_length=300, required=False, allow_blank=True, default="")


class VueVacations(VuePerimetre):
    queryset = Vacation.objects.select_related("site", "agent")
    serializer_class = VacationSerializer
    chemin_site = "site"
    actions_requises = {
        "lecture": "lire_personnel",
        "ecriture": "planifier_personnel",
        "candidats": "planifier_personnel",
        "affecter": "planifier_personnel",
        "annuler": "planifier_personnel",
        "planning_pdf": "lire_personnel",
    }
    filterset_fields = {"site": ["exact"], "agent": ["exact", "isnull"], "statut": ["exact"], "debut": ["gte", "lt"]}
    http_method_names = ["get", "post", "patch", "head", "options"]

    def perform_create(self, serializer: Any) -> None:
        super().perform_create(serializer)
        services._recouvrir(serializer.instance)

    def update(self, request: Request, *args: Any, **kwargs: Any) -> Response:
        vacation = self.get_object()
        entree = VacationSerializer(vacation, data=request.data, partial=True)
        entree.is_valid(raise_exception=True)
        d = entree.validated_data
        vacation = services.modifier_vacation(
            vacation,
            acteur=agent_courant(request),
            debut=d.get("debut", vacation.debut),
            fin=d.get("fin", vacation.fin),
            type_vacation=d.get("type"),
            forcer=bool(request.data.get("forcer", False)) if isinstance(request.data, dict) else False,
            motif=str(request.data.get("motif", ""))[:300] if isinstance(request.data, dict) else "",
        )
        return Response(VacationSerializer(vacation).data)

    @extend_schema(
        parameters=[OpenApiParameter(n, str) for n in ("agent", "site", "du", "au", "papier")],
        responses={(200, "application/pdf"): bytes},
    )
    @action(detail=False, methods=["get"], url_path="planning-pdf")
    def planning_pdf(self, request: Request) -> HttpResponse:
        """IMP-02 : planning PDF d'un agent ou d'un site (noir et blanc, date d'édition, QR code)."""
        from apps.referentiel.models import Site

        p = request.query_params
        try:
            du, au = date.fromisoformat(p.get("du", "")), date.fromisoformat(p.get("au", ""))
        except ValueError as erreur:
            raise ErreurValidation("Dates au format AAAA-MM-JJ attendues.", code="dates_invalides") from erreur
        agent = Agent.objects.filter(pk=int(p["agent"])).first() if p.get("agent", "").isdigit() else None
        site = Site.objects.filter(pk=int(p["site"])).first() if p.get("site", "").isdigit() else None
        if (p.get("agent") and agent is None) or (p.get("site") and site is None):
            raise NotFound()
        pdf = services.planning_pdf(
            acteur=agent_courant(request), du=du, au=au, agent=agent, site=site, format_papier=p.get("papier", "A4")
        )
        reponse = HttpResponse(pdf, content_type="application/pdf")
        reponse["Content-Disposition"] = f'attachment; filename="planning-{du:%Y%m%d}-{au:%Y%m%d}.pdf"'
        return reponse

    @extend_schema(responses={200: dict})
    @action(detail=True, methods=["get"])
    def candidats(self, request: Request, pk: str | None = None) -> Response:
        """PER-04 : propositions d'affectation (remplaçant compris), règles de temps de travail indiquées."""
        return Response(
            [
                {
                    "agent": c["agent"].pk,
                    "nom": str(c["agent"]),
                    "minutes_semaine": c["minutes_semaine"],
                    "prefere": c["prefere"],
                    "conforme": c["conforme"],
                    "violations": c["violations"],
                }
                for c in services.candidats(self.get_object())
            ]
        )

    @extend_schema(request=AffectationSerializer, responses=VacationSerializer)
    @action(detail=True, methods=["post"])
    def affecter(self, request: Request, pk: str | None = None) -> Response:
        entree = AffectationSerializer(data=request.data)
        entree.is_valid(raise_exception=True)
        d = entree.validated_data
        vacation = services.affecter(
            self.get_object(), d["agent"], acteur=agent_courant(request), forcer=d["forcer"], motif=d["motif"]
        )
        return Response(VacationSerializer(vacation).data)

    @extend_schema(
        request={"application/json": {"type": "object", "properties": {"motif": {"type": "string"}}}},
        responses=VacationSerializer,
    )
    @action(detail=True, methods=["post"])
    def annuler(self, request: Request, pk: str | None = None) -> Response:
        motif = str(request.data.get("motif", "")) if isinstance(request.data, dict) else ""
        if len(motif.strip()) < 3:
            raise ErreurValidation("Indiquez le motif.", code="motif_requis")
        return Response(
            VacationSerializer(services.annuler_vacation(self.get_object(), acteur=agent_courant(request), motif=motif)).data
        )


class LigneTrameSerializer(serializers.ModelSerializer):
    agent_nom = serializers.CharField(source="agent.__str__", read_only=True, default="")

    class Meta:
        model = LigneTrame
        fields = ["id", "trame", "jour", "heure_debut", "heure_fin", "agent", "agent_nom", "type"]


class TrameSerializer(serializers.ModelSerializer):
    lignes = LigneTrameSerializer(many=True, read_only=True)
    site_nom = serializers.CharField(source="site.nom", read_only=True)
    saison_nom = serializers.CharField(source="saison.nom", read_only=True)

    class Meta:
        model = Trame
        fields = ["id", "nom", "saison", "saison_nom", "site", "site_nom", "appliquee_le", "lignes"]
        read_only_fields = ["appliquee_le"]


class VueTrames(VuePerimetre):
    queryset = Trame.objects.select_related("site", "saison").prefetch_related("lignes__agent")
    serializer_class = TrameSerializer
    chemin_site = "site"
    actions_requises = {**LECTURE_ECRITURE, "appliquer": "planifier_personnel"}
    filterset_fields = ["saison", "site"]

    @extend_schema(request=None, responses={200: dict})
    @action(detail=True, methods=["post"])
    def appliquer(self, request: Request, pk: str | None = None) -> Response:
        """PER-03 : génère les vacations de la semaine type sur toute la saison."""
        return Response(services.appliquer_trame(self.get_object(), acteur=agent_courant(request)))


class VueLignesTrame(VuePerimetre):
    queryset = LigneTrame.objects.select_related("agent", "trame")
    serializer_class = LigneTrameSerializer
    chemin_site = "trame__site"
    actions_requises = LECTURE_ECRITURE
    filterset_fields = ["trame"]


class AbsenceSerializer(serializers.ModelSerializer):
    agent_nom = serializers.CharField(source="agent.__str__", read_only=True)

    class Meta:
        model = Absence
        fields = ["id", "agent", "agent_nom", "debut", "fin", "nature", "commentaire", "cree_le"]
        read_only_fields = ["cree_le"]


class VueAbsences(VuePerimetre):
    """PER-06 : saisir une absence libère les vacations de l'agent (elles deviennent « à pourvoir »)."""

    queryset = Absence.objects.select_related("agent")
    serializer_class = AbsenceSerializer
    chemin_site = "agent__sites"
    actions_requises = LECTURE_ECRITURE
    filterset_fields = ["agent", "nature"]
    http_method_names = ["get", "post", "head", "options"]

    def create(self, request: Request, *args: Any, **kwargs: Any) -> Response:
        entree = AbsenceSerializer(data=request.data)
        entree.is_valid(raise_exception=True)
        d = entree.validated_data
        self._verifier_objet(d["agent"])
        absence, liberees = services.saisir_absence(
            d["agent"],
            acteur=agent_courant(request),
            debut=d["debut"],
            fin=d["fin"],
            nature=d["nature"],
            commentaire=d.get("commentaire", ""),
        )
        return Response(
            {**AbsenceSerializer(absence).data, "vacations_liberees": VacationSerializer(liberees, many=True).data},
            status=status.HTTP_201_CREATED,
        )


class IncidentSerializer(serializers.ModelSerializer):
    site_nom = serializers.CharField(source="site.nom", read_only=True)
    espace_nom = serializers.CharField(source="espace.nom", read_only=True, default="")
    usager_nom = serializers.CharField(source="usager.nom", read_only=True, default="")
    signale_par_nom = serializers.CharField(source="signale_par.__str__", read_only=True, default="")

    class Meta:
        model = Incident
        fields = [
            "id",
            "site",
            "site_nom",
            "espace_nom",
            "occurrence",
            "usager",
            "usager_nom",
            "nature",
            "gravite",
            "description",
            "constate_le",
            "signale_par_nom",
            "source",
            "traite",
            "suite_donnee",
            "cree_le",
        ]
        read_only_fields = ["usager", "source", "cree_le", "espace_nom", "usager_nom", "signale_par_nom"]

    def get_fields(self) -> dict[str, Any]:
        champs = super().get_fields()
        if self.instance is not None:
            # Le traitement d'un incident ne change ni sa séance, ni son site, ni son usager (PER-09).
            for nom in ("site", "occurrence", "nature", "gravite", "description", "constate_le"):
                champs[nom].read_only = True
        return champs


class VueIncidents(VuePerimetre):
    """PER-09 : incidents rattachés à la séance et à l'usager ; le traitement est tracé."""

    queryset = Incident.objects.select_related("site", "espace", "usager", "signale_par")
    serializer_class = IncidentSerializer
    chemin_site = "site"
    actions_requises = LECTURE_ECRITURE
    filterset_fields = ["site", "traite", "gravite", "usager"]
    http_method_names = ["get", "post", "patch", "head", "options"]

    def create(self, request: Request, *args: Any, **kwargs: Any) -> Response:
        entree = IncidentSerializer(data=request.data)
        entree.is_valid(raise_exception=True)
        d = entree.validated_data
        self._verifier_objet(d["site"])
        if d.get("occurrence") is not None:
            self._verifier_objet(d["occurrence"])
        incident = services.signaler_incident(
            acteur=agent_courant(request),
            source="backoffice",
            site=d["site"],
            nature=d["nature"],
            gravite=d.get("gravite", "mineur"),
            description=d["description"],
            constate_le=d["constate_le"],
            occurrence=d.get("occurrence"),
        )
        return Response(IncidentSerializer(incident).data, status=status.HTTP_201_CREATED)


class AppareilSerializer(serializers.ModelSerializer):
    agent_nom = serializers.CharField(source="agent.__str__", read_only=True)
    certificat = serializers.CharField(
        write_only=True, required=False, allow_blank=True, help_text="PEM du certificat (option B)."
    )

    class Meta:
        model = Appareil
        fields = [
            "id",
            "agent",
            "agent_nom",
            "libelle",
            "empreinte_certificat",
            "certificat",
            "actif",
            "a_autoriser",
            "enregistre_le",
            "revoque_le",
            "derniere_synchronisation",
        ]
        read_only_fields = [
            "empreinte_certificat",
            "actif",
            "a_autoriser",
            "enregistre_le",
            "revoque_le",
            "derniere_synchronisation",
        ]

    def validate(self, donnees: dict[str, Any]) -> dict[str, Any]:
        certificat = donnees.pop("certificat", "")
        if certificat:
            donnees["empreinte_certificat"] = empreinte_certificat(certificat)
        return donnees


class VueAppareils(VuePerimetre):
    """SEC-10 : appareils des gardiens ; retirer un appareil coupe ses sessions."""

    queryset = Appareil.objects.select_related("agent")
    serializer_class = AppareilSerializer
    chemin_site = "agent__sites"
    actions_requises = {
        "lecture": "lire_personnel",
        "ecriture": "gerer_appareils",
        "retirer": "gerer_appareils",
        "autoriser": "gerer_appareils",
    }
    filterset_fields = ["agent", "actif"]
    http_method_names = ["get", "post", "head", "options"]

    @extend_schema(request=None, responses=AppareilSerializer)
    @action(detail=True, methods=["post"])
    def retirer(self, request: Request, pk: str | None = None) -> Response:
        appareil = self.get_object()
        appareil.actif, appareil.revoque_le = False, timezone.now()
        appareil.save(update_fields=["actif", "revoque_le"])
        appareil.jetons.filter(revoque_le__isnull=True).update(revoque_le=timezone.now())
        journaliser("retirer_appareil", appareil, acteur=agent_courant(request))
        return Response(AppareilSerializer(appareil).data)

    @extend_schema(request=None, responses=AppareilSerializer)
    @action(detail=True, methods=["post"])
    def autoriser(self, request: Request, pk: str | None = None) -> Response:
        """Nouvel appareil d'un agent dont un appareil a été retiré, ou au-delà de deux appareils : autorisation explicite."""
        appareil = self.get_object()
        if appareil.revoque_le is not None:
            raise ErreurMetier(
                "Un appareil retiré ne se réactive pas : l'agent se connecte depuis son nouvel appareil.", code="appareil_retire"
            )
        appareil.actif, appareil.a_autoriser = True, False
        appareil.save(update_fields=["actif", "a_autoriser"])
        journaliser("autoriser_appareil", appareil, acteur=agent_courant(request))
        return Response(AppareilSerializer(appareil).data)


class SaisieSerializer(serializers.ModelSerializer):
    agent_nom = serializers.CharField(source="agent.__str__", read_only=True)

    class Meta:
        model = SaisieMobile
        fields = [
            "id",
            "uuid",
            "agent",
            "agent_nom",
            "appareil",
            "type",
            "horodatage_appareil",
            "donnees",
            "statut",
            "message",
            "recue_le",
        ]
        read_only_fields = fields


class VueSaisies(VuePerimetre):
    """MOB-06 : saisies reçues du terrain, dont celles conservées en conflit à examiner."""

    queryset = SaisieMobile.objects.select_related("agent")
    serializer_class = SaisieSerializer
    chemin_site = "agent__sites"
    actions_requises = {"lecture": "lire_personnel", "examinee": "planifier_personnel"}
    filterset_fields = ["statut", "type", "agent"]
    http_method_names = ["get", "post", "head", "options"]

    def create(self, request: Request, *args: Any, **kwargs: Any) -> Response:
        return Response({"code": "non_autorise", "message": "Les saisies viennent de l'application mobile."}, status=405)

    @extend_schema(request=None, responses=SaisieSerializer)
    @action(detail=True, methods=["post"])
    def examinee(self, request: Request, pk: str | None = None) -> Response:
        saisie = self.get_object()
        SaisieMobile.objects.filter(pk=saisie.pk).update(traitee_par=agent_courant(request))
        journaliser("examiner_saisie_mobile", saisie, acteur=agent_courant(request))
        return Response(SaisieSerializer(SaisieMobile.objects.get(pk=saisie.pk)).data)


class PeriodeSerializer(serializers.Serializer):
    du = serializers.DateField()
    au = serializers.DateField()
    site = serializers.IntegerField(required=False)
    export = serializers.ChoiceField(choices=["json", "csv"], default="json")


class VueCompteurs(APIView):
    """PER-07 : compteurs d'heures par agent sur la période (dans le périmètre) et export pour la paie."""

    actions_requises = {"get": "lire_personnel"}

    def _agents(self, request: Request, site: int | None) -> QuerySet[Agent]:
        # Un agent parti en cours de mois reste dans les compteurs de la période où il a des vacations (PER-07).
        d = PeriodeSerializer(data=request.query_params)
        d.is_valid(raise_exception=True)
        debut = datetime.combine(d.validated_data["du"], time.min, tzinfo=PARIS)
        fin = datetime.combine(d.validated_data["au"] + timedelta(days=1), time.min, tzinfo=PARIS)
        agents = Agent.objects.filter(Q(actif=True) | Q(vacations__debut__lt=fin, vacations__fin__gt=debut))
        sites = sites_autorises(agent_courant(request), "lire_personnel")
        if sites is not None:
            agents = agents.filter(sites__in=sites)
        if site:
            agents = agents.filter(sites=site)
        return agents.distinct().order_by("nom", "prenom")

    @extend_schema(parameters=[PeriodeSerializer], responses={200: dict})
    def get(self, request: Request) -> Response | HttpResponse:
        entree = PeriodeSerializer(data=request.query_params)
        entree.is_valid(raise_exception=True)
        d = entree.validated_data
        if d["au"] < d["du"] or (d["au"] - d["du"]).days > 92:
            raise ErreurValidation("Période de 3 mois au plus.", code="periode_invalide")
        lignes = services.compteurs(self._agents(request, d.get("site")), d["du"], d["au"])
        if d["export"] == "csv":
            journaliser(
                "exporter_compteurs_paie",
                objet_type="personnel.agent",
                objet_id="*",
                apres={"du": str(d["du"]), "au": str(d["au"])},
                acteur=agent_courant(request),
            )
            reponse = HttpResponse(services.export_paie(lignes, d["du"], d["au"]), content_type="text/csv; charset=utf-8")
            reponse["Content-Disposition"] = f'attachment; filename="compteurs-{d["du"]:%Y%m%d}-{d["au"]:%Y%m%d}.csv"'
            return reponse
        return Response(
            [
                {**{k: v for k, v in ligne.items() if k != "agent"}, "agent": ligne["agent"].pk, "nom": str(ligne["agent"])}
                for ligne in lignes
            ]
        )


class VueIcal(APIView):
    """PER-08 : flux iCal personnel ; le jeton du lien remplace l'authentification et se révoque."""

    authentication_classes: list[type] = []
    permission_classes: list[type] = []
    throttle_scope = "public"

    @extend_schema(responses={(200, "text/calendar"): bytes})
    def get(self, request: Request, jeton: str) -> HttpResponse:
        try:
            contenu = services.flux_ical(jeton)
        except ErreurMetier as erreur:
            raise NotFound() from erreur
        reponse = HttpResponse(contenu, content_type="text/calendar; charset=utf-8")
        reponse["Cache-Control"] = "private, max-age=900"
        return reponse
