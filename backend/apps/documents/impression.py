"""Éditions imprimables (IMP-01, IMP-02, IMP-03) : tableau noir et blanc A4 ou A3, date d'édition, QR code vers la
version en ligne, converti en PDF/A par Gotenberg comme les autres documents (DOC-04).

Le .docx intermédiaire est construit avec python-docx : une impression est une vue du planning à un instant donné,
pas un document contractuel ; elle n'est pas archivée (rien d'immuable à conserver).
"""

from __future__ import annotations

import io
from dataclasses import dataclass, field
from datetime import datetime

import segno
from django.utils import timezone
from docx import Document as DocumentWord
from docx.enum.section import WD_ORIENT
from docx.enum.table import WD_TABLE_ALIGNMENT
from docx.oxml import OxmlElement
from docx.oxml.ns import qn
from docx.shared import Cm, Pt, RGBColor

from apps.documents import gotenberg
from apps.noyau.exceptions import ErreurValidation
from apps.noyau.tableur import texte_xml

FORMATS = {"A4": (Cm(21.0), Cm(29.7)), "A3": (Cm(29.7), Cm(42.0))}
NOIR = RGBColor(0, 0, 0)


@dataclass
class Edition:
    titre: str
    sous_titre: str
    entetes: list[str]
    lignes: list[list[str]]
    lien: str = ""
    format_papier: str = "A4"
    paysage: bool = True
    groupes: list[tuple[str, list[list[str]]]] = field(default_factory=list)
    mention_vide: str = "Aucun créneau sur la période."


def _repeter_entete(ligne: object) -> None:
    proprietes = ligne._tr.get_or_add_trPr()  # type: ignore[attr-defined]
    marque = OxmlElement("w:tblHeader")
    marque.set(qn("w:val"), "true")
    proprietes.append(marque)


def _tableau(document: object, entetes: list[str], lignes: list[list[str]]) -> None:
    table = document.add_table(rows=1, cols=len(entetes))  # type: ignore[attr-defined]
    table.style = "Table Grid"
    table.alignment = WD_TABLE_ALIGNMENT.CENTER
    _repeter_entete(table.rows[0])
    for cellule, texte in zip(table.rows[0].cells, entetes, strict=True):
        cellule.text = ""
        execution = cellule.paragraphs[0].add_run(texte_xml(texte))
        execution.bold = True
        execution.font.size = Pt(9)
    for valeurs in lignes:
        cellules = table.add_row().cells
        for cellule, texte in zip(cellules, valeurs, strict=True):
            cellule.text = ""
            execution = cellule.paragraphs[0].add_run(texte_xml(texte))
            execution.font.size = Pt(9)
            execution.font.color.rgb = NOIR


def construire_docx(edition: Edition, maintenant: datetime | None = None) -> bytes:
    if edition.format_papier not in FORMATS:
        raise ErreurValidation("Format d'impression : A4 ou A3.", code="format_invalide")
    maintenant = timezone.localtime(maintenant or timezone.now())
    document = DocumentWord()
    edition.titre, edition.sous_titre = texte_xml(edition.titre), texte_xml(edition.sous_titre)
    document.core_properties.title = edition.titre
    document.core_properties.language = "fr-FR"
    section = document.sections[0]
    largeur, hauteur = FORMATS[edition.format_papier]
    if edition.paysage:
        section.orientation = WD_ORIENT.LANDSCAPE
        section.page_width, section.page_height = hauteur, largeur
    else:
        section.page_width, section.page_height = largeur, hauteur
    for marge in ("left_margin", "right_margin", "top_margin", "bottom_margin"):
        setattr(section, marge, Cm(1.2))
    style = document.styles["Normal"]
    style.font.name = "Liberation Sans"
    style.font.size = Pt(10)
    document.add_heading(edition.titre, level=1)
    paragraphe = document.add_paragraph(edition.sous_titre)
    paragraphe.add_run(f"\nÉdité le {maintenant:%d/%m/%Y à %H:%M} — la version en ligne fait foi.").italic = True
    if edition.lien:
        image = io.BytesIO()
        segno.make(edition.lien, error="m").save(image, kind="png", scale=4, border=1, dark="black", light="white")
        image.seek(0)
        bloc = document.add_paragraph()
        bloc.add_run().add_picture(image, width=Cm(2.5))
        bloc.add_run(f"  Version en ligne : {edition.lien}").font.size = Pt(8)
    if edition.groupes:
        for intitule, lignes in edition.groupes:
            document.add_heading(texte_xml(intitule), level=2)
            if lignes:
                _tableau(document, edition.entetes, lignes)
            else:
                document.add_paragraph(edition.mention_vide)
    elif edition.lignes:
        _tableau(document, edition.entetes, edition.lignes)
    else:
        document.add_paragraph(edition.mention_vide)
    pied = section.footer.paragraphs[0]
    pied.text = f"Ville de Châtillon — {edition.titre} — édité le {maintenant:%d/%m/%Y}"
    sortie = io.BytesIO()
    document.save(sortie)
    return sortie.getvalue()


def imprimer(edition: Edition) -> bytes:
    """PDF/A de l'édition ; Gotenberg indisponible → erreur lisible (503), jamais un PDF vide."""
    return gotenberg.convertir_en_pdfa("edition.docx", construire_docx(edition))
