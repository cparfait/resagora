"""Éditions imprimables (IMP-01, IMP-02, IMP-03) : tableau noir et blanc A4 ou A3, date d'édition, QR code vers la
version en ligne, converti en PDF/A par Gotenberg comme les autres documents (DOC-04).

Deux mises en page : la liste (un tableau par jour) et le calendrier — une grille par semaine, une colonne par jour,
une ligne par demi-heure, chaque séance en bloc grisé sur sa durée, comme la vue semaine du planning à l'écran. Les
séances qui se chevauchent un même jour (plusieurs espaces d'un site) occupent des sous-colonnes côte à côte.

Le .docx intermédiaire est construit avec python-docx : une impression est une vue du planning à un instant donné,
pas un document contractuel ; elle n'est pas archivée (rien d'immuable à conserver).
"""

from __future__ import annotations

import io
import math
from dataclasses import dataclass, field
from datetime import date, datetime, time, timedelta

import segno
from django.utils import timezone
from docx import Document as DocumentWord
from docx.enum.section import WD_ORIENT
from docx.enum.table import WD_ROW_HEIGHT_RULE, WD_TABLE_ALIGNMENT
from docx.enum.text import WD_ALIGN_PARAGRAPH, WD_BREAK
from docx.oxml import OxmlElement
from docx.oxml.ns import qn
from docx.shared import Cm, Length, Pt, RGBColor

from apps.documents import gotenberg
from apps.noyau.exceptions import ErreurValidation
from apps.noyau.tableur import texte_xml

FORMATS = {"A4": (Cm(21.0), Cm(29.7)), "A3": (Cm(29.7), Cm(42.0))}
NOIR = RGBColor(0, 0, 0)
JOURS_COURTS = ["Lun.", "Mar.", "Mer.", "Jeu.", "Ven.", "Sam.", "Dim."]
PAS_MINUTES = 30
GRIS, GRIS_CLAIR = "D9D9D9", "F2F2F2"
MISES_EN_PAGE = ("calendrier", "liste")


@dataclass
class Bloc:
    """Une séance dans la grille : colonne 0 (lundi) à 6 (dimanche) ; une fin à minuit s'écrit time(0)."""

    colonne: int
    debut: time
    fin: time
    lignes: list[str]
    provisoire: bool = False


@dataclass
class Grille:
    intitule: str
    jours: list[str]
    blocs: list[Bloc]
    afficher_intitule: bool = False


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
    grilles: list[Grille] = field(default_factory=list)


def verifier_mise_en_page(valeur: str) -> str:
    if valeur not in MISES_EN_PAGE:
        raise ErreurValidation("Mise en page : calendrier ou liste.", code="mise_en_page_invalide")
    return valeur


def grilles_datees(
    du: date, au: date, seances: list[tuple[datetime, datetime, list[str], bool]], *, prefixe: str = ""
) -> list[Grille]:
    """Une grille par semaine (lundi → dimanche) couvrant la période ; heures locales Europe/Paris attendues. Le
    préfixe (nom de l'espace dans le planning d'un site) s'affiche au-dessus de chaque grille."""
    lundi = du - timedelta(days=du.weekday())
    grilles = []
    while lundi <= au:
        dimanche = lundi + timedelta(days=6)
        blocs = [
            Bloc(debut.weekday(), debut.time(), fin.time() if fin.date() == debut.date() else time(0), lignes, provisoire)
            for debut, fin, lignes, provisoire in seances
            if lundi <= debut.date() <= dimanche
        ]
        jours = [f"{JOURS_COURTS[i]} {lundi + timedelta(days=i):%d/%m}" for i in range(7)]
        semaine = f"semaine du {lundi:%d/%m/%Y} au {dimanche:%d/%m/%Y}"
        intitule = f"{prefixe} — {semaine}" if prefixe else semaine.capitalize()
        grilles.append(Grille(intitule, jours, blocs, afficher_intitule=bool(prefixe)))
        lundi += timedelta(days=7)
    return grilles


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


# --- Calendrier ---------------------------------------------------------------------------------------------------


def _minutes(heure: time, *, fin: bool = False) -> int:
    valeur = heure.hour * 60 + heure.minute
    return 24 * 60 if fin and valeur == 0 else valeur


def _ombrer(cellule: object, couleur: str) -> None:
    ombre = OxmlElement("w:shd")
    ombre.set(qn("w:val"), "clear")
    ombre.set(qn("w:color"), "auto")
    ombre.set(qn("w:fill"), couleur)
    cellule._tc.get_or_add_tcPr().append(ombre)  # type: ignore[attr-defined]


def _pointiller(cellule: object, cote: str) -> None:
    """Trait pointillé à la demi-heure, trait plein à l'heure : la grille se lit comme un agenda. Le trait est posé
    des deux côtés (bas de la cellule du dessus, haut de celle du dessous) pour qu'aucun moteur ne garde le plein."""
    bordures = OxmlElement("w:tcBorders")
    trait = OxmlElement(f"w:{cote}")
    for attribut, valeur in (("w:val", "dotted"), ("w:sz", "4"), ("w:space", "0"), ("w:color", "808080")):
        trait.set(qn(attribut), valeur)
    bordures.append(trait)
    cellule._tc.get_or_add_tcPr().append(bordures)  # type: ignore[attr-defined]


def _ecrire(cellule: object, lignes: list[str], *, taille: float = 7, gras_premiere: bool = False, centre: bool = False) -> None:
    cellule.text = ""  # type: ignore[attr-defined]
    for rang, texte in enumerate(lignes):
        paragraphe = cellule.paragraphs[0] if rang == 0 else cellule.add_paragraph()  # type: ignore[attr-defined]
        mise_en_forme = paragraphe.paragraph_format
        mise_en_forme.space_before = mise_en_forme.space_after = Pt(0)
        mise_en_forme.line_spacing = 1.0
        if centre:
            paragraphe.alignment = WD_ALIGN_PARAGRAPH.CENTER
        execution = paragraphe.add_run(texte_xml(texte))
        execution.font.size = Pt(taille)
        execution.font.color.rgb = NOIR
        execution.bold = gras_premiere and rang == 0


def _marges_cellules(table: object) -> None:
    marges = OxmlElement("w:tblCellMar")
    for cote in ("left", "right"):
        element = OxmlElement(f"w:{cote}")
        element.set(qn("w:w"), "40")
        element.set(qn("w:type"), "dxa")
        marges.append(element)
    table._tbl.tblPr.append(marges)  # type: ignore[attr-defined]


def _couloirs(intervalles: list[tuple[int, int, Bloc]]) -> tuple[list[int], int]:
    """Sous-colonne de chaque bloc d'un jour (triés par début) et nombre de sous-colonnes : partition gloutonne."""
    fins: list[int] = []
    rangs = []
    for premiere, derniere, _ in intervalles:
        libre = next((i for i, fin in enumerate(fins) if fin < premiere), None)
        if libre is None:
            fins.append(derniere)
            rangs.append(len(fins) - 1)
        else:
            fins[libre] = derniere
            rangs.append(libre)
    return rangs, max(1, len(fins))


def _calendrier(document: object, grille: Grille, largeur: int, hauteur: int) -> None:
    debuts = [_minutes(b.debut) for b in grille.blocs]
    fins = [max(_minutes(b.fin, fin=True), debut + PAS_MINUTES) for b, debut in zip(grille.blocs, debuts, strict=True)]
    heure_min = min([8 * 60, *debuts]) // 60
    heure_max = min(24, math.ceil(max([22 * 60, *fins]) / 60))
    nombre_lignes = (heure_max - heure_min) * 60 // PAS_MINUTES
    par_jour: list[list[tuple[int, int, Bloc]]] = [[] for _ in range(7)]
    for bloc, debut, fin in zip(grille.blocs, debuts, fins, strict=True):
        premiere = max(0, (debut - heure_min * 60) // PAS_MINUTES)
        derniere = min(nombre_lignes - 1, math.ceil((fin - heure_min * 60) / PAS_MINUTES) - 1)
        par_jour[bloc.colonne].append((premiere, max(premiere, derniere), bloc))
    couloirs = []
    for intervalles in par_jour:
        intervalles.sort(key=lambda element: (element[0], -element[1]))
        couloirs.append(_couloirs(intervalles))
    table = document.add_table(rows=1 + nombre_lignes, cols=1 + sum(n for _, n in couloirs))  # type: ignore[attr-defined]
    table.style = "Table Grid"
    table.alignment = WD_TABLE_ALIGNMENT.CENTER
    table.autofit = False
    _marges_cellules(table)
    _repeter_entete(table.rows[0])
    # Largeur proportionnelle au nombre de séances simultanées : un jour chargé s'élargit, un jour libre se resserre.
    largeur_heures = Cm(1.1)
    largeur_couloir = (largeur - largeur_heures) // sum(nombre for _, nombre in couloirs)
    largeurs = [Length(largeur_heures)] + [Length(largeur_couloir)] * (len(table.columns) - 1)
    for colonne, mesure in zip(table.columns, largeurs, strict=True):
        colonne.width = mesure  # grille du tableau (w:gridCol), seule lue par LibreOffice
    hauteur_ligne = Length(max(Cm(0.38), hauteur // max(1, nombre_lignes)))
    for rang, ligne in enumerate(table.rows):
        ligne.height = Cm(0.6) if rang == 0 else hauteur_ligne
        ligne.height_rule = WD_ROW_HEIGHT_RULE.AT_LEAST
        demi_heure = rang > 0 and (heure_min * 60 + (rang - 1) * PAS_MINUTES) % 60 != 0
        avant_demi_heure = 0 < rang < nombre_lignes and (heure_min * 60 + rang * PAS_MINUTES) % 60 != 0
        for colonne, cellule in enumerate(ligne.cells):
            cellule.width = largeurs[colonne]
            if demi_heure:
                _pointiller(cellule, "top")
            elif avant_demi_heure:
                _pointiller(cellule, "bottom")
    _ecrire(table.cell(0, 0), ["Heure"], taille=8, gras_premiere=True, centre=True)
    for rang in range(nombre_lignes):
        minutes = heure_min * 60 + rang * PAS_MINUTES
        if minutes % 60 == 0:
            _ecrire(table.cell(1 + rang, 0), [f"{minutes // 60:02d}:00"])
    colonne = 1
    for jour, (rangs, nombre) in enumerate(couloirs):
        entete = table.cell(0, colonne)
        if nombre > 1:
            entete = entete.merge(table.cell(0, colonne + nombre - 1))
        _ecrire(entete, [grille.jours[jour]], taille=8, gras_premiere=True, centre=True)
        for (premiere, derniere, bloc), couloir in zip(par_jour[jour], rangs, strict=True):
            cellule = table.cell(1 + premiere, colonne + couloir)
            if derniere > premiere:
                cellule = cellule.merge(table.cell(1 + derniere, colonne + couloir))
            _ecrire(cellule, bloc.lignes, gras_premiere=True)
            _ombrer(cellule, GRIS_CLAIR if bloc.provisoire else GRIS)
        colonne += nombre


def _grilles(document: object, edition: Edition, page_largeur: int, page_hauteur: int) -> None:
    marge = Cm(1.2)
    # En-tête compact (titre et QR code côte à côte), intitulé, ligne des jours et pied de page : environ 5 cm.
    utile_largeur, utile_hauteur = page_largeur - 2 * marge, page_hauteur - 2 * marge - Cm(5.4)
    if not any(g.blocs for g in edition.grilles):
        document.add_paragraph(edition.mention_vide)  # type: ignore[attr-defined]
    for rang, grille in enumerate(edition.grilles):
        if rang:
            document.add_paragraph().add_run().add_break(WD_BREAK.PAGE)  # type: ignore[attr-defined]
        if grille.intitule and (grille.afficher_intitule or len(edition.grilles) > 1):
            document.add_heading(texte_xml(grille.intitule), level=2)  # type: ignore[attr-defined]
        _calendrier(document, grille, utile_largeur, utile_hauteur)


def _qr(lien: str) -> io.BytesIO:
    image = io.BytesIO()
    segno.make(lien, error="m").save(image, kind="png", scale=4, border=1, dark="black", light="white")
    image.seek(0)
    return image


def _entete_compact(document: object, edition: Edition, edite: str, largeur: int) -> None:
    """Calendrier : titre à gauche, QR code à droite, pour laisser la hauteur de la page à la grille."""
    table = document.add_table(rows=1, cols=2)  # type: ignore[attr-defined]
    table.autofit = False
    droite = Cm(4.6) if edition.lien else Cm(0.1)
    for colonne, mesure in zip(table.columns, (Length(largeur - droite), Length(droite)), strict=True):
        colonne.width = mesure
        colonne.cells[0].width = mesure
    gauche, qr = table.rows[0].cells
    gauche.paragraphs[0].style = document.styles["Heading 1"]  # type: ignore[attr-defined]
    gauche.paragraphs[0].add_run(edition.titre)
    gauche.add_paragraph().add_run(edition.sous_titre).font.size = Pt(9)
    gauche.add_paragraph().add_run(edite).italic = True
    if edition.lien:
        qr.paragraphs[0].alignment = WD_ALIGN_PARAGRAPH.RIGHT
        qr.paragraphs[0].add_run().add_picture(_qr(edition.lien), width=Cm(1.8))
        legende = qr.add_paragraph()
        legende.alignment = WD_ALIGN_PARAGRAPH.RIGHT
        execution = legende.add_run(f"Version en ligne : {edition.lien}")
        execution.font.size = Pt(6)


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
    if edition.paysage or edition.grilles:
        section.orientation = WD_ORIENT.LANDSCAPE
        largeur, hauteur = hauteur, largeur
        section.page_width, section.page_height = largeur, hauteur
    else:
        section.page_width, section.page_height = largeur, hauteur
    for marge in ("left_margin", "right_margin", "top_margin", "bottom_margin"):
        setattr(section, marge, Cm(1.2))
    style = document.styles["Normal"]
    style.font.name = "Liberation Sans"
    style.font.size = Pt(10)
    edite = f"Édité le {maintenant:%d/%m/%Y à %H:%M} — la version en ligne fait foi."
    if edition.grilles:
        _entete_compact(document, edition, edite, largeur - Cm(2.4))
    else:
        document.add_heading(edition.titre, level=1)
        paragraphe = document.add_paragraph(edition.sous_titre)
        paragraphe.add_run(f"\n{edite}").italic = True
        if edition.lien:
            bloc = document.add_paragraph()
            bloc.add_run().add_picture(_qr(edition.lien), width=Cm(2.5))
            bloc.add_run(f"  Version en ligne : {edition.lien}").font.size = Pt(8)
    if edition.grilles:
        _grilles(document, edition, largeur, hauteur)
    elif edition.groupes:
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
