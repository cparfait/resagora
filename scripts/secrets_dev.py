"""Génère des secrets aléatoires de DÉVELOPPEMENT / RECETTE dans deploy/*/secrets (ignorés par Git, SEC-09).

En production, ces fichiers sont fournis par l'exploitation (voir docs/a-brancher.md). Idempotent :
un secret existant n'est jamais remplacé.
"""

from __future__ import annotations

import base64
import secrets
import sys
from pathlib import Path

RACINE = Path(__file__).resolve().parent.parent
LAN, DMZ, DEV = (RACINE / "deploy" / z / "secrets" for z in ("lan", "dmz", "dev"))
RETOUR_CHARIOT = bytes([13])


def jeton(octets: int = 32) -> str:
    return secrets.token_urlsafe(octets)


def ecrire(chemin: Path, valeur: str) -> None:
    if chemin.exists():
        return
    chemin.parent.mkdir(parents=True, exist_ok=True)
    chemin.write_bytes((valeur + "\n").encode("utf-8"))
    chemin.chmod(0o600)


def lire(chemin: Path) -> str:
    return chemin.read_bytes().decode("utf-8").strip()


def normaliser() -> None:
    """Fins de ligne LF : un secret écrit en CRLF sous Windows casserait les mots de passe."""
    for dossier in (LAN, DMZ, DEV):
        for chemin in dossier.glob("*"):
            if chemin.is_file() and chemin.suffix not in {".crt", ".key", ".p12"}:
                contenu = chemin.read_bytes()
                if RETOUR_CHARIOT in contenu:
                    chemin.write_bytes(contenu.replace(RETOUR_CHARIOT, b""))


def main() -> int:
    normaliser()
    ecrire(LAN / "django_secret_key", jeton(48))
    ecrire(LAN / "cle_chiffrement", base64.urlsafe_b64encode(secrets.token_bytes(32)).decode())
    ecrire(LAN / "postgres_password", jeton(24))
    ecrire(LAN / "valkey_mot_de_passe", jeton(24))
    ecrire(DMZ / "valkey_mot_de_passe", jeton(24))
    for zone, hote in ((LAN, "valkey"), (DMZ, "valkey-dmz")):
        nom = "valkey_url" if zone is LAN else "valkey_dmz_url"
        if (zone / nom).exists() and "@" not in lire(zone / nom):
            (zone / nom).unlink()
        ecrire(zone / nom, f"redis://:{lire(zone / 'valkey_mot_de_passe')}@{hote}:6379/0")
    ecrire(LAN / "ldap_mot_de_passe", jeton(18))
    ecrire(LAN / "docuseal_api_jeton", "a-renseigner-apres-creation-du-compte-docuseal")
    ecrire(LAN / "docuseal_webhook_secret", jeton(24))
    ecrire(LAN / "payfip_secret", jeton(24))
    ecrire(LAN / "smtp_mot_de_passe", "")
    ecrire(DMZ / "docuseal_webhook_secret", lire(LAN / "docuseal_webhook_secret"))
    ecrire(DEV / "ldap_mot_de_passe", lire(LAN / "ldap_mot_de_passe"))
    ecrire(DEV / "ldap_admin_mot_de_passe", jeton(18))
    ecrire(DEV / "mdp_agents_demo", "Demo-" + jeton(9))
    print("Secrets de développement présents dans deploy/lan/secrets, deploy/dmz/secrets et deploy/dev/secrets.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
