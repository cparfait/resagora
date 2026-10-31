"""Liste blanche des routes relayées vers l'API métier (SEC-01).

Toute route absente de cette liste reçoit 404. Chaque entrée fixe la méthode, le motif exact du
chemin, la nature du corps et la limitation de débit (SEC-06). Les identifiants d'objets sont
contraints à des entiers ou des UUID pour éviter toute traversée de chemin.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from enum import StrEnum


class Nature(StrEnum):
    JSON = "json"
    TELEVERSEMENT = "televersement"
    TELECHARGEMENT = "telechargement"
    CONNEXION = "connexion"
    DECONNEXION = "deconnexion"
    WEBHOOK_DOCUSEAL = "webhook_docuseal"
    NOTIFICATION_PAYFIP = "notification_payfip"
    MOBILE = "mobile"
    PHOTO_MOBILE = "photo_mobile"


@dataclass(frozen=True)
class Route:
    methode: str
    motif: re.Pattern[str]
    nature: Nature = Nature.JSON
    session_requise: bool = False
    debit: str = "public"


ID = r"[0-9]{1,12}"
UUID = r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}"


def r(methode: str, chemin: str, nature: Nature = Nature.JSON, session: bool = False, debit: str = "public") -> Route:
    return Route(methode, re.compile(chemin.replace("{id}", ID).replace("{uuid}", UUID), re.ASCII), nature, session, debit)


ROUTES: list[Route] = [
    # Catalogue et disponibilités publiques anonymisées (POR-02, POR-03, TAR-11)
    r("GET", "/api/portail/catalogue/sites"),
    r("GET", "/api/portail/catalogue/familles"),
    r("GET", "/api/portail/catalogue/espaces"),
    r("GET", "/api/portail/catalogue/espaces/{id}"),
    r("GET", "/api/portail/catalogue/espaces/{id}/photos/{id}", Nature.TELECHARGEMENT),
    r("GET", "/api/portail/catalogue/espaces/{id}/documents/{id}", Nature.TELECHARGEMENT),
    r("GET", "/api/portail/disponibilites"),
    r("POST", "/api/portail/simulation-tarif"),
    r("GET", "/api/portail/accessibilite"),
    # Comptes (POR-01, SEC-04)
    r("POST", "/api/portail/auth/connexion", Nature.CONNEXION, debit="connexion"),
    r("POST", "/api/portail/auth/totp", Nature.CONNEXION, debit="connexion"),
    r("POST", "/api/portail/auth/deconnexion", Nature.DECONNEXION, session=True),
    r("POST", "/api/portail/auth/inscription", debit="inscription"),
    r("POST", "/api/portail/auth/confirmation-courriel", debit="inscription"),
    r("POST", "/api/portail/auth/confirmation-nouvelle-adresse", debit="inscription"),
    r("POST", "/api/portail/auth/mot-de-passe-oublie", debit="reinitialisation"),
    r("POST", "/api/portail/auth/reinitialisation", debit="reinitialisation"),
    r("POST", "/api/portail/auth/invitation", debit="reinitialisation"),
    r("GET", "/api/portail/compte", session=True),
    r("PATCH", "/api/portail/compte", session=True),
    r("POST", "/api/portail/compte/mot-de-passe", session=True, debit="connexion"),
    r("POST", "/api/portail/compte/courriel", session=True, debit="connexion"),
    r("GET", "/api/portail/compte/totp", session=True),
    r("POST", "/api/portail/compte/totp", session=True, debit="connexion"),
    r("DELETE", "/api/portail/compte/totp", session=True),
    r("GET", "/api/portail/compte/export", Nature.TELECHARGEMENT, session=True),
    r("GET", "/api/portail/compte/preferences", session=True),
    r("PATCH", "/api/portail/compte/preferences", session=True),
    r("POST", "/api/portail/compte/preferences/telephone", session=True, debit="connexion"),
    # Usagers et contacts
    r("GET", "/api/portail/usagers", session=True),
    r("GET", "/api/portail/usagers/{id}", session=True),
    r("PATCH", "/api/portail/usagers/{id}", session=True),
    r("GET", "/api/portail/usagers/{id}/contacts", session=True),
    r("POST", "/api/portail/usagers/{id}/contacts", session=True),
    r("PATCH", "/api/portail/usagers/{id}/contacts/{id}", session=True),
    r("DELETE", "/api/portail/usagers/{id}/contacts/{id}", session=True),
    r("GET", "/api/portail/usagers/{id}/documents", session=True),
    r("GET", "/api/portail/usagers/{id}/documents/{id}/fichier", Nature.TELECHARGEMENT, session=True),
    r("GET", "/api/portail/usagers/{id}/pieces", session=True),
    r("POST", "/api/portail/usagers/{id}/pieces", Nature.TELEVERSEMENT, session=True, debit="televersement"),
    r("GET", "/api/portail/usagers/{id}/pieces/{id}/fichier", Nature.TELECHARGEMENT, session=True),
    r("GET", "/api/portail/pieces-exigees", session=True),
    r("GET", "/api/portail/types-demande", session=True),
    # Demandes et dossiers (POR-04, POR-05)
    r("GET", "/api/portail/dossiers", session=True),
    r("POST", "/api/portail/dossiers", session=True, debit="depot"),
    r("GET", "/api/portail/dossiers/{id}", session=True),
    r("PATCH", "/api/portail/dossiers/{id}", session=True),
    r("DELETE", "/api/portail/dossiers/{id}", session=True),
    r("POST", "/api/portail/dossiers/{id}/envoyer", session=True, debit="depot"),
    r("POST", "/api/portail/dossiers/{id}/annuler", session=True),
    r("POST", "/api/portail/dossiers/{id}/occurrences/{id}/annuler", session=True),
    r("GET", "/api/portail/dossiers/{id}/documents", session=True),
    r("GET", "/api/portail/dossiers/{id}/documents/{id}/fichier", Nature.TELECHARGEMENT, session=True),
    r("POST", "/api/portail/dossiers/{id}/documents/{id}/scan-signe", Nature.TELEVERSEMENT, session=True, debit="televersement"),
    r("GET", "/api/portail/dossiers/{id}/documents/{id}/signature", session=True),
    r("POST", "/api/portail/dossiers/{id}/devis/{id}/accepter", session=True),
    r("GET", "/api/portail/dossiers/{id}/messages", session=True),
    r("POST", "/api/portail/dossiers/{id}/messages", session=True, debit="depot"),
    r("POST", "/api/portail/dossiers/{id}/pieces", Nature.TELEVERSEMENT, session=True, debit="televersement"),
    r("GET", "/api/portail/campagnes", session=True),
    r("POST", "/api/portail/campagnes/{id}/demandes", session=True, debit="depot"),
    # Finances (POR-05, TAR-12, POR-07 au lot 7)
    r("GET", "/api/portail/factures", session=True),
    r("GET", "/api/portail/factures/{id}/fichier", Nature.TELECHARGEMENT, session=True),
    r("POST", "/api/portail/factures/{id}/paiement-en-ligne", session=True, debit="depot"),
    r("GET", "/api/portail/paiements/{uuid}", session=True),
    r("GET", "/api/portail/cautions", session=True),
    r("GET", "/api/portail/attestations", session=True),
    r("GET", "/api/portail/attestations/{id}/fichier", Nature.TELECHARGEMENT, session=True),
    r("GET", "/api/portail/materiel", session=True),
    r("POST", "/api/portail/dossiers/{id}/materiel", session=True, debit="depot"),
    r("GET", "/api/portail/notifications", session=True),
    r("POST", "/api/portail/notifications/{id}/lue", session=True),
    # Rappels entrants des tiers, vérifiés ici puis revérifiés par l'API (SIG-02, TAR-07)
    r("POST", "/api/portail/webhooks/docuseal", Nature.WEBHOOK_DOCUSEAL, debit="webhook"),
    r("POST", "/api/portail/payfip/notification", Nature.NOTIFICATION_PAYFIP, debit="webhook"),
]

ROUTES_MOBILE: list[Route] = [
    # Option B uniquement (SEC-10) : certificat d'appareil vérifié par le proxy DMZ, puis par l'API.
    r("POST", "/api/mobile/auth/connexion", Nature.MOBILE, debit="connexion"),
    r("POST", "/api/mobile/auth/totp", Nature.MOBILE, debit="connexion"),
    r("POST", "/api/mobile/auth/deconnexion", Nature.MOBILE),
    r("GET", "/api/mobile/sante", Nature.MOBILE),
    r("GET", "/api/mobile/paquet", Nature.MOBILE),
    r("POST", "/api/mobile/saisies", Nature.MOBILE, debit="televersement"),
    r("POST", "/api/mobile/photos", Nature.PHOTO_MOBILE, debit="televersement"),
]

DEBITS: dict[str, tuple[int, int]] = {
    "public": (120, 60),
    "connexion": (10, 60),
    "inscription": (5, 3600),
    "reinitialisation": (5, 3600),
    "depot": (30, 3600),
    "televersement": (60, 3600),
    "webhook": (300, 60),
}


def trouver(methode: str, chemin: str, mobile_option: str = "A") -> Route | None:
    routes = ROUTES + (ROUTES_MOBILE if mobile_option == "B" else [])
    for route in routes:
        if route.methode == methode and route.motif.fullmatch(chemin):
            return route
    return None
