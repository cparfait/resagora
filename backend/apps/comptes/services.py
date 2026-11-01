"""Comptes usagers du portail (POR-01, SEC-04).

- Mot de passe : Argon2id, politique conforme aux recommandations de l'ANSSI (12 caractères et trois
  familles de caractères, ou phrase de passe de 16 caractères ; mots de passe courants refusés).
- Connexion : message identique que le compte existe ou non (pas d'énumération), temps de calcul
  identique (hachage factice), attente imposée après `portail.echecs_avant_verrou` échecs, doublée à
  chaque récidive dans la limite de `portail.verrou_max_minutes`. Les compteurs sont tenus par
  identifiant saisi (empreinte HMAC), y compris pour les identifiants inconnus.
- Double authentification TOTP proposée à chaque usager ; défi à usage unique de cinq minutes.
- Liens de confirmation, d'invitation et de réinitialisation à usage unique et de courte durée ; le
  lien n'est jamais conservé en clair (empreinte en base, corps du courriel masqué dans le journal).
"""

from __future__ import annotations

import logging
import re
import secrets
from dataclasses import dataclass
from datetime import timedelta
from difflib import SequenceMatcher
from types import SimpleNamespace
from typing import Any

import pyotp
from django.conf import settings
from django.contrib.auth import password_validation
from django.contrib.auth.hashers import check_password, is_password_usable, make_password
from django.core.cache import cache
from django.core.exceptions import ValidationError
from django.db import transaction
from django.utils import timezone

from apps.audit.services import instantane, journaliser
from apps.communication.services import notifier
from apps.habilitations.services import exiger
from apps.noyau.chiffrement import chiffrer, dechiffrer, empreinte_hmac
from apps.noyau.exceptions import ErreurMetier, ErreurValidation
from apps.noyau.parametres import parametre
from apps.usagers.agenda import revoquer_abonnements
from apps.usagers.models import Contact, Rattachement, Usager

from .models import CompteUsager, JetonPortail, JetonUnique

journal_securite = logging.getLogger("securite")

MESSAGE_ECHEC = "Identifiant ou mot de passe incorrect."
MESSAGE_ENVOI = (
    "Si cette adresse correspond à un compte, un courriel vient d'être envoyé. Pensez à vérifier vos courriers indésirables."
)
# Hachage d'un mot de passe aléatoire : la vérification d'un identifiant inconnu coûte le même temps.
HASH_FACTICE = make_password(secrets.token_urlsafe(24))
DUREE_DEFI_TOTP = timedelta(minutes=5)
DUREE_INVITATION = timedelta(days=7)


class ErreurConnexion(ErreurMetier):
    statut_http = 401


class ErreurVerrou(ErreurMetier):
    statut_http = 429


class CompteInactif(ErreurMetier):
    statut_http = 403


# --- Politique de mot de passe -------------------------------------------------------------------


class ValidateurFamilles:
    """Trois familles de caractères (minuscules, majuscules, chiffres, autres) sous 16 caractères."""

    def validate(self, password: str, user: Any = None) -> None:
        if len(password) >= 16:
            return
        familles = sum(
            [
                any(c.islower() for c in password),
                any(c.isupper() for c in password),
                any(c.isdecimal() for c in password),
                any(not c.isalnum() for c in password),
            ]
        )
        if familles < 3:
            raise ValidationError(
                "Utilisez au moins trois types de caractères parmi minuscules, majuscules, chiffres et caractères spéciaux, "
                "ou une phrase de passe d'au moins 16 caractères.",
                code="familles",
            )

    def get_help_text(self) -> str:
        return "Trois types de caractères, ou une phrase de passe de 16 caractères."


class ValidateurSimilarite:
    """Le mot de passe ne doit pas reprendre l'adresse, le prénom ou le nom du titulaire."""

    def validate(self, password: str, user: Any = None) -> None:
        if user is None:
            return
        mot = password.lower()
        valeurs: list[str] = []
        for attribut in ("identifiant", "prenom", "nom"):
            valeur = str(getattr(user, attribut, "") or "").lower()
            valeurs += [valeur, *re.split(r"\W+", valeur)]
        for valeur in {v for v in valeurs if len(v) >= 3}:
            if valeur in mot or SequenceMatcher(a=mot, b=valeur).ratio() >= 0.7:
                raise ValidationError("Mot de passe trop proche du nom ou de l'adresse.", code="password_too_similar")

    def get_help_text(self) -> str:
        return "Le mot de passe ne reprend ni votre nom ni votre adresse électronique."


VALIDATEURS = [
    password_validation.MinimumLengthValidator(min_length=12),
    password_validation.CommonPasswordValidator(),
    password_validation.NumericPasswordValidator(),
    ValidateurSimilarite(),
    ValidateurFamilles(),
]

MESSAGES_VALIDATEURS = {
    "password_too_short": "Le mot de passe doit contenir au moins 12 caractères.",
    "password_too_common": "Ce mot de passe est trop courant.",
    "password_entirely_numeric": "Le mot de passe ne peut pas être composé uniquement de chiffres.",
    "password_too_similar": "Le mot de passe ressemble trop à votre nom ou à votre adresse électronique.",
}


def verifier_politique(mot_de_passe: str, *, identifiant: str = "", prenom: str = "", nom: str = "") -> None:
    if len(mot_de_passe) > 256:
        raise ErreurValidation("Le mot de passe est trop long (256 caractères au plus).", code="mot_de_passe_refuse")
    personne: Any = SimpleNamespace(identifiant=identifiant, prenom=prenom, nom=nom)
    validateurs: Any = VALIDATEURS
    try:
        password_validation.validate_password(mot_de_passe, user=personne, password_validators=validateurs)
    except ValidationError as erreur:
        messages = [MESSAGES_VALIDATEURS.get(e.code or "", e.messages[0]) for e in erreur.error_list]
        raise ErreurValidation(" ".join(messages), code="mot_de_passe_refuse") from erreur


def normaliser_identifiant(identifiant: str) -> str:
    return (identifiant or "").strip().lower()[:254]


# --- Jetons ---------------------------------------------------------------------------------------


def _nouveau_jeton() -> str:
    return secrets.token_urlsafe(32)


def emettre_jeton_unique(compte: CompteUsager, nature: str, duree: timedelta, *, donnee: str = "") -> str:
    """Invalide les jetons précédents de même nature et en émet un nouveau (valeur renvoyée une seule fois)."""
    JetonUnique.objects.filter(compte=compte, nature=nature, utilise_le__isnull=True).update(utilise_le=timezone.now())
    valeur = _nouveau_jeton()
    JetonUnique.objects.create(
        compte=compte, nature=nature, empreinte=empreinte_hmac(valeur), expire_le=timezone.now() + duree, donnee=donnee
    )
    return valeur


def consommer_jeton(valeur: str, nature: str) -> JetonUnique:
    jeton = (
        JetonUnique.objects.select_for_update()
        .select_related("compte__contact")
        .filter(empreinte=empreinte_hmac(valeur or ""), nature=nature)
        .first()
    )
    if jeton is None or jeton.utilise_le is not None or jeton.expire_le <= timezone.now():
        raise ErreurValidation("Ce lien n'est plus valable. Faites une nouvelle demande.", code="lien_invalide")
    jeton.utilise_le = timezone.now()
    jeton.save(update_fields=["utilise_le"])
    return jeton


def consommer_jeton_unique(valeur: str, nature: str) -> CompteUsager:
    jeton = (
        JetonUnique.objects.select_for_update()
        .select_related("compte__contact")
        .filter(empreinte=empreinte_hmac(valeur or ""), nature=nature)
        .first()
    )
    if jeton is None or jeton.utilise_le is not None or jeton.expire_le <= timezone.now():
        raise ErreurValidation("Ce lien n'est plus valable. Faites une nouvelle demande.", code="lien_invalide")
    jeton.utilise_le = timezone.now()
    jeton.save(update_fields=["utilise_le"])
    return jeton.compte


def ouvrir_session(compte: CompteUsager) -> str:
    valeur = _nouveau_jeton()
    JetonPortail.objects.create(
        compte=compte,
        empreinte=empreinte_hmac(valeur),
        expire_le=timezone.now() + timedelta(hours=int(parametre("portail.jeton_heures"))),
    )
    maintenant = timezone.now()
    CompteUsager.objects.filter(pk=compte.pk).update(derniere_connexion=maintenant)
    Usager.objects.filter(rattachements__contact=compte.contact).update(derniere_activite=maintenant)
    return valeur


def compte_du_jeton(valeur: str) -> tuple[CompteUsager, JetonPortail] | None:
    jeton = (
        JetonPortail.objects.select_related("compte__contact")
        .filter(empreinte=empreinte_hmac(valeur), revoque_le__isnull=True, expire_le__gt=timezone.now())
        .first()
    )
    if jeton is None or jeton.compte.statut != "actif":
        return None
    maintenant = timezone.now()
    if jeton.derniere_utilisation is None or maintenant - jeton.derniere_utilisation > timedelta(minutes=5):
        JetonPortail.objects.filter(pk=jeton.pk).update(derniere_utilisation=maintenant)
    return jeton.compte, jeton


def fermer_sessions(compte: CompteUsager, sauf: JetonPortail | None = None) -> int:
    qs = JetonPortail.objects.filter(compte=compte, revoque_le__isnull=True)
    if sauf is not None:
        qs = qs.exclude(pk=sauf.pk)
    return qs.update(revoque_le=timezone.now())


def revoquer(jeton: JetonPortail) -> None:
    JetonPortail.objects.filter(pk=jeton.pk, revoque_le__isnull=True).update(revoque_le=timezone.now())


# --- Verrouillage progressif ----------------------------------------------------------------------


def _cle(identifiant: str) -> str:
    return empreinte_hmac("connexion-portail:" + normaliser_identifiant(identifiant))[:40]


def minutes_attente(identifiant: str) -> int:
    fin = cache.get(f"portail-verrou:{_cle(identifiant)}")
    if not fin:
        return 0
    restant = fin - timezone.now().timestamp()
    return max(0, int(restant // 60) + (1 if restant % 60 else 0))


def _enregistrer_echec(identifiant: str, compte: CompteUsager | None) -> None:
    cle = _cle(identifiant)
    cache.add(f"portail-echecs:{cle}", 0, timeout=24 * 3600)
    echecs = cache.incr(f"portail-echecs:{cle}")
    journal_securite.warning("Échec de connexion au portail (identifiant %s…)", cle[:12])
    if echecs < int(parametre("portail.echecs_avant_verrou")):
        return
    recidive = int(cache.get(f"portail-recidive:{cle}", 0)) + 1
    cache.set(f"portail-recidive:{cle}", recidive, timeout=24 * 3600)
    minutes = min(int(parametre("portail.verrou_minutes")) * 2 ** (recidive - 1), int(parametre("portail.verrou_max_minutes")))
    fin = timezone.now() + timedelta(minutes=minutes)
    cache.set(f"portail-verrou:{cle}", fin.timestamp(), timeout=minutes * 60)
    cache.delete(f"portail-echecs:{cle}")
    if compte is not None:
        CompteUsager.objects.filter(pk=compte.pk).update(verrouille_jusqu_au=fin, recidives=recidive, echecs_connexion=0)
        journaliser("verrouiller_compte_portail", compte, apres={"minutes": minutes}, acteur="portail")


def _reussite(identifiant: str, compte: CompteUsager) -> None:
    cle = _cle(identifiant)
    cache.delete_many([f"portail-echecs:{cle}", f"portail-recidive:{cle}"])
    CompteUsager.objects.filter(pk=compte.pk).update(echecs_connexion=0, recidives=0, verrouille_jusqu_au=None)


def _refus_verrou(identifiant: str) -> None:
    minutes = minutes_attente(identifiant)
    if minutes:
        raise ErreurVerrou(
            f"Trop de tentatives. Réessayez dans {minutes} minute{'s' if minutes > 1 else ''}.",
            code="trop_de_tentatives",
            details={"minutes": minutes},
        )


# --- Inscription, confirmation, validation ------------------------------------------------------


@dataclass
class Resultat:
    message: str
    donnees: dict[str, Any]


def _lien(chemin: str, jeton: str) -> str:
    """Le jeton voyage dans le fragment de l'adresse : il n'est jamais transmis aux serveurs (journaux d'accès)."""
    return f"{settings.PORTAIL_URL.rstrip('/')}/{chemin}#jeton={jeton}"


@transaction.atomic
def inscrire(
    *,
    contact: dict[str, str],
    usager: dict[str, str],
    mot_de_passe: str,
    consentement: bool,
) -> Resultat:
    """POR-01 : crée le contact, la structure (en attente) et le compte, puis envoie le lien de confirmation.

    Si l'adresse a déjà un compte, la réponse est identique et le titulaire est prévenu par courriel.
    """
    if not consentement:
        raise ErreurValidation(
            "Vous devez accepter les conditions d'utilisation du portail et la politique de protection des données.",
            code="consentement",
        )
    identifiant = normaliser_identifiant(contact["courriel"])
    verifier_politique(mot_de_passe, identifiant=identifiant, prenom=contact.get("prenom", ""), nom=contact.get("nom", ""))
    existant = CompteUsager.objects.filter(identifiant=identifiant).select_related("contact").first()
    if existant is not None:
        make_password(mot_de_passe)  # même coût que la création d'un compte : pas d'énumération par le temps de réponse
        notifier(
            "compte_deja_existant",
            {"lien": f"{settings.PORTAIL_URL.rstrip('/')}/mot-de-passe-oublie"},
            contacts=[existant.contact],
        )
        return Resultat(MESSAGE_ENVOI, {})
    personne = Contact.objects.create(
        civilite=contact.get("civilite", ""),
        prenom=contact["prenom"],
        nom=contact["nom"],
        courriel=identifiant,
        telephone=contact.get("telephone", ""),
    )
    type_usager = usager["type"]
    structure = Usager.objects.create(
        type=type_usager,
        nom=usager.get("nom") or f"{personne.prenom} {personne.nom}",
        sigle=usager.get("sigle", ""),
        siret=usager.get("siret", ""),
        rna=usager.get("rna", ""),
        adresse=usager.get("adresse", ""),
        code_postal=usager.get("code_postal", ""),
        commune=usager.get("commune", ""),
        telephone=usager.get("telephone", "") or personne.telephone,
        courriel=usager.get("courriel", "") or identifiant,
        statut="en_attente",
    )
    Rattachement.objects.create(
        usager=structure, contact=personne, role=usager.get("role_contact") or "responsable", principal=True, peut_signer=True
    )
    compte = CompteUsager.objects.create(contact=personne, identifiant=identifiant, mot_de_passe=make_password(mot_de_passe))
    journaliser("inscrire_compte_portail", compte, apres={"usager": structure.pk, "type": type_usager}, acteur=personne)
    envoyer_confirmation(compte)
    return Resultat(MESSAGE_ENVOI, {})


def envoyer_confirmation(compte: CompteUsager) -> None:
    jeton = emettre_jeton_unique(compte, "confirmation", timedelta(hours=int(parametre("portail.confirmation_heures"))))
    notifier("compte_confirmation", {}, contacts=[compte.contact], secrets={"lien": _lien("confirmation", jeton)})


@transaction.atomic
def confirmer_courriel(jeton: str) -> Resultat:
    compte = consommer_jeton_unique(jeton, "confirmation")
    if compte.statut == "a_confirmer":
        compte.statut = "a_valider"
        compte.courriel_confirme_le = timezone.now()
        compte.save(update_fields=["statut", "courriel_confirme_le"])
        journaliser("confirmer_courriel_portail", compte, acteur=compte.contact)
        usagers = list(Usager.objects.filter(rattachements__contact=compte.contact, statut="en_attente"))
        notifier(
            "compte_a_valider",
            {
                "compte": compte,
                "usagers": ", ".join(u.nom for u in usagers),
                "lien": f"{settings.BACKOFFICE_URL}/usagers/comptes",
            },
            courriels=[str(parametre("portail.service_courriel"))],
            objet=compte,
        )
    return Resultat(
        "Votre adresse est confirmée. La Ville va vérifier votre demande de compte ; vous serez prévenu par courriel.", {}
    )


@transaction.atomic
def valider_compte(compte: CompteUsager, *, acteur: Any, usager_existant: Usager | None = None) -> CompteUsager:
    """La Ville valide le compte ; elle peut rattacher le contact à un usager déjà connu (doublon évité)."""
    exiger(acteur, "valider_compte_usager")
    compte = CompteUsager.objects.select_for_update().get(pk=compte.pk)
    if compte.statut not in {"a_valider", "a_confirmer"}:
        raise ErreurMetier("Ce compte n'est pas en attente de validation.", code="statut_compte")
    avant = instantane(compte)
    en_attente = list(Usager.objects.filter(rattachements__contact=compte.contact, statut="en_attente"))
    if usager_existant is not None:
        for doublon in en_attente:
            if not doublon.dossiers.exists():
                doublon.delete()
        Rattachement.objects.get_or_create(
            usager=usager_existant, contact=compte.contact, defaults={"role": "referent", "peut_signer": False}
        )
    else:
        Usager.objects.filter(pk__in=[u.pk for u in en_attente]).update(statut="valide")
    compte.statut = "actif"
    compte.valide_par = acteur
    compte.valide_le = timezone.now()
    compte.courriel_confirme_le = compte.courriel_confirme_le or timezone.now()
    compte.save()
    journaliser("valider_compte_portail", compte, avant=avant, apres=instantane(compte), acteur=acteur)
    notifier("compte_valide", {"lien": settings.PORTAIL_URL}, contacts=[compte.contact], objet=compte)
    return compte


@transaction.atomic
def refuser_compte(compte: CompteUsager, *, acteur: Any, motif: str) -> CompteUsager:
    exiger(acteur, "valider_compte_usager")
    if not motif.strip():
        raise ErreurValidation("Indiquez le motif du refus.", code="motif_obligatoire")
    compte = CompteUsager.objects.select_for_update().get(pk=compte.pk)
    if compte.statut not in {"a_valider", "a_confirmer"}:
        raise ErreurMetier("Ce compte n'est pas en attente de validation.", code="statut_compte")
    compte.statut = "ferme"
    compte.motif_suspension = motif[:250]
    compte.save(update_fields=["statut", "motif_suspension"])
    revoquer_abonnements(contact=compte.contact, acteur=acteur, motif="compte refusé")
    for usager in Usager.objects.filter(rattachements__contact=compte.contact, statut="en_attente"):
        if not usager.dossiers.exists():
            usager.delete()
    journaliser("refuser_compte_portail", compte, apres={"motif": motif}, acteur=acteur)
    notifier("compte_refuse", {"motif": motif}, contacts=[compte.contact], objet=compte)
    fermer_sessions(compte)
    return compte


@transaction.atomic
def suspendre_compte(compte: CompteUsager, *, acteur: Any, motif: str) -> CompteUsager:
    exiger(acteur, "valider_compte_usager")
    if compte.statut != "actif":
        raise ErreurMetier("Seul un compte actif peut être suspendu.", code="statut_compte")
    compte.statut = "suspendu"
    compte.motif_suspension = motif[:250]
    compte.save(update_fields=["statut", "motif_suspension"])
    fermer_sessions(compte)
    revoquer_abonnements(contact=compte.contact, acteur=acteur, motif="compte suspendu")
    journaliser("suspendre_compte_portail", compte, apres={"motif": motif}, acteur=acteur)
    return compte


@transaction.atomic
def reactiver_compte(compte: CompteUsager, *, acteur: Any) -> CompteUsager:
    exiger(acteur, "valider_compte_usager")
    if compte.statut != "suspendu":
        raise ErreurMetier("Seul un compte suspendu peut être réactivé.", code="statut_compte")
    compte.statut = "actif"
    compte.motif_suspension = ""
    compte.save(update_fields=["statut", "motif_suspension"])
    journaliser("reactiver_compte_portail", compte, acteur=acteur)
    return compte


@transaction.atomic
def inviter_contact(contact: Contact, *, invite_par: Any, structure: Any = None) -> CompteUsager | None:
    """Un contact ajouté par un usager (ou par un agent) reçoit un lien pour choisir son mot de passe.

    Sans énumération (SEC-04) : si l'adresse a déjà un compte, la réponse ne change pas et seul le titulaire
    est prévenu. Un compte déjà ouvert n'est jamais réinvité : son titulaire passe par « mot de passe oublié »
    (une réinvitation remplacerait son mot de passe).
    """
    identifiant = normaliser_identifiant(contact.courriel)
    existant = CompteUsager.objects.filter(identifiant=identifiant).exclude(contact=contact).select_related("contact").first()
    if existant is not None:
        notifier(
            "contact_deja_inscrit",
            {"invite_par": str(invite_par), "structure": str(structure or "")},
            contacts=[existant.contact],
        )
        journaliser("inviter_contact_portail", contact, apres={"compte_existant": True}, acteur=invite_par)
        return None
    compte = CompteUsager.objects.filter(contact=contact).first()
    if compte is not None and (
        compte.statut in {"actif", "suspendu", "a_valider", "ferme"} or is_password_usable(compte.mot_de_passe)
    ):
        raise ErreurMetier(
            "Ce contact a déjà un compte sur le portail : il peut utiliser « Mot de passe oublié ».", code="compte_existant"
        )
    if compte is None:
        compte = CompteUsager.objects.create(
            contact=contact, identifiant=identifiant, mot_de_passe=make_password(None), statut="a_confirmer"
        )
    jeton = emettre_jeton_unique(compte, "invitation", DUREE_INVITATION)
    notifier(
        "contact_invitation", {"invite_par": str(invite_par)}, contacts=[contact], secrets={"lien": _lien("invitation", jeton)}
    )
    journaliser("inviter_contact_portail", compte, acteur=invite_par)
    return compte


@transaction.atomic
def accepter_invitation(jeton: str, mot_de_passe: str) -> Resultat:
    compte = consommer_jeton_unique(jeton, "invitation")
    verifier_politique(mot_de_passe, identifiant=compte.identifiant, prenom=compte.contact.prenom, nom=compte.contact.nom)
    compte.mot_de_passe = make_password(mot_de_passe)
    compte.mot_de_passe_modifie_le = timezone.now()
    compte.courriel_confirme_le = timezone.now()
    # Le contact a été ajouté par une structure déjà connue de la Ville : pas de nouvelle validation.
    valide = Usager.objects.filter(rattachements__contact=compte.contact, statut="valide").exists()
    compte.statut = "actif" if valide else "a_valider"
    compte.save()
    fermer_sessions(compte)
    journaliser("accepter_invitation_portail", compte, acteur=compte.contact)
    return Resultat("Votre compte est créé. Vous pouvez vous connecter.", {})


# --- Connexion ------------------------------------------------------------------------------------


def _reponse_session(compte: CompteUsager) -> dict[str, Any]:
    return {"jeton": ouvrir_session(compte), "contact": profil(compte)}


def profil(compte: CompteUsager) -> dict[str, Any]:
    c = compte.contact
    return {"id": c.pk, "prenom": c.prenom, "nom": c.nom, "totp": compte.totp_actif}


def connecter(identifiant: str, mot_de_passe: str) -> dict[str, Any]:
    identifiant = normaliser_identifiant(identifiant)
    _refus_verrou(identifiant)
    compte = CompteUsager.objects.select_related("contact").filter(identifiant=identifiant).first()
    if compte is None:
        check_password(mot_de_passe, HASH_FACTICE)
        _enregistrer_echec(identifiant, None)
        _refus_verrou(identifiant)
        raise ErreurConnexion(MESSAGE_ECHEC, code="identifiants_invalides")
    if not check_password(mot_de_passe, compte.mot_de_passe):
        _enregistrer_echec(identifiant, compte)
        _refus_verrou(identifiant)
        raise ErreurConnexion(MESSAGE_ECHEC, code="identifiants_invalides")
    # Mot de passe exact : on peut désormais indiquer l'état du compte sans risque d'énumération.
    if compte.statut == "a_confirmer":
        envoyer_confirmation(compte)
        raise CompteInactif(
            "Confirmez votre adresse électronique : un nouveau lien de confirmation vient de vous être envoyé.",
            code="compte_a_confirmer",
        )
    if compte.statut == "a_valider":
        raise CompteInactif(
            "Votre compte est en attente de validation par la Ville. Vous serez prévenu par courriel.", code="compte_a_valider"
        )
    if compte.statut != "actif":
        raise CompteInactif("Votre compte n'est pas actif. Contactez le service des équipements.", code="compte_inactif")
    if compte.totp_actif:
        # Les compteurs d'échecs ne repartent à zéro qu'après le code de double authentification (SEC-04).
        defi = emettre_jeton_unique(compte, "defi_totp", DUREE_DEFI_TOTP)
        return {"etape": "totp", "defi": defi}
    _reussite(identifiant, compte)
    journaliser("connexion_portail", compte, acteur=compte.contact)
    return _reponse_session(compte)


def valider_defi_totp(defi: str, code: str) -> dict[str, Any]:
    """Hors transaction globale : un échec compté doit rester compté même si la requête est refusée."""
    jeton = (
        JetonUnique.objects.select_related("compte__contact")
        .filter(empreinte=empreinte_hmac(defi or ""), nature="defi_totp", utilise_le__isnull=True, expire_le__gt=timezone.now())
        .first()
    )
    if jeton is None:
        raise ErreurConnexion("La connexion a expiré. Saisissez à nouveau votre mot de passe.", code="defi_expire")
    compte = jeton.compte
    _refus_verrou(compte.identifiant)
    graine = dechiffrer(compte.totp_secret_chiffre)
    if not _code_valide(compte, graine, code):
        _enregistrer_echec(compte.identifiant, compte)
        if minutes_attente(compte.identifiant):
            JetonUnique.objects.filter(pk=jeton.pk).update(utilise_le=timezone.now())
            _refus_verrou(compte.identifiant)
        raise ErreurConnexion("Code incorrect. Vérifiez l'heure de votre téléphone et réessayez.", code="code_invalide")
    with transaction.atomic():
        if not JetonUnique.objects.filter(pk=jeton.pk, utilise_le__isnull=True).update(utilise_le=timezone.now()):
            raise ErreurConnexion("La connexion a expiré. Saisissez à nouveau votre mot de passe.", code="defi_expire")
        _reussite(compte.identifiant, compte)
        journaliser("connexion_portail", compte, apres={"totp": True}, acteur=compte.contact)
        return _reponse_session(compte)


def _code_valide(compte: CompteUsager, graine: str, code: str) -> bool:
    code = (code or "").strip().replace(" ", "")
    if not (code.isdecimal() and len(code) == 6 and pyotp.TOTP(graine).verify(code, valid_window=1)):
        return False
    return bool(cache.add(f"portail-totp-utilise:{compte.pk}:{code}", True, timeout=120))


# --- Mot de passe ---------------------------------------------------------------------------------


@transaction.atomic
def demander_reinitialisation(identifiant: str) -> Resultat:
    compte = CompteUsager.objects.select_related("contact").filter(identifiant=normaliser_identifiant(identifiant)).first()
    check_password("", HASH_FACTICE)  # même coût pour une adresse connue ou inconnue
    if compte is not None and compte.statut in {"actif", "a_valider", "a_confirmer"}:
        jeton = emettre_jeton_unique(
            compte, "reinitialisation", timedelta(minutes=int(parametre("portail.reinitialisation_minutes")))
        )
        notifier(
            "mot_de_passe_reinitialisation",
            {"minutes": parametre("portail.reinitialisation_minutes")},
            contacts=[compte.contact],
            secrets={"lien": _lien("reinitialisation", jeton)},
        )
        journaliser("demander_reinitialisation_portail", compte, acteur=compte.contact)
    return Resultat(MESSAGE_ENVOI, {})


@transaction.atomic
def reinitialiser(jeton: str, mot_de_passe: str) -> Resultat:
    compte = consommer_jeton_unique(jeton, "reinitialisation")
    verifier_politique(mot_de_passe, identifiant=compte.identifiant, prenom=compte.contact.prenom, nom=compte.contact.nom)
    compte.mot_de_passe = make_password(mot_de_passe)
    compte.mot_de_passe_modifie_le = timezone.now()
    compte.save(update_fields=["mot_de_passe", "mot_de_passe_modifie_le"])
    fermer_sessions(compte)
    _reussite(compte.identifiant, compte)
    journaliser("reinitialiser_mot_de_passe_portail", compte, acteur=compte.contact)
    notifier("mot_de_passe_modifie", {}, contacts=[compte.contact])
    return Resultat("Votre mot de passe est modifié. Vous pouvez vous connecter.", {})


def verifier_mot_de_passe_actuel(compte: CompteUsager, mot_de_passe: str, message: str) -> None:
    """Hors transaction : l'échec est compté et le verrou progressif s'applique comme à la connexion (SEC-04)."""
    _refus_verrou(compte.identifiant)
    if not check_password(mot_de_passe, compte.mot_de_passe):
        _enregistrer_echec(compte.identifiant, compte)
        _refus_verrou(compte.identifiant)
        raise ErreurValidation(message, code="mot_de_passe_actuel")


def changer_mot_de_passe(compte: CompteUsager, actuel: str, nouveau: str, *, jeton: JetonPortail | None = None) -> None:
    verifier_mot_de_passe_actuel(compte, actuel, "Le mot de passe actuel est incorrect.")
    verifier_politique(nouveau, identifiant=compte.identifiant, prenom=compte.contact.prenom, nom=compte.contact.nom)
    with transaction.atomic():
        compte.mot_de_passe = make_password(nouveau)
        compte.mot_de_passe_modifie_le = timezone.now()
        compte.save(update_fields=["mot_de_passe", "mot_de_passe_modifie_le"])
        fermer_sessions(compte, sauf=jeton)
        journaliser("changer_mot_de_passe_portail", compte, acteur=compte.contact)
        notifier("mot_de_passe_modifie", {}, contacts=[compte.contact])


# --- Double authentification ----------------------------------------------------------------------


def commencer_totp(compte: CompteUsager) -> dict[str, str]:
    from apps.habilitations.totp import qr_svg

    graine = pyotp.random_base32()
    compte.totp_en_attente_chiffre = chiffrer(graine)
    compte.save(update_fields=["totp_en_attente_chiffre"])
    uri = pyotp.TOTP(graine).provisioning_uri(name=compte.identifiant, issuer_name=settings.TOTP_EMETTEUR)
    return {"uri": uri, "qr_svg": qr_svg(uri), "cle": graine}


def activer_totp(compte: CompteUsager, code: str, mot_de_passe: str) -> None:
    """Activation confirmée par le mot de passe : une session volée ne suffit pas à enrôler un téléphone."""
    verifier_mot_de_passe_actuel(compte, mot_de_passe, "Le mot de passe est incorrect.")
    if not compte.totp_en_attente_chiffre:
        raise ErreurValidation("Commencez par afficher le code QR.", code="totp_non_commence")
    graine = dechiffrer(compte.totp_en_attente_chiffre)
    if not _code_valide(compte, graine, code):
        raise ErreurValidation("Code incorrect. Vérifiez l'heure de votre téléphone et réessayez.", code="code_invalide")
    with transaction.atomic():
        compte.totp_secret_chiffre = chiffrer(graine)
        compte.totp_en_attente_chiffre = ""
        compte.totp_actif = True
        compte.save(update_fields=["totp_secret_chiffre", "totp_en_attente_chiffre", "totp_actif"])
        journaliser("activer_totp_portail", compte, acteur=compte.contact)
        notifier("totp_active", {}, contacts=[compte.contact])


def desactiver_totp(compte: CompteUsager, mot_de_passe: str) -> None:
    verifier_mot_de_passe_actuel(compte, mot_de_passe, "Le mot de passe est incorrect.")
    with transaction.atomic():
        compte.totp_actif = False
        compte.totp_secret_chiffre = ""
        compte.save(update_fields=["totp_actif", "totp_secret_chiffre"])
        journaliser("desactiver_totp_portail", compte, acteur=compte.contact)
        notifier("totp_desactive", {}, contacts=[compte.contact])


# --- Changement d'adresse électronique ------------------------------------------------------------------


def demander_changement_courriel(compte: CompteUsager, nouveau: str, mot_de_passe: str) -> Resultat:
    """La nouvelle adresse est confirmée par un lien qui lui est envoyé ; l'ancienne est prévenue du changement.

    Réponse identique si l'adresse est déjà utilisée (son titulaire est alors prévenu) : pas d'énumération.
    """
    verifier_mot_de_passe_actuel(compte, mot_de_passe, "Le mot de passe est incorrect.")
    adresse = normaliser_identifiant(nouveau)
    if adresse == compte.identifiant:
        raise ErreurValidation("C'est déjà l'adresse de votre compte.", code="adresse_identique")
    with transaction.atomic():
        existant = CompteUsager.objects.filter(identifiant=adresse).select_related("contact").first()
        if existant is not None:
            notifier(
                "compte_deja_existant",
                {"lien": f"{settings.PORTAIL_URL.rstrip('/')}/mot-de-passe-oublie"},
                contacts=[existant.contact],
            )
        else:
            jeton = emettre_jeton_unique(compte, "changement_courriel", timedelta(hours=24), donnee=adresse)
            notifier(
                "courriel_changement_confirmation",
                {"contact": compte.contact, "nouvelle": adresse},
                courriels=[adresse],
                secrets={"lien": _lien("confirmer-adresse", jeton)},
            )
        journaliser("demander_changement_courriel_portail", compte, acteur=compte.contact)
    return Resultat("Un lien de confirmation vient d'être envoyé à la nouvelle adresse. Il est valable 24 heures.", {})


@transaction.atomic
def confirmer_changement_courriel(valeur: str) -> Resultat:
    jeton = consommer_jeton(valeur, "changement_courriel")
    compte = jeton.compte
    if CompteUsager.objects.filter(identifiant=jeton.donnee).exclude(pk=compte.pk).exists():
        raise ErreurValidation("Ce lien n'est plus valable. Faites une nouvelle demande.", code="lien_invalide")
    ancienne = compte.contact.courriel
    compte.identifiant = jeton.donnee
    compte.save(update_fields=["identifiant"])
    contact = compte.contact
    contact.courriel = jeton.donnee
    contact.save(update_fields=["courriel"])
    fermer_sessions(compte)
    journaliser(
        "changer_courriel_portail", compte, avant={"courriel": ancienne}, apres={"courriel": jeton.donnee}, acteur=contact
    )
    notifier("courriel_contact_modifie", {"contact": contact, "nouvelle": jeton.donnee}, courriels=[ancienne])
    return Resultat("Votre nouvelle adresse est confirmée. Connectez-vous avec cette adresse.", {})
