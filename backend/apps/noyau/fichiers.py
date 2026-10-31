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
from urllib.parse import quote

from django.conf import settings
from django.http import FileResponse

from .exceptions import ErreurMetier, ErreurValidation
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
    if controle_facade == "clamav" and empreinte_facade == empreinte and getattr(settings, "CANAL", "") == "portail":
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


def enregistrer_genere(nom: str, contenu: bytes, type_mime: str, *, depose_par: str = "application") -> Fichier:
    """Stocke un fichier produit par l'application elle-même (PDF généré, jeu de démonstration) : pas d'analyse antivirale."""
    relatif = f"{secrets.token_hex(2)}/{secrets.token_hex(16)}"
    destination = Path(settings.MEDIA_ROOT) / relatif
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_bytes(contenu)
    return Fichier.objects.create(
        nom_origine=nom_sain(nom),
        type_mime=type_mime,
        taille=len(contenu),
        sha256=hashlib.sha256(contenu).hexdigest(),
        chemin=relatif,
        controle_antivirus="genere",
        depose_par=depose_par[:200],
    )


def enregistrer_analyse(nom: str, contenu: bytes, type_mime: str, *, depose_par: str) -> Fichier:
    """Fichier de données déposé par un agent (état d'encaissements…) : analysé par ClamAV avant d'être conservé."""
    if not contenu:
        raise ErreurValidation("Le fichier est vide.", code="fichier_vide")
    if len(contenu) > TAILLE_MAX:
        raise ErreurValidation(f"Le fichier dépasse {TAILLE_MAX // (1024 * 1024)} Mo.", code="fichier_trop_gros")
    try:
        signature = analyser_clamav(contenu)
    except OSError as erreur:
        raise ErreurValidation(
            "Le contrôle antivirus est momentanément indisponible. Réessayez plus tard.", code="antivirus_indisponible"
        ) from erreur
    if signature:
        raise ErreurValidation("Le fichier a été refusé par le contrôle antivirus.", code="fichier_infecte")
    fichier = enregistrer_genere(nom, contenu, type_mime, depose_par=depose_par)
    Fichier.objects.filter(pk=fichier.pk).update(controle_antivirus="clamav-lan")
    fichier.controle_antivirus = "clamav-lan"
    return fichier


PNG_SIGNATURE = b"\x89PNG\r\n\x1a\n"
#: Blocs PNG de texte et de métadonnées (auteur, logiciel, EXIF, date) retirés ; l'image elle-même est intacte.
PNG_METADONNEES = {b"tEXt", b"iTXt", b"zTXt", b"eXIf", b"tIME"}


def _png_sans_metadonnees(contenu: bytes) -> bytes:
    sortie, position = bytearray(PNG_SIGNATURE), len(PNG_SIGNATURE)
    while position + 12 <= len(contenu):
        longueur = int.from_bytes(contenu[position : position + 4], "big")
        type_bloc = contenu[position + 4 : position + 8]
        fin = position + 12 + longueur
        if fin > len(contenu):
            break
        if type_bloc not in PNG_METADONNEES:
            sortie += contenu[position:fin]
        position = fin
        if type_bloc == b"IEND":
            return bytes(sortie)
    return bytes(sortie + contenu[position:])


def sans_metadonnees(contenu: bytes) -> bytes:
    """Retire les métadonnées (géolocalisation, appareil, auteur) d'une photo JPEG (EXIF, XMP) ou PNG (blocs de
    texte, EXIF), sans réencodage."""
    if contenu.startswith(PNG_SIGNATURE):
        return _png_sans_metadonnees(contenu)
    if not contenu.startswith(b"\xff\xd8"):
        return contenu
    sortie, position = bytearray(b"\xff\xd8"), 2
    while position + 4 <= len(contenu) and contenu[position] == 0xFF:
        marqueur = contenu[position + 1]
        if marqueur == 0xDA:  # début des données d'image : le reste est recopié tel quel
            break
        longueur = int.from_bytes(contenu[position + 2 : position + 4], "big")
        segment = contenu[position : position + 2 + longueur]
        if marqueur != 0xE1:  # APP1 = EXIF / XMP
            sortie += segment
        position += 2 + longueur
    return bytes(sortie + contenu[position:])


def lire(fichier: Fichier) -> bytes:
    try:
        contenu = (Path(settings.MEDIA_ROOT) / fichier.chemin).read_bytes()
    except FileNotFoundError as erreur:
        raise ErreurMetier(
            "Ce fichier n'est plus disponible : il a été supprimé au terme de sa durée de conservation.", code="fichier_purge"
        ) from erreur
    if hashlib.sha256(contenu).hexdigest() != fichier.sha256:
        raise ErreurValidation("Le fichier stocké a été altéré : téléchargement refusé.", code="fichier_altere")
    return contenu


def reponse_telechargement(fichier: Fichier, en_ligne: bool = False) -> FileResponse:
    reponse = FileResponse(iter([lire(fichier)]), content_type=fichier.type_mime)
    disposition = "inline" if en_ligne else "attachment"
    nom_ascii = fichier.nom_origine.encode("ascii", "ignore").decode().replace('"', "") or "document"
    reponse["Content-Disposition"] = f"{disposition}; filename=\"{nom_ascii}\"; filename*=UTF-8''{quote(fichier.nom_origine)}"
    reponse["X-Content-Type-Options"] = "nosniff"
    return reponse
