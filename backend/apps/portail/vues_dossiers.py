"""Portail : demandes guidées en quatre étapes avec brouillon (POR-04), suivi et annulation (POR-05),
campagnes annuelles (PLA-05) et messagerie par dossier (POR-08, COM-02).

Le brouillon conserve les créneaux saisis sans rien réserver ; à l'envoi, chaque créneau devient une
réservation « demande » par les mêmes règles que le guichet (horaires, fermetures, calendrier,
délai minimal, horizon) : les contrôles sont ceux de l'API métier, jamais seulement du navigateur.
"""

from __future__ import annotations

from datetime import date, datetime, time
from typing import Any

from django.conf import settings
from django.db import transaction
from django.db.models import QuerySet
from django.utils import timezone
from drf_spectacular.utils import extend_schema
from rest_framework import serializers, status
from rest_framework.parsers import MultiPartParser
from rest_framework.request import Request
from rest_framework.response import Response

from apps.audit.services import journaliser
from apps.communication.models import Message
from apps.communication.services import notifier
from apps.noyau.exceptions import ErreurMetier, ErreurValidation
from apps.noyau.parametres import parametre
from apps.referentiel.models import Espace
from apps.reservations import conditions, services
from apps.reservations.models import STATUTS, Campagne, Dossier, Occurrence, Reservation, TypeReservation
from apps.reservations.recurrence import PARIS, decrire, valider_regle
from apps.usagers.models import Contact, Usager

from .authentification import Introuvable, contact_courant, usager_autorise, usagers_du_contact
from .catalogue import espaces_publics
from .securite import VueContact
from .vues_materiel import MaterielDemandeSerializer, materialiser_brouillon, representation_prets, valider_materiel_demande
from .vues_usagers import deposer_depuis_portail, representation_piece

JOURS_RRULE = ["MO", "TU", "WE", "TH", "FR", "SA", "SU"]
STATUTS_PUBLICS = {
    **dict(STATUTS),
    "demande": "Demande envoyée",
    "en_instruction": "En cours d'examen",
    "option": "Pré-réservation (option)",
    "validee": "Accordée",
    "confirmee": "Confirmée",
}
ANNULABLES = {"demande", "en_instruction", "option", "validee", "confirmee"}


def dossiers_du_contact(contact: Contact) -> QuerySet[Dossier]:
    return Dossier.objects.filter(usager__in=usagers_du_contact(contact)).select_related("usager", "type_reservation", "campagne")


def dossier_autorise(contact: Contact, identifiant: Any) -> Dossier:
    dossier = dossiers_du_contact(contact).filter(pk=identifiant).first() if str(identifiant).isdigit() else None
    if dossier is None:
        raise Introuvable()
    return dossier


# --- Créneaux saisis sur le portail --------------------------------------------------------------


class CreneauSerializer(serializers.Serializer):
    espace = serializers.IntegerField(min_value=1)
    date_debut = serializers.DateField()
    date_fin = serializers.DateField(required=False, allow_null=True)
    heure_debut = serializers.TimeField()
    heure_fin = serializers.TimeField()
    jours = serializers.ListField(child=serializers.ChoiceField(choices=JOURS_RRULE), required=False, default=list, max_length=7)
    toutes_les_semaines = serializers.IntegerField(min_value=1, max_value=4, default=1)
    exclure_vacances = serializers.BooleanField(default=True)

    def validate(self, donnees: dict[str, Any]) -> dict[str, Any]:
        fin = donnees.get("date_fin") or donnees["date_debut"]
        if fin < donnees["date_debut"]:
            raise serializers.ValidationError({"date_fin": "La date de fin doit suivre la date de début."})
        if donnees["heure_fin"] == donnees["heure_debut"]:
            raise serializers.ValidationError({"heure_fin": "L'heure de fin doit différer de l'heure de début."})
        if fin != donnees["date_debut"] and not donnees.get("jours"):
            raise serializers.ValidationError({"jours": "Choisissez le ou les jours de la semaine concernés."})
        donnees["date_fin"] = fin
        return donnees


def _espace_public(identifiant: int) -> Espace:
    espace = espaces_publics().filter(pk=identifiant).first()
    if espace is None:
        raise ErreurValidation("Cet espace n'est pas réservable en ligne.", code="espace_non_reservable")
    return espace


def _regle(creneau: dict[str, Any]) -> str:
    if not creneau.get("jours") or creneau["date_fin"] == creneau["date_debut"]:
        return ""
    regle = "FREQ=WEEKLY;BYDAY=" + ",".join(j for j in JOURS_RRULE if j in creneau["jours"])
    if creneau.get("toutes_les_semaines", 1) > 1:
        regle += f";INTERVAL={creneau['toutes_les_semaines']}"
    return valider_regle(regle)


def _serialiser_creneau(creneau: dict[str, Any]) -> dict[str, Any]:
    return {
        **creneau,
        "date_debut": creneau["date_debut"].isoformat(),
        "date_fin": creneau["date_fin"].isoformat(),
        "heure_debut": creneau["heure_debut"].strftime("%H:%M"),
        "heure_fin": creneau["heure_fin"].strftime("%H:%M"),
    }


def _lire_creneau(brut: dict[str, Any]) -> dict[str, Any]:
    return {
        **brut,
        "date_debut": date.fromisoformat(brut["date_debut"]),
        "date_fin": date.fromisoformat(brut["date_fin"]),
        "heure_debut": time.fromisoformat(brut["heure_debut"]),
        "heure_fin": time.fromisoformat(brut["heure_fin"]),
    }


def _reservation_fictive(dossier: Dossier, creneau: dict[str, Any], espace: Espace) -> Reservation:
    return Reservation(
        dossier=dossier,
        espace=espace,
        date_debut=creneau["date_debut"],
        date_fin=creneau["date_fin"],
        heure_debut=creneau["heure_debut"],
        heure_fin=creneau["heure_fin"],
        recurrence=_regle(creneau),
        exclure_vacances=creneau.get("exclure_vacances", True),
        exclure_feries=True,
    )


def apercu_creneaux(dossier: Dossier) -> list[dict[str, Any]]:
    """Description et disponibilité de chaque créneau du brouillon, sans aucun nom d'autre usager (POR-02)."""
    resultat = []
    for brut in dossier.brouillon_creneaux:
        creneau = _lire_creneau(brut)
        espace = espaces_publics().filter(pk=creneau["espace"]).first()
        if espace is None:
            resultat.append({**brut, "erreur": "Cet espace n'est plus réservable en ligne."})
            continue
        fictive = _reservation_fictive(dossier, creneau, espace)
        try:
            plages = services._valider_creneau(espace, fictive, forcer_horaires=False)
        except ErreurMetier as erreur:
            resultat.append({**brut, "espace_nom": espace.nom, "description": decrire(fictive), "erreur": erreur.message})
            continue
        indisponibles = [d for d, f in plages if services.conflits(espace, d, f)]
        resultat.append(
            {
                **brut,
                "espace_nom": espace.nom,
                "site_nom": espace.batiment.site.nom,
                "description": decrire(fictive),
                "seances": len(plages),
                "indisponibles": [timezone.localtime(d, PARIS).strftime("%d/%m/%Y %H:%M") for d in indisponibles[:20]],
                "erreur": "",
            }
        )
    return resultat


# --- Représentation ----------------------------------------------------------------------------------


def _seance(o: Occurrence, maintenant: datetime) -> dict[str, Any]:
    return {
        "id": o.pk,
        "debut": o.debut,
        "fin": o.fin,
        "espace_nom": o.espace.nom,
        "statut": o.statut,
        "statut_libelle": STATUTS_PUBLICS.get(o.statut, o.statut),
        "annulable": o.statut in ANNULABLES and o.debut > maintenant,
        "annulation_tardive_si_annulee": o.statut in ANNULABLES and services.est_tardive(o, maintenant),
        "annulation_tardive": o.annulation_tardive,
        # Le signalement interne peut citer un autre usager (conflit) : jamais exposé tel quel (POR-02).
        "signalement": "Séance à revoir par le service des équipements, qui vous contactera." if o.signalement else "",
    }


def representation_dossier(dossier: Dossier, *, detail: bool = False) -> dict[str, Any]:
    maintenant = timezone.now()
    donnees: dict[str, Any] = {
        "id": dossier.pk,
        "numero": dossier.numero,
        "objet": dossier.objet,
        "usager": dossier.usager_id,
        "usager_nom": dossier.usager.nom,
        "type_reservation": dossier.type_reservation_id,
        "type_libelle": dossier.type_reservation.libelle,
        "campagne": dossier.campagne_id,
        "brouillon": dossier.brouillon,
        "etape": dossier.brouillon_etape,
        "statut": "brouillon" if dossier.brouillon else dossier.statut,
        "statut_libelle": "Brouillon" if dossier.brouillon else STATUTS_PUBLICS.get(dossier.statut, dossier.statut),
        "cree_le": dossier.cree_le,
        "depose_le": dossier.depose_le,
        "messages_non_lus": dossier.messages.filter(auteur_contact__isnull=True, lu_par_usager_le__isnull=True).count(),
    }
    if not detail:
        return donnees
    donnees.update(
        {
            "activite": dossier.activite,
            "effectif": dossier.effectif,
            "observations": dossier.observations,
            "creneaux": apercu_creneaux(dossier) if dossier.brouillon else [],
            "materiel_demande": dossier.brouillon_materiel if dossier.brouillon else [],
            "materiel": representation_prets(dossier),
            "reservations": [
                {
                    "id": r.pk,
                    "espace": r.espace_id,
                    "espace_nom": r.espace.nom,
                    "site_nom": r.espace.batiment.site.nom,
                    "description": r.description,
                    "statut": r.statut,
                    "statut_libelle": STATUTS_PUBLICS.get(r.statut, r.statut),
                    "motif_refus": r.motif_refus,
                    "option_expire_le": r.option_expire_le,
                    "a_faire": conditions.conditions_manquantes(r) if r.statut in {"validee", "option"} else [],
                    "seances": [_seance(o, maintenant) for o in r.occurrences.select_related("espace").order_by("debut")[:400]],
                }
                for r in dossier.reservations.select_related("espace__batiment__site").order_by("date_debut")
            ],
        }
    )
    return donnees


# --- Dossiers ----------------------------------------------------------------------------------------


class NouveauDossierSerializer(serializers.Serializer):
    usager = serializers.IntegerField(min_value=1)
    type_reservation = serializers.IntegerField(min_value=1, required=False)
    objet = serializers.CharField(max_length=250, required=False, allow_blank=True, default="")
    creneaux = serializers.ListField(child=CreneauSerializer(), required=False, default=list, max_length=10)


class ModificationDossierSerializer(serializers.Serializer):
    etape = serializers.IntegerField(min_value=1, max_value=4, required=False)
    type_reservation = serializers.IntegerField(min_value=1, required=False)
    objet = serializers.CharField(max_length=250, required=False, allow_blank=True)
    activite = serializers.CharField(max_length=150, required=False, allow_blank=True)
    effectif = serializers.IntegerField(min_value=0, max_value=100_000, required=False)
    observations = serializers.CharField(max_length=2000, required=False, allow_blank=True)
    creneaux = serializers.ListField(child=CreneauSerializer(), required=False, max_length=10)
    materiel = serializers.ListField(child=MaterielDemandeSerializer(), required=False, max_length=20)


def _type_autorise(identifiant: int | None, usager: Usager, campagne: Campagne | None) -> TypeReservation:
    if campagne is not None:
        return TypeReservation.objects.get(code="creneau_annuel")
    type_reservation = TypeReservation.objects.filter(pk=identifiant, ouvert_portail=True).first() if identifiant else None
    if type_reservation is None or (type_reservation.types_usager and usager.type not in type_reservation.types_usager):
        raise ErreurValidation("Ce type de demande n'est pas proposé pour votre structure.", code="type_non_propose")
    return type_reservation


def _enregistrer_creneaux(dossier: Dossier, creneaux: list[dict[str, Any]]) -> None:
    for creneau in creneaux:
        _espace_public(creneau["espace"])
        _regle(creneau)
    dossier.brouillon_creneaux = [_serialiser_creneau(c) for c in creneaux]


def creer_brouillon(contact: Contact, usager: Usager, donnees: dict[str, Any], campagne: Campagne | None = None) -> Dossier:
    if usager.statut != "valide":
        raise ErreurMetier(
            "Votre structure doit être validée par la Ville avant de déposer une demande.", code="usager_non_valide"
        )
    type_reservation = _type_autorise(donnees.get("type_reservation"), usager, campagne)
    with transaction.atomic():
        dossier = services.creer_dossier(
            acteur=contact,
            usager=usager,
            type_reservation=type_reservation,
            objet=donnees.get("objet") or "Demande en cours de saisie",
            contact=contact,
            origine="campagne" if campagne else "portail",
            brouillon=True,
            campagne=campagne,
        )
        if donnees.get("creneaux"):
            _enregistrer_creneaux(dossier, donnees["creneaux"])
            dossier.save(update_fields=["brouillon_creneaux"])
    return dossier


class VueDossiersPortail(VueContact):
    def get_throttles(self) -> list[Any]:
        self.throttle_scope = "depot" if self.request.method == "POST" else "public"
        return super().get_throttles()

    @extend_schema(responses={200: dict})
    def get(self, request: Request) -> Response:
        contact = contact_courant(request)
        qs = dossiers_du_contact(contact).order_by("-cree_le")
        usager = request.query_params.get("usager", "")
        if usager.isdigit():
            qs = qs.filter(usager_id=int(usager))
        return Response([representation_dossier(d) for d in qs[:200]])

    @extend_schema(request=NouveauDossierSerializer, responses={201: dict})
    def post(self, request: Request) -> Response:
        contact = contact_courant(request)
        entree = NouveauDossierSerializer(data=request.data)
        entree.is_valid(raise_exception=True)
        usager = usager_autorise(contact, entree.validated_data["usager"], valide=True)
        dossier = creer_brouillon(contact, usager, entree.validated_data)
        return Response(representation_dossier(dossier, detail=True), status=status.HTTP_201_CREATED)


class VueDossierPortail(VueContact):
    @extend_schema(responses={200: dict})
    def get(self, request: Request, pk: int) -> Response:
        return Response(representation_dossier(dossier_autorise(contact_courant(request), pk), detail=True))

    @extend_schema(request=ModificationDossierSerializer, responses={200: dict})
    def patch(self, request: Request, pk: int) -> Response:
        contact = contact_courant(request)
        dossier = dossier_autorise(contact, pk)
        if not dossier.brouillon:
            raise ErreurMetier(
                "La demande est envoyée : écrivez au service par la messagerie du dossier pour la modifier.",
                code="dossier_envoye",
            )
        entree = ModificationDossierSerializer(data=request.data, partial=True)
        entree.is_valid(raise_exception=True)
        d = entree.validated_data
        with transaction.atomic():
            if "type_reservation" in d:
                dossier.type_reservation = _type_autorise(d["type_reservation"], dossier.usager, dossier.campagne)
            for champ in ("objet", "activite", "effectif", "observations"):
                if champ in d:
                    setattr(dossier, champ, d[champ])
            if "etape" in d:
                dossier.brouillon_etape = d["etape"]
            if "creneaux" in d:
                _enregistrer_creneaux(dossier, d["creneaux"])
            if "materiel" in d:
                dossier.brouillon_materiel = valider_materiel_demande(d["materiel"])
            dossier.save()
        return Response(representation_dossier(dossier, detail=True))

    @extend_schema(responses={204: None})
    def delete(self, request: Request, pk: int) -> Response:
        """Abandon d'un brouillon (rien n'a été réservé)."""
        contact = contact_courant(request)
        dossier = dossier_autorise(contact, pk)
        if not dossier.brouillon or dossier.reservations.exists():
            raise ErreurMetier("Seul un brouillon peut être abandonné ; une demande envoyée s'annule.", code="dossier_envoye")
        journaliser("abandonner_brouillon", dossier, acteur=contact)
        dossier.delete()
        return Response(status=status.HTTP_204_NO_CONTENT)


@transaction.atomic
def envoyer_demande(dossier: Dossier, contact: Contact) -> Dossier:
    """Étape 4 : chaque créneau devient une réservation « demande » ; accusé de réception à l'usager."""
    dossier = Dossier.objects.select_for_update().get(pk=dossier.pk)
    if not dossier.brouillon:
        raise ErreurMetier("Cette demande est déjà envoyée.", code="dossier_envoye")
    if not dossier.brouillon_creneaux:
        raise ErreurValidation("Ajoutez au moins un créneau (étape 1).", code="creneau_requis")
    if not dossier.objet.strip() or dossier.objet == "Demande en cours de saisie":
        raise ErreurValidation("Indiquez l'objet de la demande (étape 2).", code="objet_requis")
    # Contrôles du guichet rejoués à l'envoi : la structure ou le type ont pu changer depuis le brouillon.
    if dossier.usager.statut != "valide":
        raise ErreurMetier(
            "Votre structure n'est plus en mesure de déposer une demande : contactez le service des équipements.",
            code="usager_non_valide",
        )
    sites = None
    saison = None
    if dossier.campagne is not None:
        saison = services._verifier_campagne(dossier.campagne, contact, dossier.saison)
        sites = dossier.campagne.sites_concernes()
        types = dossier.type_reservation.types_usager
        if types and dossier.usager.type not in types:
            raise ErreurValidation("Cette campagne n'est pas ouverte à votre type de structure.", code="type_non_propose")
    else:
        _type_autorise(dossier.type_reservation_id, dossier.usager, None)
    erreurs = []
    for rang, brut in enumerate(dossier.brouillon_creneaux, start=1):
        creneau = _lire_creneau(brut)
        espace = _espace_public(creneau["espace"])
        if sites is not None and espace.batiment.site_id not in sites:
            erreurs.append(f"Créneau {rang} : {espace.nom} n'est pas proposé dans cette campagne.")
            continue
        if saison is not None and not saison.debut <= creneau["date_debut"] <= creneau["date_fin"] <= saison.fin:
            erreurs.append(
                f"Créneau {rang} : les dates doivent être comprises dans la saison {saison.nom} "
                f"(du {saison.debut:%d/%m/%Y} au {saison.fin:%d/%m/%Y})."
            )
            continue
        try:
            with transaction.atomic():
                services.ajouter_reservation(
                    dossier,
                    acteur=contact,
                    portail=True,
                    espace=espace,
                    date_debut=creneau["date_debut"],
                    date_fin=creneau["date_fin"],
                    heure_debut=creneau["heure_debut"],
                    heure_fin=creneau["heure_fin"],
                    recurrence=_regle(creneau),
                    exclure_vacances=creneau.get("exclure_vacances", True),
                )
        except ErreurMetier as erreur:
            texte = (
                "le calendrier des vacances scolaires de cette période n'est pas encore publié par la Ville ; choisissez "
                "d'autres dates ou contactez le service des équipements."
                if erreur.code == "calendrier_absent"
                else erreur.message
            )
            erreurs.append(f"Créneau {rang} : {texte}")
    if not erreurs:
        erreurs = materialiser_brouillon(dossier, contact)
    if erreurs:
        raise ErreurValidation(" ".join(erreurs), code="creneaux_invalides", details={"erreurs": erreurs})
    dossier.brouillon = False
    dossier.depose_le = timezone.now()
    dossier.save(update_fields=["brouillon", "depose_le"])
    Usager.objects.filter(pk=dossier.usager_id).update(derniere_activite=timezone.now())
    journaliser("envoyer_demande_portail", dossier, apres={"reservations": dossier.reservations.count()}, acteur=contact)
    notifier("demande_recue", {"dossier": dossier}, contacts=[contact], usager=dossier.usager, objet=dossier)
    return dossier


class VueEnvoyerDossier(VueContact):
    throttle_scope = "depot"

    @extend_schema(request=None, responses={200: dict})
    def post(self, request: Request, pk: int) -> Response:
        contact = contact_courant(request)
        dossier = envoyer_demande(dossier_autorise(contact, pk), contact)
        return Response(representation_dossier(dossier, detail=True))


class MotifPortailSerializer(serializers.Serializer):
    motif = serializers.CharField(max_length=300)


class VueAnnulerDossier(VueContact):
    """POR-05, PLA-10 : l'usager annule sa demande ou ses réservations à venir (tardive selon le délai)."""

    @extend_schema(request=MotifPortailSerializer, responses={200: dict})
    def post(self, request: Request, pk: int) -> Response:
        contact = contact_courant(request)
        dossier = dossier_autorise(contact, pk)
        entree = MotifPortailSerializer(data=request.data)
        entree.is_valid(raise_exception=True)
        actives = list(dossier.reservations.filter(statut__in=ANNULABLES))
        if not actives:
            raise ErreurMetier("Rien à annuler dans ce dossier.", code="rien_a_annuler")
        with transaction.atomic():
            for reservation in actives:
                services.annuler(reservation, acteur=contact, motif=entree.validated_data["motif"], par_usager=True)
        return Response(representation_dossier(dossier, detail=True))


class VueAnnulerSeance(VueContact):
    @extend_schema(request=MotifPortailSerializer, responses={200: dict})
    def post(self, request: Request, pk: int, seance: int) -> Response:
        contact = contact_courant(request)
        dossier = dossier_autorise(contact, pk)
        occurrence = Occurrence.objects.filter(pk=seance, reservation__dossier=dossier).first()
        if occurrence is None:
            raise Introuvable()
        if occurrence.debut <= timezone.now():
            raise ErreurMetier("Une séance passée ne peut plus être annulée.", code="seance_passee")
        entree = MotifPortailSerializer(data=request.data)
        entree.is_valid(raise_exception=True)
        occurrence = services.annuler_occurrence(
            occurrence, acteur=contact, motif=entree.validated_data["motif"], par_usager=True
        )
        return Response(_seance(occurrence, timezone.now()))


class VuePiecesDossier(VueContact):
    """Étape 3 : dépôt des pièces demandées pour la structure du dossier (POR-06)."""

    parser_classes = [MultiPartParser]
    throttle_scope = "televersement"

    @extend_schema(request={"multipart/form-data": dict}, responses={201: dict})
    def post(self, request: Request, pk: int) -> Response:
        contact = contact_courant(request)
        dossier = dossier_autorise(contact, pk)
        piece = deposer_depuis_portail(request, dossier.usager, contact)
        return Response(representation_piece(piece), status=status.HTTP_201_CREATED)


class VueTypesDemande(VueContact):
    """Types de demande proposés en ligne à une structure (POR-04)."""

    @extend_schema(responses={200: dict})
    def get(self, request: Request) -> Response:
        usager = usager_autorise(contact_courant(request), request.query_params.get("usager", ""))
        types = [
            {"id": t.pk, "libelle": t.libelle}
            for t in TypeReservation.objects.filter(ouvert_portail=True).order_by("ordre", "libelle")
            if not t.types_usager or usager.type in t.types_usager
        ]
        return Response(types)


# --- Campagnes --------------------------------------------------------------------------------------


def campagnes_ouvertes() -> QuerySet[Campagne]:
    aujourd_hui = timezone.localdate()
    return Campagne.objects.filter(statut="ouverte", ouverture__lte=aujourd_hui, cloture__gte=aujourd_hui).select_related(
        "saison"
    )


class VueCampagnesPortail(VueContact):
    @extend_schema(responses={200: dict})
    def get(self, request: Request) -> Response:
        return Response(
            [
                {
                    "id": c.pk,
                    "nom": c.nom,
                    "saison": c.saison.nom,
                    "saison_debut": c.saison.debut,
                    "saison_fin": c.saison.fin,
                    "cloture": c.cloture,
                    "sites": [s.nom for s in c.sites.all()],
                }
                for c in campagnes_ouvertes().prefetch_related("sites")
            ]
        )


class DemandeCampagneSerializer(serializers.Serializer):
    usager = serializers.IntegerField(min_value=1)
    objet = serializers.CharField(max_length=250, required=False, allow_blank=True, default="")


class VueDemandeCampagne(VueContact):
    throttle_scope = "depot"

    @extend_schema(request=DemandeCampagneSerializer, responses={201: dict})
    def post(self, request: Request, pk: int) -> Response:
        contact = contact_courant(request)
        campagne = campagnes_ouvertes().filter(pk=pk).first()
        if campagne is None:
            raise Introuvable()
        entree = DemandeCampagneSerializer(data=request.data)
        entree.is_valid(raise_exception=True)
        usager = usager_autorise(contact, entree.validated_data["usager"], valide=True)
        dossier = creer_brouillon(contact, usager, {"objet": entree.validated_data["objet"]}, campagne=campagne)
        return Response(representation_dossier(dossier, detail=True), status=status.HTTP_201_CREATED)


# --- Messagerie (POR-08, COM-02) ------------------------------------------------------------------------


class MessageSerializer(serializers.Serializer):
    corps = serializers.CharField(max_length=5000, trim_whitespace=True)


def representation_message(message: Message) -> dict[str, Any]:
    return {
        "id": message.pk,
        "de_la_ville": message.de_la_ville,
        "auteur": "Service des équipements" if message.de_la_ville else str(message.auteur_contact or "Vous"),
        "corps": message.corps,
        "cree_le": message.cree_le,
        "lu": bool(message.lu_par_ville_le if not message.de_la_ville else message.lu_par_usager_le),
    }


class VueMessagesDossier(VueContact):
    def get_throttles(self) -> list[Any]:
        self.throttle_scope = "depot" if self.request.method == "POST" else "public"
        return super().get_throttles()

    @extend_schema(responses={200: dict})
    def get(self, request: Request, pk: int) -> Response:
        dossier = dossier_autorise(contact_courant(request), pk)
        messages = list(dossier.messages.select_related("auteur_contact").order_by("cree_le"))
        dossier.messages.filter(auteur_contact__isnull=True, lu_par_usager_le__isnull=True).update(
            lu_par_usager_le=timezone.now()
        )
        return Response([representation_message(m) for m in messages])

    @extend_schema(request=MessageSerializer, responses={201: dict})
    def post(self, request: Request, pk: int) -> Response:
        contact = contact_courant(request)
        dossier = dossier_autorise(contact, pk)
        entree = MessageSerializer(data=request.data)
        entree.is_valid(raise_exception=True)
        with transaction.atomic():
            message = Message.objects.create(dossier=dossier, auteur_contact=contact, corps=entree.validated_data["corps"])
            journaliser("ecrire_message_portail", message, apres={"dossier": dossier.numero}, acteur=contact)
            notifier(
                "message_usager",
                {
                    "dossier": dossier,
                    "usager": dossier.usager,
                    "auteur": str(contact),
                    "extrait": message.corps[:500],
                    "lien": f"{settings.BACKOFFICE_URL}/reservations/dossiers/{dossier.pk}",
                },
                courriels=[str(parametre("portail.service_courriel"))],
                objet=message,
            )
        return Response(representation_message(message), status=status.HTTP_201_CREATED)


# --- Notifications reçues (journal personnel) -------------------------------------------------------------


class VueNotificationsPortail(VueContact):
    @extend_schema(responses={200: dict})
    def get(self, request: Request) -> Response:
        from apps.communication.models import Notification

        contact = contact_courant(request)
        notifications = Notification.objects.filter(contact=contact, canal="courriel").order_by("-cree_le")[:100]
        return Response(
            [
                {"id": n.pk, "sujet": n.sujet, "corps": n.corps, "cree_le": n.cree_le, "lue": n.lue_le is not None}
                for n in notifications
            ]
        )


class VueNotificationLue(VueContact):
    @extend_schema(request=None, responses={204: None})
    def post(self, request: Request, pk: int) -> Response:
        from apps.communication.models import Notification

        mises_a_jour = Notification.objects.filter(pk=pk, contact=contact_courant(request), lue_le__isnull=True).update(
            lue_le=timezone.now()
        )
        if not mises_a_jour and not Notification.objects.filter(pk=pk, contact=contact_courant(request)).exists():
            raise Introuvable()
        return Response(status=status.HTTP_204_NO_CONTENT)
