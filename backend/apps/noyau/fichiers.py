"""Stockage contrôlé des fichiers (SEC-07, DOC-07).

- Type réel vérifié par les octets magiques (PDF, JPEG, PNG ; DOCX pour les modèles), taille maximale ;
- analyse ClamAV (INSTREAM) pour tout fichier qui ne vient pas déjà de la quarantaine DMZ ;
- nom aléatoire hors racine web, empreinte SHA-256 enregistrée et revérifiée à la lecture ;
- téléchargement uniquement par des vues qui contrôlent les droits, en `Content-Disposition: attachment`.
"""

from __future__ import annotations

import hashlib
import os
import secrets
import socket
import struct
from pathlib import Path

from django.conf import settings
from django.http import FileResponse

from .exceptions import ErreurValidation
from .models import Fichier

TYPES = {
    "application/pdf": ([b"%PDF-"], {".pdf"}),
    "image/jpeg": ([b"\xff\xd8\xff"], {".jpg", ".jpeg"}),
    "image/png": ([b"\x89PNG\r\n\x1a\n"], {".png"}),
    "application/vnd.openxmlformats-officedocument.wordprocessingml.document": ([b"PK\x03\x04"], {".docx"}),
}
TYPES_PIECES = ("application/pdf", "image/jpeg", "image/png")
TAILLE_MAX = int(os.environ.get("TAILLE_MAX_FICHIER_OCTETS", str(10 * 1024 * 1024)))


def type_reel(contenu: bytes) -> str | None:
    for type_mime, (signatures, _extensions) in TYPES.items():
        if any(contenu.startswith(s) for s in signatures):
            return type_mime
    return None


def nom_sain(nom: str) -> str:
    base = nom.replace("\\", "/").rsplit("/", 1)[-1]
    propre = "".join(c for c in base if c.isprintable() and c not in '<>:"|?*').strip(". ")
    return propre[:150] or "document"


def analyser_clamav(contenu: bytes) -> str | None:
    """Renvoie le nom de la signature détectée, None si sain. Lève OSError si l'antivirus est injoignable."""
    hote = os.environ.get("CLAMAV_HOTE", "clamav")
    port = int(os.environ.get("CLAMAV_PORT", "3310"))
    with socket.create_connection((hote, port), timeout=30) as connexion:
        connexion.sendall(b"zINSTREAM\0")
        for debut in range(0, len(contenu), 65536):
            bloc = contenu[debut : debut + 65536]
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
    raise OSError(f"Réponse ClamAV inattendue : {texte[:60]}")


def enregistrer(
    nom: str,
    contenu: bytes,
    *,
    types_autorises: tuple[str, ...] = TYPES_PIECES,
    depose_par: str = "",
    controle_facade: str = "",
    empreinte_facade: str = "",
) -> Fichier:
    """Contrôle puis stocke un fichier. `controle_facade` = « clamav » si la façade DMZ l'a déjà analysé."""
    nom_affiche = nom_sain(nom)
    if not contenu:
        raise ErreurValidation("Le fichier est vide.", code="fichier_vide")
    if len(contenu) > TAILLE_MAX:
        raise ErreurValidation(f"Le fichier dépasse {TAILLE_MAX // (1024 * 1024)} Mo.", code="fichier_trop_gros")
    type_mime = type_reel(contenu[:16])
    if type_mime is None or type_mime not in types_autorises or Path(nom_affiche).suffix.lower() not in TYPES[type_mime][1]:
        formats = ", ".join(sorted({e.lstrip(".").upper() for t in types_autorises for e in TYPES[t][1]}))
        raise ErreurValidation(f"Format non accepté. Formats acceptés : {formats}.", code="format_refuse")
    empreinte = hashlib.sha256(contenu).hexdigest()
    if controle_facade == "clamav" and empreinte_facade == empreinte:
        controle = "clamav-dmz"
    else:
        try:
            signature = analyser_clamav(contenu)
        except OSError as erreur:
            raise ErreurValidation(
                "Le contrôle antivirus est momentanément indisponible. Réessayez plus tard.", code="antivirus_indisponible"
            ) from erreur
        if signature:
            raise ErreurValidation("Le fichier a été refusé par le contrôle antivirus.", code="fichier_infecte")
        controle = "clamav-lan"
    relatif = f"{secrets.token_hex(2)}/{secrets.token_hex(16)}"
    destination = Path(settings.MEDIA_ROOT) / relatif
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_bytes(contenu)
    return Fichier.objects.create(
        nom_origine=nom_affiche,
        type_mime=type_mime,
        taille=len(contenu),
        sha256=empreinte,
        chemin=relatif,
        controle_antivirus=controle,
        depose_par=depose_par[:200],
    )


def lire(fichier: Fichier) -> bytes:
    contenu = (Path(settings.MEDIA_ROOT) / fichier.chemin).read_bytes()
    if hashlib.sha256(contenu).hexdigest() != fichier.sha256:
        raise ErreurValidation("Le fichier stocké a été altéré : téléchargement refusé.", code="fichier_altere")
    return contenu


def reponse_telechargement(fichier: Fichier, en_ligne: bool = False) -> FileResponse:
    reponse = FileResponse(iter([lire(fichier)]), content_type=fichier.type_mime)
    disposition = "inline" if en_ligne else "attachment"
    nom_ascii = fichier.nom_origine.encode("ascii", "ignore").decode() or "document"
    reponse["Content-Disposition"] = f'{disposition}; filename="{nom_ascii}"'
    reponse["X-Content-Type-Options"] = "nosniff"
    return reponse
