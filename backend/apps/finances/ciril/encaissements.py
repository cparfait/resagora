"""Import de l'état des titres soldés exporté de Ciril (TAR-13), au format paramétrable.

`ciril.import_colonnes` associe les champs attendus aux en-têtes du fichier fourni par le service financier :
`{"titre": "N° titre", "facture": "Référence", "montant": "Montant encaissé", "date": "Date encaissement",
"reference": "Référence paiement"}`. Le rapprochement se fait sur le numéro de titre, à défaut sur le
numéro de facture. Chaque ligne non rapprochée figure au rapport, avec son motif ; l'import est rejouable :
un encaissement déjà enregistré (même titre, même date, même montant) n'est pas dupliqué.
"""

from __future__ import annotations

import csv
import io
import zipfile
from datetime import date, datetime, timedelta
from typing import Any

from django.db import transaction
from openpyxl import load_workbook

from apps.audit.services import journaliser
from apps.noyau import fichiers
from apps.noyau.exceptions import ErreurMetier, ErreurValidation
from apps.noyau.montants import centimes
from apps.noyau.parametres import parametre

from ..facturation import enregistrer_encaissement
from ..models import Encaissement, ImportEncaissements, PieceComptable

TYPE_XLSX = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"


LIGNES_MAX = 5000
TAILLE_DECOMPRESSEE_MAX = 50 * 1024 * 1024


def _controler_classeur(contenu: bytes) -> None:
    """Bombe zip : le tableur décompressé ne dépasse pas 50 Mo et reste un vrai classeur XLSX."""
    try:
        with zipfile.ZipFile(io.BytesIO(contenu)) as archive:
            membres = archive.infolist()
            if "xl/workbook.xml" not in {m.filename for m in membres}:
                raise ErreurValidation("Ce fichier n'est pas un classeur XLSX.", code="format_refuse")
            if sum(m.file_size for m in membres) > TAILLE_DECOMPRESSEE_MAX:
                raise ErreurValidation("Classeur trop volumineux une fois décompressé.", code="fichier_trop_gros")
    except zipfile.BadZipFile as erreur:
        raise ErreurValidation("Classeur XLSX illisible.", code="format_refuse") from erreur


def _lire_lignes(nom: str, contenu: bytes) -> list[dict[str, str]]:
    if nom.lower().endswith(".xlsx") or contenu.startswith(b"PK\x03\x04"):
        _controler_classeur(contenu)
        classeur = load_workbook(io.BytesIO(contenu), read_only=True, data_only=True)
        feuille = classeur.active
        rangees = [[("" if v is None else str(v)).strip() for v in r] for r in feuille.iter_rows(values_only=True)]
        if not rangees:
            return []
        entetes = rangees[0]
        return [dict(zip(entetes, r, strict=False)) for r in rangees[1:] if any(r)]
    texte = (
        contenu.decode("utf-8-sig", errors="replace")
        if b"\xef\xbb\xbf" in contenu[:3]
        else contenu.decode("cp1252", errors="replace")
    )
    try:
        dialecte = csv.Sniffer().sniff(texte[:2048], delimiters=";,\t")
        separateur = dialecte.delimiter
    except csv.Error:
        separateur = ";"
    return [
        {(k or "").strip(): (v or "").strip() for k, v in r.items()}
        for r in csv.DictReader(io.StringIO(texte), delimiter=separateur)
    ]


def _date(valeur: str) -> date:
    for forme in ("%d/%m/%Y", "%Y-%m-%d", "%d/%m/%y", "%Y-%m-%d %H:%M:%S"):
        try:
            return datetime.strptime(valeur.strip(), forme).date()
        except ValueError:
            continue
    raise ErreurValidation(f"Date illisible : « {valeur} ».", code="date_invalide")


@transaction.atomic
def importer(nom: str, contenu: bytes, *, acteur: Any) -> ImportEncaissements:
    from ..titres import exiger_ville_entiere

    exiger_ville_entiere(acteur, "encaisser")
    if not nom.lower().endswith((".csv", ".xlsx", ".txt")):
        raise ErreurValidation("Format attendu : CSV ou tableur XLSX exporté de Ciril.", code="format_refuse")
    correspondance = parametre("ciril.import_colonnes")
    rangees = _lire_lignes(nom, contenu)
    if len(rangees) > LIGNES_MAX:
        raise ErreurValidation(f"L'état dépasse {LIGNES_MAX} lignes : importez-le en plusieurs fichiers.", code="trop_de_lignes")
    if rangees:
        absentes = [entete for cle, entete in correspondance.items() if cle in {"montant", "date"} and entete not in rangees[0]]
        if absentes or not ({correspondance.get("titre"), correspondance.get("facture")} & set(rangees[0])):
            raise ErreurValidation(
                "Colonnes attendues absentes de l'état : "
                + ", ".join(absentes or [correspondance.get("titre", "")])
                + " (paramètre « ciril.import_colonnes »).",
                code="colonnes_absentes",
            )
    fichier = fichiers.enregistrer_analyse(
        nom, contenu, TYPE_XLSX if nom.lower().endswith(".xlsx") else "text/csv", depose_par=str(acteur)
    )
    lot = ImportEncaissements.objects.create(fichier=fichier, lignes_lues=len(rangees), cree_par=acteur)
    rejets: list[dict[str, Any]] = []
    rapprochees = 0
    for rang, rangee in enumerate(rangees, start=2):
        valeur = {cle: rangee.get(entete, "") for cle, entete in correspondance.items()}
        try:
            montant = centimes(valeur.get("montant", ""))
            if montant <= 0:
                raise ErreurMetier(
                    "montant nul ou négatif (rejet ou annulation de paiement) : à traiter manuellement", code="montant_negatif"
                )
            jour = _date(valeur.get("date", ""))
            piece = None
            if valeur.get("titre"):
                piece = PieceComptable.objects.select_for_update().filter(titre_numero=valeur["titre"]).first()
            if piece is None and valeur.get("facture"):
                piece = PieceComptable.objects.select_for_update().filter(numero=valeur["facture"]).first()
            if piece is None:
                raise ErreurMetier("aucune facture ne correspond au titre ou à la référence", code="introuvable")
            reference = valeur.get("reference") or valeur.get("titre") or ""
            if Encaissement.objects.filter(piece=piece, date=jour, montant=montant, origine="import").exists():
                raise ErreurMetier("encaissement déjà importé", code="doublon")
            proche = Encaissement.objects.filter(
                piece=piece, montant=montant, date__gte=jour - timedelta(days=7), date__lte=jour + timedelta(days=7)
            ).first()
            if proche is not None:
                raise ErreurMetier(
                    f"un règlement de même montant est déjà enregistré le {proche.date:%d/%m/%Y} ({proche.get_origine_display().lower()}) : à vérifier",
                    code="doublon_probable",
                )
            with transaction.atomic():
                enregistrer_encaissement(
                    piece, montant=montant, jour=jour, reference=reference, origine="import", agent=acteur, import_lot=lot
                )
            rapprochees += 1
        except ErreurMetier as erreur:
            rejets.append(
                {"ligne": rang, "titre": valeur.get("titre", ""), "facture": valeur.get("facture", ""), "motif": erreur.message}
            )
    lot.rapprochees, lot.rejets = rapprochees, rejets
    lot.save(update_fields=["rapprochees", "rejets"])
    journaliser(
        "importer_encaissements",
        lot,
        apres={"lues": len(rangees), "rapprochees": rapprochees, "rejets": len(rejets)},
        acteur=acteur,
    )
    return lot
