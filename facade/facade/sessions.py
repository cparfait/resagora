"""Sessions des usagers : seule donnée conservée en DMZ, dans un Valkey dédié (SEC-01).

La session contient le jeton portail émis par l'API (jamais exposé au navigateur), le jeton
CSRF et les dates d'expiration. Le cookie ne porte qu'un identifiant aléatoire.
"""

from __future__ import annotations

import json
import secrets
import time
from dataclasses import asdict, dataclass
from typing import Protocol

import redis


@dataclass
class Session:
    jeton_api: str
    csrf: str
    cree_le: float
    expire_le: float
    contact: dict[str, object]

    def restant(self) -> int:
        return max(0, int(self.expire_le - time.time()))


class Magasin(Protocol):
    def lire(self, cle: str) -> str | None:
        """Valeur stockée sous `cle`, None si absente ou expirée."""
        ...

    def ecrire(self, cle: str, valeur: str, duree_s: int) -> None:
        """Écrit `valeur` sous `cle` pour `duree_s` secondes."""
        ...

    def supprimer(self, cle: str) -> None:
        """Supprime `cle`."""
        ...

    def incrementer(self, cle: str, fenetre_s: int) -> int:
        """Incrémente le compteur `cle` (créé pour `fenetre_s` secondes) et renvoie sa valeur."""
        ...


class MagasinValkey:
    def __init__(self, url: str):
        self.client = redis.Redis.from_url(url, socket_timeout=2, decode_responses=True)

    def lire(self, cle: str) -> str | None:
        valeur = self.client.get(cle)
        return None if valeur is None else str(valeur)

    def ecrire(self, cle: str, valeur: str, duree_s: int) -> None:
        self.client.set(cle, valeur, ex=duree_s)

    def supprimer(self, cle: str) -> None:
        self.client.delete(cle)

    def incrementer(self, cle: str, fenetre_s: int) -> int:
        tube = self.client.pipeline()
        tube.incr(cle)
        tube.expire(cle, fenetre_s, nx=True)
        valeur, _ = tube.execute()
        return int(valeur)


class MagasinMemoire:
    """Magasin en mémoire pour les tests et le développement sans Valkey."""

    def __init__(self) -> None:
        self.donnees: dict[str, tuple[str, float]] = {}

    def lire(self, cle: str) -> str | None:
        valeur = self.donnees.get(cle)
        if valeur is None or valeur[1] < time.time():
            self.donnees.pop(cle, None)
            return None
        return valeur[0]

    def ecrire(self, cle: str, valeur: str, duree_s: int) -> None:
        self.donnees[cle] = (valeur, time.time() + duree_s)

    def supprimer(self, cle: str) -> None:
        self.donnees.pop(cle, None)

    def incrementer(self, cle: str, fenetre_s: int) -> int:
        actuel = self.lire(cle)
        expiration = self.donnees[cle][1] if actuel is not None else time.time() + fenetre_s
        nouveau = int(actuel or 0) + 1
        self.donnees[cle] = (str(nouveau), expiration)
        return nouveau


class GestionnaireSessions:
    PREFIXE = "session:"

    def __init__(self, magasin: Magasin, duree_s: int, duree_max_s: int):
        self.magasin = magasin
        self.duree_s = duree_s
        self.duree_max_s = duree_max_s

    def creer(self, jeton_api: str, contact: dict[str, object]) -> tuple[str, Session]:
        identifiant = secrets.token_urlsafe(32)
        maintenant = time.time()
        session = Session(jeton_api, secrets.token_urlsafe(32), maintenant, maintenant + self.duree_s, contact)
        self._ecrire(identifiant, session)
        return identifiant, session

    def lire(self, identifiant: str | None) -> Session | None:
        if not identifiant or len(identifiant) > 64:
            return None
        brut = self.magasin.lire(self.PREFIXE + identifiant)
        if brut is None:
            return None
        session = Session(**json.loads(brut))
        if session.expire_le < time.time():
            self.supprimer(identifiant)
            return None
        return session

    def prolonger(self, identifiant: str, session: Session) -> Session:
        """Prolongation à la demande de l'usager (RGAA : temps limité), plafonnée à la durée maximale."""
        session.expire_le = min(time.time() + self.duree_s, session.cree_le + self.duree_max_s)
        self._ecrire(identifiant, session)
        return session

    def supprimer(self, identifiant: str) -> None:
        self.magasin.supprimer(self.PREFIXE + identifiant)

    def _ecrire(self, identifiant: str, session: Session) -> None:
        self.magasin.ecrire(self.PREFIXE + identifiant, json.dumps(asdict(session)), max(1, session.restant()))
