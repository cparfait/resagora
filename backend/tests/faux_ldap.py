"""Annuaire simulé implémentant le sous-ensemble de l'API python-ldap utilisé par `apps.habilitations.ldap`.

Les tests unitaires tournent ainsi sur tous les postes ; le comportement réel de python-ldap et de
l'annuaire est vérifié par les tests d'intégration contre le conteneur OpenLDAP (`-m integration`).
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any


class LDAPError(Exception):
    pass


class INVALID_CREDENTIALS(LDAPError):
    pass


class SIZELIMIT_EXCEEDED(LDAPError):
    pass


class SERVER_DOWN(LDAPError):
    pass


@dataclass
class Entree:
    dn: str
    attributs: dict[str, list[str | bytes]]
    mot_de_passe: str = ""


@dataclass
class Repertoire:
    entrees: dict[str, Entree] = field(default_factory=dict)
    panne: bool = False
    filtres: list[str] = field(default_factory=list)
    options: dict[int, Any] = field(default_factory=dict)

    def ajouter(self, dn: str, mot_de_passe: str = "", **attributs: list[str | bytes]) -> None:
        self.entrees[dn.lower()] = Entree(dn, attributs, mot_de_passe)


def _deseschapper(valeur: str) -> str:
    return re.sub(r"\\([0-9a-fA-F]{2})", lambda m: chr(int(m.group(1), 16)), valeur)


def _encoder(valeurs: list[str | bytes]) -> list[bytes]:
    return [v if isinstance(v, bytes) else v.encode("utf-8") for v in valeurs]


class Connexion:
    def __init__(self, repertoire: Repertoire):
        self.repertoire = repertoire

    def set_option(self, option: int, valeur: Any) -> None:
        self.repertoire.options[option] = valeur

    def start_tls_s(self) -> None:
        self.repertoire.options[-1] = "starttls"

    def simple_bind_s(self, dn: str, mot_de_passe: str) -> None:
        if self.repertoire.panne:
            raise SERVER_DOWN("annuaire injoignable")
        entree = self.repertoire.entrees.get(dn.lower())
        if entree is None or not mot_de_passe or entree.mot_de_passe != mot_de_passe:
            raise INVALID_CREDENTIALS("identifiants invalides")

    def unbind_s(self) -> None:
        return None

    def whoami_s(self) -> str:
        return "dn:simule"

    def search_ext_s(
        self, base: str, portee: int, filtre: str, attributs: list[str], sizelimit: int = 0
    ) -> list[tuple[str, dict[str, list[bytes]]]]:
        self.repertoire.filtres.append(filtre)
        conditions = re.findall(r"\(([A-Za-z]+)(?::[0-9.]+:)?=([^()]*)\)", filtre)
        resultats = []
        for entree in self.repertoire.entrees.values():
            if not entree.dn.lower().endswith(base.lower()):
                continue
            correspondances = []
            for attribut, valeur in conditions:
                attendu = _deseschapper(valeur).lower()
                presents = [str(v.decode() if isinstance(v, bytes) else v).lower() for v in entree.attributs.get(attribut, [])]
                correspondances.append(attendu in presents)
            if conditions and (all(correspondances) if filtre.startswith("(&") else any(correspondances)):
                resultats.append((entree.dn, {a: _encoder(entree.attributs[a]) for a in attributs if a in entree.attributs}))
        if sizelimit and len(resultats) > sizelimit:
            raise SIZELIMIT_EXCEEDED("trop de résultats")
        return resultats


class ModuleLdap:
    """Remplace le module `ldap` : constantes, exceptions et `initialize`."""

    OPT_PROTOCOL_VERSION, OPT_REFERRALS, OPT_NETWORK_TIMEOUT, OPT_TIMEOUT = 1, 2, 3, 4
    OPT_X_TLS_CACERTFILE, OPT_X_TLS_REQUIRE_CERT, OPT_X_TLS_DEMAND, OPT_X_TLS_NEVER = 5, 6, 7, 8
    OPT_X_TLS_PROTOCOL_MIN, OPT_X_TLS_PROTOCOL_TLS1_2, OPT_X_TLS_NEWCTX = 9, 10, 11
    SCOPE_SUBTREE = 2
    LDAPError = LDAPError
    INVALID_CREDENTIALS = INVALID_CREDENTIALS
    SIZELIMIT_EXCEEDED = SIZELIMIT_EXCEEDED
    SERVER_DOWN = SERVER_DOWN

    def __init__(self, repertoire: Repertoire):
        self.repertoire = repertoire

    def initialize(self, uri: str) -> Connexion:
        return Connexion(self.repertoire)
