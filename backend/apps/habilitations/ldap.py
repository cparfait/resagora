"""Authentification des agents par l'Active Directory en LDAPS (SEC-02) et groupes → rôles (ADM-06).

Client sur **python-ldap** (OpenLDAP libldap, maintenu ; ADR 0003) : LDAPS ou StartTLS avec
vérification obligatoire du certificat par l'AC fournie en secret, renvois désactivés, compte de
service pour la recherche, liaison avec le DN de l'agent pour vérifier le mot de passe, filtres
échappés. Groupes lus selon trois modes : `memberof`, `ad_imbriques` (LDAP_MATCHING_RULE_IN_CHAIN)
ou `recherche` (member / uniqueMember). L'agent est apparié à son identifiant immuable
(`objectGUID` sur l'AD, `entryUUID` sur OpenLDAP), jamais au seul nom de compte.
"""

from __future__ import annotations

import logging
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from django.conf import settings
from django.contrib.auth.backends import BaseBackend
from django.db import transaction
from django.http import HttpRequest
from django.utils import timezone

from apps.audit.services import journaliser

from .models import Utilisateur
from .services import synchroniser_groupes_ad

journal = logging.getLogger(__name__)
REGLE_IMBRICATION_AD = "1.2.840.113556.1.4.1941"


class AnnuaireIndisponible(Exception):
    pass


def _ldap() -> Any:
    """Module python-ldap, importé à l'usage (absent des postes Windows sans OpenLDAP, voir ADR 0003)."""
    import ldap

    return ldap


def echapper(valeur: str) -> str:
    """Échappement RFC 4515 des valeurs insérées dans un filtre (anti-injection LDAP)."""
    resultat = []
    for caractere in valeur:
        if caractere in "*()\\\0" or ord(caractere) < 0x20:
            resultat.append("".join(f"\\{octet:02x}" for octet in caractere.encode("utf-8")))
        else:
            resultat.append(caractere)
    return "".join(resultat)


@dataclass
class EntreeAnnuaire:
    dn: str
    identifiant: str
    guid: str = ""
    prenom: str = ""
    nom: str = ""
    courriel: str = ""
    groupes: list[str] = field(default_factory=list)


def _texte(valeurs: list[bytes] | None) -> str:
    if not valeurs:
        return ""
    return valeurs[0].decode("utf-8", errors="replace")


def _guid(valeurs: list[bytes] | None) -> str:
    """objectGUID (16 octets, ordre AD) ou entryUUID (texte) → forme canonique."""
    if not valeurs:
        return ""
    brut = valeurs[0]
    if len(brut) == 16:
        return str(uuid.UUID(bytes_le=brut))
    return brut.decode("ascii", errors="replace").strip().lower()


class Annuaire:
    def __init__(self, configuration: dict[str, Any] | None = None, initialiser: Any = None):
        self.conf: dict[str, Any] = configuration or settings.LDAP
        self._initialiser = initialiser

    def _connexion(self) -> Any:
        ldap = _ldap()
        conf = self.conf
        fichier_ac = conf["FICHIER_AC"]
        if conf["VERIFIER_CERTIFICAT"] and not (fichier_ac and Path(fichier_ac).is_file()):
            raise AnnuaireIndisponible(f"Certificat de l'autorité de l'annuaire introuvable : {fichier_ac}")
        connexion = (self._initialiser or ldap.initialize)(conf["URI"])
        connexion.set_option(ldap.OPT_PROTOCOL_VERSION, 3)
        connexion.set_option(ldap.OPT_REFERRALS, 0)
        connexion.set_option(ldap.OPT_NETWORK_TIMEOUT, conf["DELAI_SECONDES"])
        connexion.set_option(ldap.OPT_TIMEOUT, conf["DELAI_SECONDES"])
        if conf["VERIFIER_CERTIFICAT"]:
            connexion.set_option(ldap.OPT_X_TLS_CACERTFILE, fichier_ac)
            connexion.set_option(ldap.OPT_X_TLS_REQUIRE_CERT, ldap.OPT_X_TLS_DEMAND)
        else:
            connexion.set_option(ldap.OPT_X_TLS_REQUIRE_CERT, ldap.OPT_X_TLS_NEVER)
        connexion.set_option(ldap.OPT_X_TLS_PROTOCOL_MIN, ldap.OPT_X_TLS_PROTOCOL_TLS1_2)
        connexion.set_option(ldap.OPT_X_TLS_NEWCTX, 0)
        if conf["STARTTLS"] and not str(conf["URI"]).startswith("ldaps://"):
            connexion.start_tls_s()
        return connexion

    def _lier(self, dn: str, mot_de_passe: str) -> Any:
        ldap = _ldap()
        try:
            connexion = self._connexion()
            connexion.simple_bind_s(dn, mot_de_passe)
        except ldap.INVALID_CREDENTIALS:
            raise
        except ldap.LDAPError as erreur:
            raise AnnuaireIndisponible(f"Liaison impossible : {type(erreur).__name__}") from erreur
        return connexion

    def connexion_service(self) -> Any:
        ldap = _ldap()
        try:
            return self._lier(self.conf["COMPTE_SERVICE_DN"], self.conf["COMPTE_SERVICE_MOT_DE_PASSE"])
        except ldap.INVALID_CREDENTIALS as erreur:
            raise AnnuaireIndisponible("Liaison du compte de service refusée (mot de passe ?)") from erreur

    def rechercher(self, identifiant: str) -> EntreeAnnuaire | None:
        ldap = _ldap()
        conf = self.conf
        filtre = str(conf["FILTRE_UTILISATEUR"]).format(identifiant=echapper(identifiant))
        attributs = [
            conf["ATTRIBUT_IDENTIFIANT"],
            conf["ATTRIBUT_PRENOM"],
            conf["ATTRIBUT_NOM"],
            conf["ATTRIBUT_COURRIEL"],
            conf["ATTRIBUT_GROUPES"],
            conf["ATTRIBUT_GUID"],
        ]
        connexion = self.connexion_service()
        try:
            resultats = [
                r
                for r in connexion.search_ext_s(conf["BASE_UTILISATEURS"], ldap.SCOPE_SUBTREE, filtre, attributs, sizelimit=2)
                if r[0]
            ]
            if len(resultats) != 1:
                return None
            dn, brut = resultats[0]
            entree = EntreeAnnuaire(
                dn=dn,
                identifiant=_texte(brut.get(conf["ATTRIBUT_IDENTIFIANT"])) or identifiant,
                guid=_guid(brut.get(conf["ATTRIBUT_GUID"])),
                prenom=_texte(brut.get(conf["ATTRIBUT_PRENOM"])),
                nom=_texte(brut.get(conf["ATTRIBUT_NOM"])),
                courriel=_texte(brut.get(conf["ATTRIBUT_COURRIEL"])),
            )
            directs = [g.decode("utf-8") for g in brut.get(conf["ATTRIBUT_GROUPES"], [])]
            entree.groupes = self.groupes(connexion, dn, directs)
            return entree
        except ldap.SIZELIMIT_EXCEEDED:
            return None
        except ldap.LDAPError as erreur:
            raise AnnuaireIndisponible(f"Recherche impossible : {type(erreur).__name__}") from erreur
        finally:
            connexion.unbind_s()

    def groupes(self, connexion: Any, dn: str, directs: list[str]) -> list[str]:
        ldap = _ldap()
        mode = self.conf["MODE_GROUPES"]
        if mode == "memberof":
            return sorted(directs)
        dn_echappe = echapper(dn)
        if mode == "ad_imbriques":
            filtre = f"(member:{REGLE_IMBRICATION_AD}:={dn_echappe})"
        else:
            filtre = f"(|(member={dn_echappe})(uniqueMember={dn_echappe}))"
        base = self.conf["BASE_GROUPES"] or self.conf["BASE_UTILISATEURS"]
        trouves = [r[0] for r in connexion.search_ext_s(base, ldap.SCOPE_SUBTREE, filtre, ["1.1"]) if r[0]]
        return sorted({*directs, *trouves})

    def authentifier(self, identifiant: str, mot_de_passe: str) -> EntreeAnnuaire | None:
        """Renvoie l'entrée de l'agent si le mot de passe est correct, None sinon (temps de réponse égalisé)."""
        ldap = _ldap()
        if not identifiant or not mot_de_passe or len(identifiant) > 128:
            return None
        entree = self.rechercher(identifiant)
        dn = entree.dn if entree else f"cn={uuid.uuid4().hex},{self.conf['BASE_UTILISATEURS']}"
        try:
            self._lier(dn, mot_de_passe).unbind_s()
        except ldap.INVALID_CREDENTIALS:
            return None
        return entree

    def tester(self) -> dict[str, Any]:
        """Diagnostic de raccordement (commande `tester_annuaire`)."""
        connexion = self.connexion_service()
        try:
            return {"serveur": self.conf["URI"], "lie": True, "qui": connexion.whoami_s()}
        finally:
            connexion.unbind_s()


def annuaire() -> Annuaire:
    return Annuaire()


@transaction.atomic
def synchroniser_utilisateur(entree: EntreeAnnuaire) -> Utilisateur | None:
    """Crée ou met à jour l'agent, apparié à son identifiant immuable d'annuaire (jamais au seul nom)."""
    identifiant = entree.identifiant.strip().lower()
    if not entree.guid:
        journaliser("connexion_refusee_sans_guid", objet_type="habilitations.utilisateur", apres={"dn": entree.dn})
        return None
    utilisateur = Utilisateur.objects.select_for_update().filter(identifiant_annuaire=entree.guid).first()
    if utilisateur is None:
        homonyme = Utilisateur.objects.select_for_update().filter(username=identifiant).first()
        if homonyme is not None:
            if homonyme.source != "ad" or homonyme.identifiant_annuaire:
                # Nom de compte réattribué à une autre personne, ou compte local : on ne fusionne jamais.
                journaliser("connexion_refusee_homonyme", homonyme, apres={"dn": entree.dn})
                return None
            homonyme.identifiant_annuaire = entree.guid
            utilisateur = homonyme
        else:
            utilisateur = Utilisateur(username=identifiant, source="ad", identifiant_annuaire=entree.guid)
            utilisateur.set_unusable_password()
            utilisateur.save()
            journaliser("creer_agent_ad", utilisateur, apres={"identifiant": identifiant}, acteur=utilisateur)
    if (
        utilisateur.username != identifiant
        and not Utilisateur.objects.filter(username=identifiant).exclude(pk=utilisateur.pk).exists()
    ):
        utilisateur.username = identifiant
    utilisateur.first_name = entree.prenom[:150]
    utilisateur.last_name = entree.nom[:150]
    utilisateur.email = entree.courriel[:254]
    utilisateur.derniere_synchronisation_ad = timezone.now()
    utilisateur.set_unusable_password()
    utilisateur.save()
    habilitations = synchroniser_groupes_ad(utilisateur, entree.groupes)
    if not habilitations and not utilisateur.habilitations.exists():
        journaliser("connexion_refusee_sans_role", utilisateur, acteur=utilisateur)
        return None
    return utilisateur


class LdapBackend(BaseBackend):
    def authenticate(
        self, request: HttpRequest | None, username: str | None = None, password: str | None = None, **kwargs: Any
    ) -> Utilisateur | None:
        if not username or not password:
            return None
        try:
            entree = annuaire().authentifier(username, password)
        except AnnuaireIndisponible as erreur:
            journal.error("Annuaire indisponible : %s", erreur)
            return None
        if entree is None:
            return None
        utilisateur = synchroniser_utilisateur(entree)
        if utilisateur is None or not utilisateur.is_active:
            return None
        return utilisateur

    def get_user(self, user_id: int) -> Utilisateur | None:
        return Utilisateur.objects.filter(pk=user_id, is_active=True).first()
