"""Authentification des agents par l'Active Directory en LDAPS (SEC-02) et groupes → rôles (ADM-06).

Client complet sur ldap3 : LDAPS ou StartTLS avec vérification du certificat, compte de service
pour la recherche, liaison avec le DN de l'agent pour vérifier le mot de passe, lecture des groupes
selon trois modes (`memberof`, `ad_imbriques` par la règle LDAP_MATCHING_RULE_IN_CHAIN, `recherche`
par member/uniqueMember), échappement des filtres contre l'injection LDAP.
"""

from __future__ import annotations

import logging
import ssl
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from django.conf import settings
from django.contrib.auth.backends import BaseBackend
from django.db import transaction
from django.http import HttpRequest
from django.utils import timezone
from ldap3 import ALL_ATTRIBUTES, SUBTREE, Connection, Server, Tls
from ldap3.core.exceptions import LDAPBindError, LDAPException, LDAPInvalidCredentialsResult
from ldap3.utils.conv import escape_filter_chars

from apps.audit.services import journaliser

from .models import Utilisateur
from .services import synchroniser_groupes_ad

journal = logging.getLogger(__name__)
REGLE_IMBRICATION_AD = "1.2.840.113556.1.4.1941"


class AnnuaireIndisponible(Exception):
    pass


@dataclass
class EntreeAnnuaire:
    dn: str
    identifiant: str
    prenom: str = ""
    nom: str = ""
    courriel: str = ""
    groupes: list[str] = field(default_factory=list)


def _premiere(valeur: Any) -> str:
    if isinstance(valeur, list):
        return str(valeur[0]) if valeur else ""
    return "" if valeur is None else str(valeur)


class Annuaire:
    def __init__(self, configuration: dict[str, Any] | None = None, serveur: Server | None = None, strategie: str | None = None):
        self.conf: dict[str, Any] = configuration or settings.LDAP
        self._serveur = serveur
        self._strategie = strategie

    def serveur(self) -> Server:
        if self._serveur is not None:
            return self._serveur
        uri: str = self.conf["URI"]
        tls = None
        if uri.startswith("ldaps://") or self.conf["STARTTLS"]:
            fichier_ac = self.conf["FICHIER_AC"]
            tls = Tls(
                validate=ssl.CERT_REQUIRED if self.conf["VERIFIER_CERTIFICAT"] else ssl.CERT_NONE,
                version=ssl.PROTOCOL_TLS_CLIENT,
                ca_certs_file=fichier_ac if fichier_ac and Path(fichier_ac).is_file() else None,
            )
        return Server(uri, use_ssl=uri.startswith("ldaps://"), tls=tls, connect_timeout=self.conf["DELAI_SECONDES"])

    def _connexion(self, dn: str, mot_de_passe: str) -> Connection:
        options: dict[str, Any] = {"user": dn, "password": mot_de_passe, "receive_timeout": self.conf["DELAI_SECONDES"]}
        if self._strategie:
            options["client_strategy"] = self._strategie
        connexion = Connection(self.serveur(), raise_exceptions=True, **options)
        connexion.open()
        if self.conf["STARTTLS"] and not self.conf["URI"].startswith("ldaps://"):
            connexion.start_tls()
        connexion.bind()
        return connexion

    def connexion_service(self) -> Connection:
        try:
            return self._connexion(self.conf["COMPTE_SERVICE_DN"], self.conf["COMPTE_SERVICE_MOT_DE_PASSE"])
        except LDAPException as erreur:
            raise AnnuaireIndisponible(f"Liaison du compte de service impossible : {type(erreur).__name__}") from erreur

    def rechercher(self, identifiant: str) -> EntreeAnnuaire | None:
        conf = self.conf
        filtre = str(conf["FILTRE_UTILISATEUR"]).format(identifiant=escape_filter_chars(identifiant))
        attributs = [
            conf["ATTRIBUT_IDENTIFIANT"],
            conf["ATTRIBUT_PRENOM"],
            conf["ATTRIBUT_NOM"],
            conf["ATTRIBUT_COURRIEL"],
            conf["ATTRIBUT_GROUPES"],
        ]
        connexion = self.connexion_service()
        try:
            connexion.search(conf["BASE_UTILISATEURS"], filtre, search_scope=SUBTREE, attributes=attributs, size_limit=2)
            entrees = list(connexion.entries)
            if len(entrees) != 1:
                return None
            brut = entrees[0].entry_attributes_as_dict
            entree = EntreeAnnuaire(
                dn=entrees[0].entry_dn,
                identifiant=_premiere(brut.get(conf["ATTRIBUT_IDENTIFIANT"])) or identifiant,
                prenom=_premiere(brut.get(conf["ATTRIBUT_PRENOM"])),
                nom=_premiere(brut.get(conf["ATTRIBUT_NOM"])),
                courriel=_premiere(brut.get(conf["ATTRIBUT_COURRIEL"])),
            )
            entree.groupes = self.groupes(connexion, entree.dn, [str(g) for g in brut.get(conf["ATTRIBUT_GROUPES"], [])])
            return entree
        except LDAPException as erreur:
            raise AnnuaireIndisponible(f"Recherche impossible : {type(erreur).__name__}") from erreur
        finally:
            connexion.unbind()

    def groupes(self, connexion: Connection, dn: str, directs: list[str]) -> list[str]:
        mode = self.conf["MODE_GROUPES"]
        if mode == "memberof":
            return directs
        dn_echappe = escape_filter_chars(dn)
        if mode == "ad_imbriques":
            filtre = f"(member:{REGLE_IMBRICATION_AD}:={dn_echappe})"
        else:
            filtre = f"(|(member={dn_echappe})(uniqueMember={dn_echappe}))"
        connexion.search(self.conf["BASE_GROUPES"] or self.conf["BASE_UTILISATEURS"], filtre, search_scope=SUBTREE, attributes=[])
        return sorted({*directs, *(e.entry_dn for e in connexion.entries)})

    def authentifier(self, identifiant: str, mot_de_passe: str) -> EntreeAnnuaire | None:
        """Renvoie l'entrée de l'agent si le mot de passe est correct, None sinon."""
        if not identifiant or not mot_de_passe or len(identifiant) > 128:
            return None
        entree = self.rechercher(identifiant)
        if entree is None:
            return None
        try:
            connexion = self._connexion(entree.dn, mot_de_passe)
            connexion.unbind()
        except LDAPBindError, LDAPInvalidCredentialsResult:
            return None
        except LDAPException as erreur:
            raise AnnuaireIndisponible(f"Liaison impossible : {type(erreur).__name__}") from erreur
        return entree

    def tester(self) -> dict[str, Any]:
        """Diagnostic de raccordement (commande `tester_annuaire`)."""
        connexion = self.connexion_service()
        try:
            return {"serveur": self.conf["URI"], "lie": connexion.bound, "qui": connexion.extend.standard.who_am_i()}
        finally:
            connexion.unbind()


def annuaire() -> Annuaire:
    return Annuaire()


@transaction.atomic
def synchroniser_utilisateur(entree: EntreeAnnuaire) -> Utilisateur | None:
    identifiant = entree.identifiant.strip().lower()
    utilisateur, cree = Utilisateur.objects.get_or_create(username=identifiant, defaults={"source": "ad"})
    utilisateur.first_name = entree.prenom[:150]
    utilisateur.last_name = entree.nom[:150]
    utilisateur.email = entree.courriel[:254]
    utilisateur.derniere_synchronisation_ad = timezone.now()
    utilisateur.set_unusable_password()
    utilisateur.save()
    if cree:
        journaliser("creer_agent_ad", utilisateur, apres={"identifiant": identifiant}, acteur=utilisateur)
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


__all__ = ["ALL_ATTRIBUTES", "Annuaire", "AnnuaireIndisponible", "EntreeAnnuaire", "LdapBackend"]
