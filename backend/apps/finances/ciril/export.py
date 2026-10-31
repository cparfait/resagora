"""Adaptateur d'export des titres de recettes vers CIVIL Finances Publiques (Ciril GROUP) — TAR-06.

Le format d'import de Ciril n'est pas public : il est défini avec l'éditeur. Ce module le rend entièrement
paramétrable sans toucher au métier :
- `ciril.format` : `csv`, `xlsx` ou `xml` ;
- `ciril.colonnes` : liste ordonnée `{"entete": …, "champ": …}` (champs disponibles : `CHAMPS`) ;
- `ciril.csv_separateur`, `ciril.csv_encodage` ; `ciril.xml_racine`, `ciril.xml_element` ;
- `ciril.imputation`, `ciril.code_produit` : valeurs fixes reprises dans chaque ligne.
Un export est un lot numéroté, rejouable à l'identique (le fichier est conservé), tracé (qui, quand).
"""

from __future__ import annotations

import csv
import io
from collections.abc import Callable
from typing import TYPE_CHECKING, Any
from xml.etree import ElementTree as ET

from openpyxl import Workbook

from apps.noyau.parametres import parametre
from apps.noyau.tableur import cellule_sure, texte_xml

from ..models import PieceComptable

if TYPE_CHECKING:
    from apps.reservations.models import Dossier
    from apps.usagers.models import Usager


# Champs numériques : jamais préfixés (un avoir de -12,00 reste un montant) ; tous les autres sont neutralisés.
CHAMPS_NUMERIQUES = {"montant", "montant_centimes", "exercice", "montant_encaisse_regie_centimes"}


def _montant(centimes: int) -> str:
    """Montant en euros, virgule décimale, calculé en entiers (règle 5 : jamais de flottant)."""
    signe = "-" if centimes < 0 else ""
    euros_, reste = divmod(abs(centimes), 100)
    return f"{signe}{euros_},{reste:02d}"


def _champ_usager(piece: PieceComptable, champ: str) -> str:
    usager: Usager = piece.usager
    return str(getattr(usager, champ) or "")


def _encaisse_regie(piece: PieceComptable) -> int:
    """Lot 7 (ADR 0008) : sommes déjà encaissées par la régie (PayFiP Régie) — le comptable émet un titre de
    régularisation au lieu de recouvrer une seconde fois."""
    return sum(e.montant for e in piece.encaissements.all() if e.origine == "payfip")


def _numero_dossier(piece: PieceComptable) -> str:
    dossier: Dossier = piece.dossier
    return dossier.numero


CHAMPS: dict[str, Callable[[PieceComptable], Any]] = {
    "numero_facture": lambda p: p.numero or "",
    "nature": lambda p: "AVOIR" if p.nature == "avoir" else "FACTURE",
    "date_emission": lambda p: f"{p.emise_le:%d/%m/%Y}" if p.emise_le else "",
    "exercice": lambda p: p.exercice or "",
    "echeance": lambda p: f"{p.echeance:%d/%m/%Y}" if p.echeance else "",
    "debiteur_nom": lambda p: _champ_usager(p, "nom"),
    "debiteur_siret": lambda p: _champ_usager(p, "siret"),
    "debiteur_adresse": lambda p: _champ_usager(p, "adresse"),
    "debiteur_code_postal": lambda p: _champ_usager(p, "code_postal"),
    "debiteur_commune": lambda p: _champ_usager(p, "commune"),
    "debiteur_courriel": lambda p: _champ_usager(p, "courriel"),
    "objet": lambda p: p.objet[:200],
    "montant": lambda p: _montant(p.total_du - p.acompte_deduit),
    "montant_centimes": lambda p: p.total_du - p.acompte_deduit,
    "reference_virement": lambda p: p.reference_virement,
    "dossier": _numero_dossier,
    "facture_origine": lambda p: p.origine.numero if p.nature == "avoir" and p.origine else "",
    "imputation": lambda p: parametre("ciril.imputation"),
    "code_produit": lambda p: parametre("ciril.code_produit"),
    "mode_encaissement": lambda p: "REGIE" if _encaisse_regie(p) else "",
    "montant_encaisse_regie": lambda p: _montant(_encaisse_regie(p)),
    "montant_encaisse_regie_centimes": _encaisse_regie,
}


def lignes(pieces: list[PieceComptable]) -> tuple[list[str], list[list[Any]]]:
    colonnes = parametre("ciril.colonnes")
    entetes = [cellule_sure(c["entete"]) for c in colonnes]
    contenu = [
        [CHAMPS[c["champ"]](p) if c["champ"] in CHAMPS_NUMERIQUES else cellule_sure(CHAMPS[c["champ"]](p)) for c in colonnes]
        for p in pieces
    ]
    return entetes, contenu


def produire(pieces: list[PieceComptable], format_export: str | None = None) -> tuple[bytes, str, str]:
    """(contenu, extension, type MIME) du fichier d'export selon le paramétrage en vigueur."""
    format_export = format_export or str(parametre("ciril.format"))
    entetes, contenu = lignes(pieces)
    if format_export == "csv":
        sortie = io.StringIO()
        ecrivain = csv.writer(sortie, delimiter=str(parametre("ciril.csv_separateur")), lineterminator="\r\n")
        ecrivain.writerow(entetes)
        ecrivain.writerows(contenu)
        return sortie.getvalue().encode(str(parametre("ciril.csv_encodage")), errors="replace"), "csv", "text/csv"
    if format_export == "xlsx":
        classeur = Workbook()
        feuille = classeur.active
        feuille.title = "Titres"
        feuille.append(entetes)
        for ligne in contenu:
            feuille.append(ligne)
        for rangee in feuille.iter_rows():
            for cellule in rangee:
                if isinstance(cellule.value, str):
                    cellule.data_type = "s"  # jamais de formule, même si le texte commence par « = »
        tampon = io.BytesIO()
        classeur.save(tampon)
        return tampon.getvalue(), "xlsx", "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
    if format_export == "xml":
        racine = ET.Element(str(parametre("ciril.xml_racine")))
        for ligne in contenu:
            element = ET.SubElement(racine, str(parametre("ciril.xml_element")))
            for colonne, valeur in zip(parametre("ciril.colonnes"), ligne, strict=True):
                ET.SubElement(element, colonne["champ"]).text = texte_xml(str(valeur).removeprefix("'"))
        return ET.tostring(racine, encoding="utf-8", xml_declaration=True), "xml", "application/xml"
    raise ValueError(f"Format d'export Ciril inconnu : {format_export}")
