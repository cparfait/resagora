"""Contrôle des fichiers déposés en quarantaine DMZ (SEC-07).

Taille maximale, extension ET type réel (octets magiques) en liste blanche (PDF, JPEG, PNG),
analyse antivirale ClamAV (protocole INSTREAM), empreinte SHA-256. Le fichier n'est jamais
conservé : il est effacé de la quarantaine dès la fin du contrôle.
"""

from __future__ import annotations

import hashlib
import logging
import secrets
import socket
import struct
from dataclasses import dataclass
from pathlib import Path

journal = logging.getLogger("facade.fichiers")

TYPES_AUTORISES = {
    "application/pdf": ({".pdf"}, [b"%PDF-"]),
    "image/jpeg": ({".jpg", ".jpeg"}, [b"\xff\xd8\xff"]),
    "image/png": ({".png"}, [b"\x89PNG\r\n\x1a\n"]),
}
TAILLE_BLOC = 64 * 1024


class FichierRefuse(Exception):
    def __init__(self, message: str, code: str):
        super().__init__(message)
        self.message = message
        self.code = code


@dataclass
class FichierControle:
    nom_origine: str
    type_mime: str
    taille: int
    sha256: str
    contenu: bytes


def type_reel(entete: bytes) -> str | None:
    for type_mime, (_ext, signatures) in TYPES_AUTORISES.items():
        if any(entete.startswith(signature) for signature in signatures):
            return type_mime
    return None


def nom_sain(nom: str) -> str:
    """Nom d'origine conservé pour l'affichage seulement, sans chemin ni caractère de contrôle."""
    base = nom.replace("\\", "/").rsplit("/", 1)[-1]
    propre = "".join(c for c in base if c.isprintable() and c not in '<>:"|?*').strip(". ")
    return propre[:150] or "document"


class AnalyseurClamAV:
    def __init__(self, hote: str, port: int, delai_s: float = 30):
        self.hote, self.port, self.delai_s = hote, port, delai_s

    def analyser(self, chemin: Path) -> str | None:
        """Renvoie le nom de la signature détectée, ou None si le fichier est sain."""
        with socket.create_connection((self.hote, self.port), timeout=self.delai_s) as connexion:
            connexion.sendall(b"zINSTREAM\0")
            with chemin.open("rb") as flux:
                while bloc := flux.read(TAILLE_BLOC):
                    connexion.sendall(struct.pack("!L", len(bloc)) + bloc)
            connexion.sendall(struct.pack("!L", 0))
            reponse = b""
            while not reponse.endswith(b"\0"):
                morceau = connexion.recv(4096)
                if not morceau:
                    break
                reponse += morceau
        texte = reponse.rstrip(b"\0").decode("utf-8", errors="replace")
        if texte.endswith("OK"):
            return None
        if texte.endswith("FOUND"):
            return texte.rsplit(":", 1)[-1].removesuffix("FOUND").strip()
        raise OSError(f"Réponse ClamAV inattendue : {texte[:80]}")


class Quarantaine:
    def __init__(self, dossier: Path, taille_max: int, analyseur: AnalyseurClamAV):
        self.dossier, self.taille_max, self.analyseur = dossier, taille_max, analyseur

    def controler(self, nom: str, contenu: bytes) -> FichierControle:
        nom_affiche = nom_sain(nom)
        extension = Path(nom_affiche).suffix.lower()
        if len(contenu) == 0:
            raise FichierRefuse("Le fichier est vide.", "fichier_vide")
        if len(contenu) > self.taille_max:
            raise FichierRefuse(f"Le fichier dépasse {self.taille_max // (1024 * 1024)} Mo.", "fichier_trop_gros")
        type_mime = type_reel(contenu[:16])
        if type_mime is None or extension not in TYPES_AUTORISES[type_mime][0]:
            raise FichierRefuse("Format non accepté : seuls les fichiers PDF, JPEG et PNG sont acceptés.", "format_refuse")
        self.dossier.mkdir(parents=True, exist_ok=True)
        chemin = self.dossier / secrets.token_hex(16)
        try:
            chemin.write_bytes(contenu)
            try:
                signature = self.analyseur.analyser(chemin)
            except OSError as erreur:
                journal.error("Antivirus indisponible : %s", erreur)
                raise FichierRefuse(
                    "Le contrôle antivirus est momentanément indisponible. Réessayez plus tard.", "antivirus_indisponible"
                ) from erreur
            if signature is not None:
                journal.warning(
                    "Fichier infecté rejeté (signature %s, sha256 %s)", signature, hashlib.sha256(contenu).hexdigest()
                )
                raise FichierRefuse("Le fichier a été refusé par le contrôle antivirus.", "fichier_infecte")
        finally:
            chemin.unlink(missing_ok=True)
        return FichierControle(nom_affiche, type_mime, len(contenu), hashlib.sha256(contenu).hexdigest(), contenu)
