"""Configuration de la façade : aucun secret du LAN, seulement ses propres secrets (SEC-01, SEC-09)."""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path

DOSSIER_SECRETS = Path(os.environ.get("DOSSIER_SECRETS", "/run/secrets"))


def secret(nom: str, defaut: str = "") -> str:
    chemin = Path(os.environ.get(f"{nom.upper()}_FICHIER", DOSSIER_SECRETS / nom))
    if chemin.is_file():
        return chemin.read_text(encoding="utf-8").strip()
    return defaut


def _entier(nom: str, defaut: int) -> int:
    valeur = os.environ.get(nom, "")
    return int(valeur) if valeur else defaut


@dataclass
class Configuration:
    api_url: str = field(default_factory=lambda: os.environ.get("API_URL", "https://api-portail:8443"))
    certificat_client: str = field(default_factory=lambda: os.environ.get("CERTIFICAT_CLIENT", "/run/secrets/facade_client.crt"))
    cle_client: str = field(default_factory=lambda: os.environ.get("CLE_CLIENT", "/run/secrets/facade_client.key"))
    ac_api: str = field(default_factory=lambda: os.environ.get("AC_API", "/run/secrets/ac_interne.crt"))
    valkey_url: str = field(
        default_factory=lambda: secret("valkey_dmz_url", os.environ.get("VALKEY_URL", "redis://valkey-dmz:6379/0"))
    )
    origine: str = field(default_factory=lambda: os.environ.get("ORIGINE_PORTAIL", "https://equipements.chatillon.fr"))
    cookies_securises: bool = field(default_factory=lambda: os.environ.get("COOKIES_SECURISES", "1") == "1")
    duree_session_s: int = field(default_factory=lambda: _entier("DUREE_SESSION_SECONDES", 1800))
    duree_session_max_s: int = field(default_factory=lambda: _entier("DUREE_SESSION_MAX_SECONDES", 12 * 3600))
    taille_max_fichier: int = field(default_factory=lambda: _entier("TAILLE_MAX_FICHIER_OCTETS", 10 * 1024 * 1024))
    taille_max_json: int = field(default_factory=lambda: _entier("TAILLE_MAX_JSON_OCTETS", 256 * 1024))
    dossier_quarantaine: Path = field(default_factory=lambda: Path(os.environ.get("DOSSIER_QUARANTAINE", "/quarantaine")))
    clamav_hote: str = field(default_factory=lambda: os.environ.get("CLAMAV_HOTE", "clamav"))
    clamav_port: int = field(default_factory=lambda: _entier("CLAMAV_PORT", 3310))
    secret_webhook_docuseal: str = field(default_factory=lambda: secret("docuseal_webhook_secret"))
    entete_webhook_docuseal: str = field(default_factory=lambda: os.environ.get("ENTETE_WEBHOOK_DOCUSEAL", "X-Docuseal-Secret"))
    ips_payfip: list[str] = field(
        default_factory=lambda: [i.strip() for i in os.environ.get("IPS_NOTIFICATION_PAYFIP", "").split(",") if i.strip()]
    )
    payfip_sans_filtre_ip: bool = field(default_factory=lambda: os.environ.get("PAYFIP_SANS_FILTRE_IP", "0") == "1")
    mobile_option: str = field(default_factory=lambda: os.environ.get("MOBILE_OPTION", "A"))
    entete_certificat_appareil: str = field(
        default_factory=lambda: os.environ.get("ENTETE_CERTIFICAT_APPAREIL", "X-Forwarded-Tls-Client-Cert-Info")
    )
    nombre_proxies: int = field(default_factory=lambda: _entier("NOMBRE_PROXIES", 1))
    # Recette automatisée uniquement : multiplie les seuils de débit (SEC-06) ; 1 en production.
    facteur_debit: int = field(default_factory=lambda: max(1, int(os.environ.get("FACTEUR_DEBIT", "1"))))
    delai_api_s: float = field(default_factory=lambda: float(os.environ.get("DELAI_API_SECONDES", "15")))
