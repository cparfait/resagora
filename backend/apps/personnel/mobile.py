"""API de l'application mobile des gardiens (MOB-01 à MOB-08, SEC-10).

- Option A (défaut) : l'application et `/api/mobile/*` sont servies sur le LAN, joint par le VPN de la Ville
  (smartphones gérés par MDM) ; canal « gestion ».
- Option B : `/api/mobile/*` est relayée par la façade DMZ (canal « portail ») ; l'appareil présente un certificat
  enregistré (empreinte transmise par la façade) et l'agent valide un second facteur (TOTP).

Le paquet descendant ne contient que ce dont l'agent a besoin (ses vacations, les séances de ses sites pendant
ces vacations, les grilles d'état des lieux) : ni montant, ni pièce justificative, ni autre site (MOB-07).
"""

from __future__ import annotations

import base64
import binascii
import hashlib
import secrets
import uuid as uuid_lib
from datetime import datetime, timedelta
from typing import Any
from urllib.parse import unquote

from django.conf import settings
from django.contrib.auth import authenticate
from django.core.cache import cache
from django.db import IntegrityError, transaction
from django.utils import timezone
from django.utils.dateparse import parse_datetime
from drf_spectacular.utils import extend_schema
from rest_framework import serializers, status
from rest_framework.authentication import BaseAuthentication
from rest_framework.exceptions import AuthenticationFailed, NotFound
from rest_framework.parsers import JSONParser, MultiPartParser
from rest_framework.permissions import BasePermission
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.audit.services import journaliser
from apps.communication.services import notifier
from apps.habilitations import totp
from apps.habilitations.models import Utilisateur
from apps.habilitations.services import peut
from apps.noyau import fichiers
from apps.noyau.chiffrement import empreinte_hmac
from apps.noyau.exceptions import AccesRefuse, ErreurMetier, ErreurValidation
from apps.noyau.parametres import parametre
from apps.reservations.models import Occurrence

from . import services
from .models import Agent, Appareil, JetonMobile, PhotoMobile, SaisieMobile, Vacation

# Session glissante : 7 jours sans synchronisation la ferment (MOB-08), 90 jours au plus depuis la connexion.
DUREE_JETON = timedelta(days=7)
DUREE_MAX_JETON = timedelta(days=90)
APPAREILS_ACTIFS_MAX = 2
ECHECS_MAX = 10
#: Message unique de tout refus antérieur au code TOTP : il ne dit pas si le mot de passe était juste (SEC-10).
REFUS_CONNEXION = "Connexion refusée : identifiant ou mot de passe incorrect, ou appareil non autorisé."
# Tolérances des saisies terrain (heure de l'appareil) : un pointage reste dans l'encadrement de la vacation, un état
# des lieux de sortie se fait en fin de séance, aucune saisie n'est datée dans le futur.
AVANCE_POINTAGE = timedelta(hours=1)
RETARD_POINTAGE = timedelta(hours=3)
DERIVE_HORLOGE = timedelta(minutes=5)
GRILLE_COMMUNE = [
    "Sol et revêtement",
    "Murs, portes et vitrages",
    "Éclairage",
    "Vestiaires et sanitaires",
    "Matériel et équipements",
    "Issues de secours dégagées",
    "Propreté générale",
]
GRILLES = {
    "salle-fetes": [*GRILLE_COMMUNE, "Cuisine et office", "Mobilier (tables, chaises)", "Sonorisation"],
    "salle-spectacle": [*GRILLE_COMMUNE, "Scène et coulisses", "Gradins et fauteuils", "Régie"],
    "terrain-exterieur": [
        "Pelouse ou revêtement",
        "Buts et filets",
        "Clôtures et portails",
        "Vestiaires et sanitaires",
        "Éclairage",
        "Propreté générale",
    ],
}


# --- Canal, authentification -----------------------------------------------------------------------------


def option_active(request: Request) -> bool:
    canal = getattr(settings, "CANAL", "gestion")
    return (settings.MOBILE_OPTION == "A" and canal == "gestion") or (settings.MOBILE_OPTION == "B" and canal == "portail")


def empreinte_certificat(valeur: str) -> str:
    """SHA-256 du certificat DER, à partir du PEM (avec ou sans en-têtes, éventuellement encodé dans l'URL)."""
    texte = unquote(valeur or "")
    corps = "".join(ligne for ligne in texte.replace("\\n", "\n").splitlines() if "-----" not in ligne).replace(" ", "")
    try:
        der = base64.b64decode(corps, validate=True)
    except (binascii.Error, ValueError) as erreur:
        raise ErreurValidation("Certificat d'appareil illisible.", code="certificat_invalide") from erreur
    return hashlib.sha256(der).hexdigest()


def _appareil_option_b(request: Request, agent: Agent | None = None) -> Appareil:
    """Option B : certificat transmis par le proxy DMZ (en-tête X-Forwarded-Tls-Client-Cert, relayé par la façade)."""
    brut = request.headers.get("X-Certificat-Appareil", "")
    if not brut:
        raise AccesRefuse("Appareil non reconnu.", code="certificat_appareil_requis")
    appareil = (
        Appareil.objects.filter(empreinte_certificat=empreinte_certificat(brut), actif=True).select_related("agent").first()
    )
    if appareil is None or (agent is not None and appareil.agent_id != agent.pk):
        raise AccesRefuse("Appareil non reconnu.", code="appareil_inconnu")
    return appareil


class AuthentificationMobile(BaseAuthentication):
    """En-tête « Authorization: Appareil <jeton> » ; en option B, le certificat doit être celui de l'appareil du jeton."""

    def authenticate(self, request: Request) -> tuple[Utilisateur, JetonMobile] | None:
        entete = request.headers.get("Authorization", "")
        if not entete.startswith("Appareil "):
            return None
        jeton = (
            JetonMobile.objects.select_related("agent__utilisateur", "appareil")
            .filter(
                empreinte=empreinte_hmac(entete.removeprefix("Appareil ").strip()),
                revoque_le__isnull=True,
                expire_le__gt=timezone.now(),
            )
            .first()
        )
        if jeton is None or jeton.agent.utilisateur is None or not jeton.agent.actif:
            raise AuthenticationFailed("Session expirée : reconnectez-vous.")
        if jeton.appareil is not None and not jeton.appareil.actif:
            raise AuthenticationFailed("Cet appareil a été retiré : contactez votre planificateur.")
        if settings.MOBILE_OPTION == "B":
            certificat = request.headers.get("X-Certificat-Appareil", "")
            if (
                not certificat
                or jeton.appareil is None
                or empreinte_certificat(certificat) != jeton.appareil.empreinte_certificat
            ):
                raise AuthenticationFailed("Appareil non reconnu.")
        utilisateur = jeton.agent.utilisateur
        if not utilisateur.is_active or not peut(utilisateur, "utiliser_mobile"):
            raise AuthenticationFailed("Accès à l'application mobile retiré.")
        maintenant = timezone.now()
        JetonMobile.objects.filter(pk=jeton.pk).update(
            dernier_usage=maintenant, expire_le=min(maintenant + DUREE_JETON, jeton.cree_le + DUREE_MAX_JETON)
        )
        return utilisateur, jeton

    def authenticate_header(self, request: Request) -> str:
        return 'Appareil realm="mobile"'


class MobileConnecte(BasePermission):
    def has_permission(self, request: Request, view: Any) -> bool:
        if not option_active(request):
            raise NotFound()
        return isinstance(request.auth, JetonMobile)


class VueMobile(APIView):
    authentication_classes = [AuthentificationMobile]
    permission_classes = [MobileConnecte]

    def agent(self, request: Request) -> Agent:
        jeton = request.auth
        assert isinstance(jeton, JetonMobile)
        return jeton.agent


class VueMobilePublique(APIView):
    authentication_classes: list[type] = []
    permission_classes: list[type] = []

    def initial(self, request: Request, *args: Any, **kwargs: Any) -> None:
        if not option_active(request):
            raise NotFound()
        super().initial(request, *args, **kwargs)


def _ouvrir_session(agent: Agent, appareil: Appareil | None) -> dict[str, Any]:
    valeur = secrets.token_urlsafe(32)
    expire = timezone.now() + DUREE_JETON
    JetonMobile.objects.create(agent=agent, appareil=appareil, empreinte=empreinte_hmac(valeur), expire_le=expire)
    journaliser("connexion_mobile", agent, apres={"appareil": appareil.libelle if appareil else ""}, acteur=agent.utilisateur)
    return {"etape": "connecte", "jeton": valeur, "expire_le": expire, "agent": {"prenom": agent.prenom, "nom": agent.nom}}


class ConnexionMobileSerializer(serializers.Serializer):
    identifiant = serializers.CharField(max_length=150)
    mot_de_passe = serializers.CharField(max_length=256, trim_whitespace=False)
    appareil = serializers.CharField(max_length=120, required=False, allow_blank=True, default="")
    appareil_id = serializers.UUIDField(required=False, allow_null=True, default=None)


def agent_du_compte(utilisateur: Utilisateur) -> Agent | None:
    """Fiche de l'agent du compte ; à la première connexion, rattachement par l'identifiant de l'annuaire (D-046)."""
    agent = Agent.objects.filter(utilisateur=utilisateur, actif=True).first()
    if agent is None:
        with transaction.atomic():
            agent = (
                Agent.objects.select_for_update()
                .filter(identifiant_ad__iexact=utilisateur.username, utilisateur__isnull=True, actif=True)
                .first()
            )
            if agent is not None:
                agent.utilisateur = utilisateur
                agent.save(update_fields=["utilisateur"])
                journaliser("rattacher_compte_agent", objet=agent, apres={"compte": utilisateur.username}, acteur=utilisateur)
    return agent


def _cle_echecs(identifiant: str) -> str:
    return f"mobile-echecs:{empreinte_hmac(identifiant.strip().lower())}"


def _refuser(identifiant: str, motif: str) -> ErreurValidation:
    """Refus neutre, compté par identifiant (limitation par compte, en plus de la limitation par adresse)."""
    cle = _cle_echecs(identifiant)
    try:
        cache.incr(cle)
    except ValueError:
        cache.set(cle, 1, timeout=900)
    journaliser(
        "connexion_mobile_echouee",
        objet_type="personnel.agent",
        apres={"identifiant_empreinte": empreinte_hmac(identifiant.lower())[:16], "motif": motif},
    )
    return ErreurValidation(REFUS_CONNEXION, code="connexion_refusee")


def _appareil_option_a(agent: Agent, identifiant: Any, libelle: str) -> Appareil | None:
    """Appareil identifié par l'identifiant tiré par l'application. Un nouvel appareil est actif d'emblée pour un agent
    qui n'en a jamais perdu ; après un retrait (perte, vol), il attend l'autorisation du planificateur (SEC-10)."""
    if identifiant is None:
        return None
    appareil = Appareil.objects.filter(agent=agent, identifiant=identifiant).first()
    if appareil is not None:
        return appareil if appareil.actif else None
    retire = agent.appareils.filter(revoque_le__isnull=False).exists()
    trop = agent.appareils.filter(actif=True).count() >= APPAREILS_ACTIFS_MAX
    appareil = Appareil.objects.create(
        agent=agent,
        identifiant=identifiant,
        libelle=(libelle or "Smartphone")[:120],
        actif=not (retire or trop),
        a_autoriser=retire or trop,
    )
    journaliser("enregistrer_appareil", appareil, apres={"a_autoriser": appareil.a_autoriser}, acteur=agent.utilisateur)
    return appareil if appareil.actif else None


class VueConnexionMobile(VueMobilePublique):
    """Compte de l'annuaire et rôle « gardien » ; second facteur exigé en option B ou si l'agent l'a activé. Tout refus
    antérieur au code TOTP reçoit la même réponse (pas d'oracle sur le mot de passe) ; en option B, le certificat
    d'appareil est vérifié avant l'annuaire et seul le compte de cet appareil peut s'y connecter."""

    throttle_scope = "connexion"

    @extend_schema(request=ConnexionMobileSerializer, responses={200: dict})
    def post(self, request: Request) -> Response:
        entree = ConnexionMobileSerializer(data=request.data)
        entree.is_valid(raise_exception=True)
        d = entree.validated_data
        identifiant = d["identifiant"].strip()
        if int(cache.get(_cle_echecs(identifiant)) or 0) >= ECHECS_MAX:
            raise _refuser(identifiant, "trop_d_echecs")
        appareil_b: Appareil | None = None
        if settings.MOBILE_OPTION == "B":
            try:
                appareil_b = _appareil_option_b(request)
            except AccesRefuse, ErreurValidation:
                raise _refuser(identifiant, "certificat") from None
            compte = appareil_b.agent.utilisateur
            if compte is None or compte.username.lower() != identifiant.lower():
                raise _refuser(identifiant, "compte_d_un_autre_appareil")
        utilisateur = authenticate(request._request, username=identifiant, password=d["mot_de_passe"])
        if not isinstance(utilisateur, Utilisateur) or not peut(utilisateur, "utiliser_mobile"):
            raise _refuser(identifiant, "identifiants")
        if totp.secondes_verrou(utilisateur):
            raise _refuser(identifiant, "verrou_totp")
        agent = agent_du_compte(utilisateur)
        if agent is None:
            raise _refuser(identifiant, "sans_fiche_agent")
        if appareil_b is not None:
            if appareil_b.agent_id != agent.pk:
                raise _refuser(identifiant, "compte_d_un_autre_appareil")
            appareil = appareil_b
        else:
            trouve = _appareil_option_a(agent, d["appareil_id"], d["appareil"])
            if trouve is None:
                raise _refuser(identifiant, "appareil_non_autorise")
            appareil = trouve
        if settings.MOBILE_OPTION == "B" or utilisateur.totp_actif:
            if not utilisateur.totp_actif:
                raise _refuser(identifiant, "totp_non_active")
            defi = secrets.token_urlsafe(24)
            cache.set(f"mobile-defi:{empreinte_hmac(defi)}", {"agent": agent.pk, "appareil": appareil.pk}, timeout=300)
            return Response({"etape": "totp", "defi": defi})
        cache.delete(_cle_echecs(identifiant))
        return Response(_ouvrir_session(agent, appareil))


class DefiMobileSerializer(serializers.Serializer):
    defi = serializers.CharField(max_length=64)
    code = serializers.CharField(max_length=10)


class VueTotpMobile(VueMobilePublique):
    throttle_scope = "connexion"

    @extend_schema(request=DefiMobileSerializer, responses={200: dict})
    def post(self, request: Request) -> Response:
        entree = DefiMobileSerializer(data=request.data)
        entree.is_valid(raise_exception=True)
        cle = f"mobile-defi:{empreinte_hmac(entree.validated_data['defi'])}"
        defi = cache.get(cle)
        if not defi:
            raise ErreurValidation("La connexion a expiré : saisissez à nouveau votre mot de passe.", code="defi_expire")
        agent = Agent.objects.select_related("utilisateur").get(pk=defi["agent"])
        appareil = Appareil.objects.get(pk=defi["appareil"])
        if not appareil.actif:
            raise ErreurValidation(REFUS_CONNEXION, code="connexion_refusee")
        if settings.MOBILE_OPTION == "B":
            _appareil_option_b(request, agent)
        utilisateur = agent.utilisateur
        assert utilisateur is not None
        if totp.secondes_verrou(utilisateur):
            raise ErreurMetier("Trop de tentatives : réessayez plus tard.", code="verrouille")
        if not totp.verifier_utilisateur(utilisateur, entree.validated_data["code"]):
            if totp.enregistrer_echec(utilisateur):
                cache.delete(cle)
            raise ErreurValidation("Code incorrect ou expiré.", code="code_invalide")
        totp.reinitialiser_echecs(utilisateur)
        cache.delete(cle)
        return Response(_ouvrir_session(agent, appareil))


class VueDeconnexionMobile(VueMobile):
    @extend_schema(request=None, responses={204: None})
    def post(self, request: Request) -> Response:
        JetonMobile.objects.filter(pk=request.auth.pk).update(revoque_le=timezone.now())  # type: ignore[union-attr]
        return Response(status=status.HTTP_204_NO_CONTENT)


class VueSanteMobile(VueMobilePublique):
    """Appel léger qui confirme le réseau avant l'envoi de la file (MOB-05)."""

    @extend_schema(responses={200: dict})
    def get(self, request: Request) -> Response:
        return Response({"ok": True, "heure": timezone.now()})


# --- Paquet descendant (MOB-01, MOB-02, MOB-07, MOB-08) ---------------------------------------------------


def paquet(agent: Agent) -> dict[str, Any]:
    maintenant = timezone.now()
    horizon = maintenant + timedelta(days=int(parametre("mobile.horizon_jours")))
    vacations = list(
        Vacation.objects.filter(
            agent=agent, statut__in=["planifiee", "a_revoir"], fin__gte=maintenant - timedelta(hours=12), debut__lte=horizon
        )
        .select_related("site")
        .order_by("debut")
    )
    seances = []
    vues: set[int] = set()
    for vacation in vacations:
        for o in (
            Occurrence.objects.filter(espace__batiment__site=vacation.site, debut__lt=vacation.fin, fin__gt=vacation.debut)
            .exclude(statut__in=["refusee", "demande", "en_instruction"])
            .select_related("espace__famille", "reservation__dossier__usager")
            .order_by("debut")
        ):
            if o.pk in vues:
                continue
            vues.add(o.pk)
            dossier = o.reservation.dossier
            referent = dossier.usager.rattachements.select_related("contact").order_by("-principal").first()
            seances.append(
                {
                    "id": o.pk,
                    "vacation": vacation.pk,
                    "espace": o.espace.nom,
                    "famille": o.espace.famille.code if o.espace.famille_id else "",
                    "debut": o.debut,
                    "fin": o.fin,
                    "statut": o.statut,
                    "usager": dossier.usager.nom,
                    "activite": dossier.activite,
                    "effectif": dossier.effectif,
                    "referent": {"nom": str(referent.contact), "telephone": referent.contact.telephone} if referent else None,
                    "etat_des_lieux": dossier.type_reservation.exige_caution,
                    "materiel": [],
                }
            )
    sites = {v.site_id: v.site for v in vacations}
    return {
        "genere_le": maintenant,
        "agent": {"prenom": agent.prenom, "nom": agent.nom},
        "parametres": {"alerte_heures": parametre("mobile.alerte_heures"), "purge_jours": parametre("mobile.purge_jours")},
        "sites": [{"id": s.pk, "nom": s.nom, "adresse": s.adresse} for s in sites.values()],
        "vacations": [
            {
                "id": v.pk,
                "site": v.site_id,
                "site_nom": v.site.nom,
                "debut": v.debut,
                "fin": v.fin,
                "type": v.get_type_display(),
                "statut": v.statut,
                "arrivee_reelle": v.arrivee_reelle,
                "depart_reel": v.depart_reel,
                "signalement": v.signalement,
            }
            for v in vacations
        ],
        "seances": seances,
        "grilles": {"commune": GRILLE_COMMUNE, **GRILLES},
    }


class VuePaquet(VueMobile):
    @extend_schema(responses={200: dict})
    def get(self, request: Request) -> Response:
        agent = self.agent(request)
        jeton = request.auth
        if isinstance(jeton, JetonMobile) and jeton.appareil_id:
            Appareil.objects.filter(pk=jeton.appareil_id).update(derniere_synchronisation=timezone.now())
        contenu = paquet(agent)
        journaliser(
            "telecharger_paquet_mobile",
            agent,
            apres={"vacations": len(contenu["vacations"]), "seances": len(contenu["seances"])},
            acteur=agent.utilisateur,
        )
        return Response(contenu)


# --- Saisies montantes (MOB-02 à MOB-06, PER-09) ----------------------------------------------------------


class Conflit(Exception):
    """Saisie conservée mais signalée : la réservation a changé pendant que l'agent était hors ligne (MOB-06)."""


def _instant(valeur: Any, defaut: datetime) -> datetime:
    instant = parse_datetime(str(valeur)) if valeur else None
    return instant if instant is not None and instant.tzinfo is not None else defaut


def _entier(valeur: Any) -> int:
    try:
        return int(valeur)
    except TypeError, ValueError:
        return 0


def _photos(agent: Agent, identifiants: Any) -> list[Any]:
    if not isinstance(identifiants, list):
        return []
    valides = [i for i in identifiants[:10] if isinstance(i, str)]
    return [p.fichier for p in PhotoMobile.objects.filter(agent=agent, uuid__in=valides).select_related("fichier")]


def _occurrence_du_site(agent: Agent, identifiant: Any) -> Occurrence:
    occurrence = (
        Occurrence.objects.select_related("espace__batiment", "reservation__dossier__usager")
        .filter(pk=_entier(identifiant))
        .first()
    )
    if occurrence is None or not agent.sites.filter(pk=occurrence.espace.batiment.site_id).exists():
        raise ErreurValidation("Séance inconnue pour cet agent.", code="seance_inconnue")
    return occurrence


def _occurrence_en_poste(agent: Agent, identifiant: Any) -> Occurrence:
    """Séance que l'agent gardiennait : une de ses vacations (planifiée ou à revoir) la chevauche (RG-11, MOB-03)."""
    occurrence = _occurrence_du_site(agent, identifiant)
    en_poste = Vacation.objects.filter(
        agent=agent,
        site_id=occurrence.espace.batiment.site_id,
        statut__in=["planifiee", "a_revoir"],
        debut__lt=occurrence.fin + RETARD_POINTAGE,
        fin__gt=occurrence.debut - AVANCE_POINTAGE,
    ).exists()
    if not en_poste:
        raise ErreurValidation("Aucune de vos vacations ne couvre cette séance.", code="hors_vacation")
    return occurrence


def _instant_borne(donnees: dict[str, Any], horodatage: datetime, recu_le: datetime) -> datetime:
    instant = _instant(donnees.get("instant"), horodatage)
    if instant > recu_le + DERIVE_HORLOGE:
        raise ErreurValidation("Heure de saisie postérieure à sa réception : vérifiez l'heure du téléphone.", code="heure_future")
    return instant


def _traiter_pointage(agent: Agent, donnees: dict[str, Any], horodatage: datetime, recu_le: datetime) -> str:
    """MOB-02 : heure bornée à la vacation ; le premier pointage de chaque moment fait foi, une saisie différente
    est conservée en conflit (les heures réalisées alimentent la paie). Une vacation annulée ou à revoir garde
    le pointage, signalé au gestionnaire (MOB-06)."""
    vacation = Vacation.objects.select_for_update().filter(pk=_entier(donnees.get("vacation")), agent=agent).first()
    if vacation is None:
        raise ErreurValidation("Vacation inconnue pour cet agent.", code="vacation_inconnue")
    moment = donnees.get("moment")
    if moment not in ("arrivee", "depart"):
        raise ErreurValidation("Pointage : « arrivee » ou « depart » attendu.", code="moment_invalide")
    instant = _instant_borne(donnees, horodatage, recu_le)
    if not vacation.debut - AVANCE_POINTAGE <= instant <= vacation.fin + RETARD_POINTAGE:
        raise ErreurValidation(
            f"Pointage à {services._texte(instant)} hors des horaires de la vacation ({services._texte(vacation.debut)}).",
            code="pointage_hors_vacation",
        )
    champ = "arrivee_reelle" if moment == "arrivee" else "depart_reel"
    deja = getattr(vacation, champ)
    if deja is not None and abs((deja - instant).total_seconds()) > 60:
        raise Conflit(
            f"Second pointage de {'l’arrivée' if moment == 'arrivee' else 'départ'} ({services._texte(instant)}), le premier est conservé"
        )
    if moment == "depart" and vacation.arrivee_reelle and instant <= vacation.arrivee_reelle:
        raise ErreurValidation("Départ antérieur à l'arrivée pointée.", code="pointage_incoherent")
    if deja is None:
        setattr(vacation, champ, instant)
        vacation.save(update_fields=[champ])
    seances = Occurrence.objects.filter(
        espace__batiment__site_id=vacation.site_id, debut__lt=vacation.fin, fin__gt=vacation.debut
    ).exclude(statut__in=["refusee", "demande", "en_instruction"])
    if vacation.statut == "annulee":
        raise Conflit(f"Pointage enregistré sur une vacation annulée ({services._texte(vacation.debut)})")
    if vacation.statut == "a_revoir" or (seances.exists() and not seances.exclude(statut="annulee").exists()):
        raise Conflit(
            f"Pointage enregistré alors que les séances de la vacation ont changé ({vacation.signalement or 'annulées'})"
        )
    return "Pointage enregistré."


def _traiter_etat_des_lieux(agent: Agent, donnees: dict[str, Any], horodatage: datetime, recu_le: datetime) -> str:
    from apps.finances import cautions
    from apps.finances.models import EtatDesLieux

    occurrence = _occurrence_en_poste(agent, donnees.get("occurrence"))
    moment = donnees.get("moment")
    if moment not in ("entree", "sortie"):
        raise ErreurValidation("État des lieux : « entree » ou « sortie » attendu.", code="moment_invalide")
    constat = donnees.get("constat")
    if constat not in ("conforme", "degats"):
        raise ErreurValidation("Constat : « conforme » ou « degats » attendu.", code="constat_invalide")
    observations = str(donnees.get("observations", ""))[:4000]
    signataire = str(donnees.get("signataire", ""))[:150]
    if signataire:
        observations = f"Signé par {signataire}. {observations}".strip()
    controles = donnees.get("controles")
    if isinstance(controles, dict):
        defauts = [str(k)[:80] for k, v in controles.items() if v is False][:30]
        if defauts:
            # Un point de la grille non conforme vaut dégâts constatés, quel que soit le constat envoyé (RG-11).
            constat = "degats"
            observations = f"{observations} Points à reprendre : {', '.join(defauts)}.".strip()
    instant = _instant_borne(donnees, horodatage, recu_le)
    photos = _photos(agent, donnees.get("photos"))
    signature = _photos(agent, [donnees.get("signature")]) if donnees.get("signature") else []
    if occurrence.statut in {"annulee", "refusee"}:
        # MOB-06 : la saisie est conservée dans le journal des saisies et signalée ; la séance n'est pas modifiée.
        raise Conflit(f"État des lieux d'une séance annulée ({occurrence.espace.nom}, {services._texte(occurrence.debut)})")
    if moment == "entree":
        if not occurrence.debut - AVANCE_POINTAGE <= instant <= occurrence.fin:
            raise ErreurValidation("L'état des lieux d'entrée se fait au début de la séance.", code="moment_incoherent")
        if EtatDesLieux.objects.filter(occurrence=occurrence, moment="entree").exists():
            raise Conflit("État des lieux d'entrée déjà établi pour cette séance")
        etat = EtatDesLieux.objects.create(
            occurrence=occurrence,
            moment="entree",
            constat=constat,
            observations=observations,
            agent=agent.utilisateur,
            source="mobile",
            constate_le=instant,
            signature_usager=signature[0] if signature else None,
        )
        etat.photos.set(photos)
        return "État des lieux d'entrée enregistré."
    try:
        etat = cautions.constater_sortie(
            occurrence,
            acteur=agent.utilisateur or "système",
            constat=constat,
            observations=observations,
            photos=photos,
            source="mobile",
            constate_le=instant,
        )
    except ErreurMetier as erreur:
        if erreur.code == "etat_des_lieux_existant":
            raise Conflit("État des lieux de sortie déjà établi pour cette séance") from erreur
        raise
    if signature:
        EtatDesLieux.objects.filter(pk=etat.pk).update(signature_usager=signature[0])
    return "État des lieux de sortie enregistré."


def _traiter_incident(agent: Agent, donnees: dict[str, Any], horodatage: datetime, recu_le: datetime) -> str:
    from apps.referentiel.models import Site

    occurrence = _occurrence_du_site(agent, donnees["occurrence"]) if donnees.get("occurrence") else None
    site = occurrence.espace.batiment.site if occurrence else agent.sites.filter(pk=_entier(donnees.get("site"))).first()
    if site is None:
        raise ErreurValidation("Indiquez la séance ou le site de l'incident.", code="site_inconnu")
    assert isinstance(site, Site)
    from .models import Incident

    nature = str(donnees.get("nature")) if donnees.get("nature") in dict(Incident.NATURES) else "autre"
    gravite = str(donnees.get("gravite")) if donnees.get("gravite") in dict(Incident.GRAVITES) else "mineur"
    # Un incident est toujours enregistré, même sur une séance annulée entre-temps (le service est prévenu).
    services.signaler_incident(
        acteur=agent.utilisateur or "système",
        source="mobile",
        site=site,
        nature=nature,
        gravite=gravite,
        description=str(donnees.get("description", ""))[:4000],
        constate_le=_instant_borne(donnees, horodatage, recu_le),
        occurrence=occurrence,
        photos=_photos(agent, donnees.get("photos")),
        agent=agent,
    )
    if occurrence and occurrence.statut in {"annulee", "refusee"}:
        return "Incident transmis au service (la séance avait été annulée)."
    return "Incident transmis au service."


TRAITEMENTS = {"pointage": _traiter_pointage, "etat_des_lieux": _traiter_etat_des_lieux, "incident": _traiter_incident}


def _enregistrer_saisie(agent: Agent, identifiant: uuid_lib.UUID, **champs: Any) -> SaisieMobile | None:
    """Création idempotente : deux envois simultanés du même identifiant donnent une seule saisie."""
    try:
        with transaction.atomic():
            return SaisieMobile.objects.create(uuid=identifiant, agent=agent, **champs)
    except IntegrityError:
        return None


def recevoir_saisies(agent: Agent, saisies: list[dict[str, Any]], appareil: str = "") -> list[dict[str, str]]:
    """Idempotent (MOB-05) : une saisie déjà reçue renvoie son accusé ; chaque saisie est traitée à part et une saisie
    malformée est rejetée seule, sans bloquer la file."""
    accuses = []
    recu_le = timezone.now()
    for saisie in saisies:
        try:
            identifiant = uuid_lib.UUID(str(saisie.get("uuid")))
        except ValueError:
            accuses.append(
                {"uuid": str(saisie.get("uuid", ""))[:40], "statut": "rejetee", "message": "Identifiant de saisie invalide."}
            )
            continue
        deja = SaisieMobile.objects.filter(uuid=identifiant).first()
        if deja is not None:
            if deja.agent_id != agent.pk:
                accuses.append({"uuid": str(identifiant), "statut": "rejetee", "message": "Identifiant de saisie déjà utilisé."})
            else:
                accuses.append({"uuid": str(identifiant), "statut": deja.statut, "message": deja.message or "Déjà reçue."})
            continue
        type_saisie = str(saisie.get("type", ""))[:15]
        donnees = saisie.get("donnees") if isinstance(saisie.get("donnees"), dict) else {}
        horodatage = _instant(saisie.get("horodatage"), recu_le)
        statut, message = "acceptee", ""
        enregistree: SaisieMobile | None = None
        try:
            with transaction.atomic():
                traitement = TRAITEMENTS.get(type_saisie)
                if traitement is None:
                    raise ErreurValidation("Type de saisie inconnu.", code="type_inconnu")
                with transaction.atomic():
                    try:
                        message = traitement(agent, donnees, horodatage, recu_le)  # type: ignore[arg-type]
                    except Conflit as conflit:
                        statut, message = "conflit", f"{conflit} : conservé et signalé au gestionnaire."
                enregistree = SaisieMobile.objects.create(
                    uuid=identifiant,
                    agent=agent,
                    appareil=appareil[:120],
                    type=type_saisie,
                    horodatage_appareil=horodatage,
                    donnees=donnees,
                    statut=statut,
                    message=message[:300],
                )
        except IntegrityError:
            enregistree = SaisieMobile.objects.filter(uuid=identifiant, agent=agent).first()
            statut, message = (enregistree.statut, enregistree.message) if enregistree else ("rejetee", "Saisie déjà reçue.")
            accuses.append({"uuid": str(identifiant), "statut": statut, "message": message or "Déjà reçue."})
            continue
        except (ErreurMetier, KeyError, TypeError, ValueError) as erreur:
            statut = "rejetee"
            message = erreur.message if isinstance(erreur, ErreurMetier) else "Saisie illisible."
            enregistree = _enregistrer_saisie(
                agent,
                identifiant,
                appareil=appareil[:120],
                type=type_saisie if type_saisie in dict(SaisieMobile.TYPES) else "incident",
                horodatage_appareil=horodatage,
                donnees=donnees,
                statut=statut,
                message=message[:300],
            )
        if statut != "acceptee" and enregistree is not None:
            notifier(
                "saisie_mobile_conflit",
                {
                    "agent": str(agent),
                    "type": type_saisie,
                    "message": message,
                    "horodatage": services._texte(horodatage),
                    "lien": f"{settings.BACKOFFICE_URL}/personnel/saisies",
                },
                courriels=[str(parametre("portail.service_courriel"))],
            )
        accuses.append({"uuid": str(identifiant), "statut": statut, "message": message})
    return accuses


class SaisiesSerializer(serializers.Serializer):
    saisies = serializers.ListField(child=serializers.DictField(), max_length=200)


class VueSaisies(VueMobile):
    parser_classes = [JSONParser]
    throttle_scope = "televersement"

    @extend_schema(request=SaisiesSerializer, responses={200: dict})
    def post(self, request: Request) -> Response:
        entree = SaisiesSerializer(data=request.data)
        entree.is_valid(raise_exception=True)
        jeton = request.auth
        appareil = jeton.appareil.libelle if isinstance(jeton, JetonMobile) and jeton.appareil else ""
        return Response({"accuses": recevoir_saisies(self.agent(request), entree.validated_data["saisies"], appareil)})


class PhotoSerializer(serializers.Serializer):
    uuid = serializers.UUIDField()
    fichier = serializers.FileField()


class VuePhotos(VueMobile):
    """Photos compressées sur l'appareil, envoyées avant la saisie qui les cite ; idempotent."""

    parser_classes = [MultiPartParser]
    throttle_scope = "televersement"

    @extend_schema(request={"multipart/form-data": PhotoSerializer}, responses={201: dict})
    def post(self, request: Request) -> Response:
        entree = PhotoSerializer(data=request.data)
        entree.is_valid(raise_exception=True)
        agent = self.agent(request)
        identifiant = entree.validated_data["uuid"]
        existante = PhotoMobile.objects.filter(uuid=identifiant).first()
        if existante is not None:
            if existante.agent_id != agent.pk:
                raise ErreurValidation("Identifiant de photo déjà utilisé.", code="photo_existante")
            return Response({"uuid": str(identifiant), "deja_recue": True})
        televerse = entree.validated_data["fichier"]
        if televerse.size is None or televerse.size > fichiers.TAILLE_MAX:
            raise ErreurValidation("La photo est trop volumineuse.", code="fichier_trop_gros")
        # Option A : les en-têtes de contrôle viendraient du téléphone lui-même ; seule la façade DMZ (option B, canal
        # « portail ») les pose, et `fichiers.enregistrer` ne les croit que sur ce canal.
        par_facade = getattr(settings, "CANAL", "gestion") == "portail"
        fichier = fichiers.enregistrer(
            televerse.name or "photo.jpg",
            fichiers.sans_metadonnees(televerse.read()),
            types_autorises=("image/jpeg", "image/png"),
            depose_par=str(agent),
            controle_facade=request.headers.get("X-Fichier-Controle", "") if par_facade else "",
            empreinte_facade=request.headers.get("X-Empreinte-Sha256", "") if par_facade else "",
        )
        PhotoMobile.objects.create(uuid=identifiant, agent=agent, fichier=fichier)
        return Response({"uuid": str(identifiant), "deja_recue": False}, status=status.HTTP_201_CREATED)
