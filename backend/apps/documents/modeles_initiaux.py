"""Catalogue des modèles livrés (DOC-02), construits en .docx éditables dans Word (syntaxe docxtpl/Jinja).

Chaque modèle est produit ici une seule fois (version 1, migration de données) ; l'administrateur
fonctionnel le télécharge, le modifie dans Word et dépose de nouvelles versions (DOC-01). Les documents
utilisent de vrais styles de titres, une langue déclarée et des en-têtes de tableaux répétés, pour que le
PDF/UA produit par Gotenberg soit lisible par les lecteurs d'écran.
"""

from __future__ import annotations

import io
from collections.abc import Callable
from dataclasses import dataclass

from docx import Document as DocumentWord
from docx.enum.text import WD_ALIGN_PARAGRAPH
from docx.oxml import OxmlElement
from docx.oxml.ns import qn
from docx.shared import Pt


@dataclass(frozen=True)
class ModeleInitial:
    code: str
    libelle: str
    nature: str
    signature_requise: bool
    signataires: tuple[str, ...]
    description: str
    construire: Callable[[], bytes]


class Redaction:
    def __init__(self, titre: str):
        self.doc = DocumentWord()
        self.doc.core_properties.title = titre
        self.doc.core_properties.language = "fr-FR"
        self.doc.core_properties.author = "{{ ville.nom }}"
        normal = self.doc.styles["Normal"]
        normal.font.name = "Arial"
        normal.font.size = Pt(10.5)
        langue = OxmlElement("w:lang")
        langue.set(qn("w:val"), "fr-FR")
        normal.element.get_or_add_rPr().append(langue)
        entete = self.doc.sections[0].header.paragraphs[0]
        entete.text = "{{ ville.nom }} — {{ ville.service }}"
        pied = self.doc.sections[0].footer.paragraphs[0]
        pied.text = "{{ ville.adresse }} — {{ ville.telephone }} — {{ ville.courriel }}"

    def titre(self, texte: str, niveau: int = 1) -> None:
        self.doc.add_heading(texte, level=niveau)

    def texte(self, texte: str, *, gras: bool = False, droite: bool = False) -> None:
        paragraphe = self.doc.add_paragraph()
        morceau = paragraphe.add_run(texte)
        morceau.bold = gras
        if droite:
            paragraphe.alignment = WD_ALIGN_PARAGRAPH.RIGHT

    def liste(self, variable: str, element: str, expression: str) -> None:
        """Paragraphe répété : `{%p for element in variable %}` … `{%p endfor %}`."""
        self.doc.add_paragraph(f"{{%p for {element} in {variable} %}}")
        self.doc.add_paragraph(expression, style="List Bullet")
        self.doc.add_paragraph("{%p endfor %}")

    def tableau(self, entetes: list[str], variable: str, element: str, cellules: list[str]) -> None:
        """Tableau dont les lignes sont répétées par docxtpl (`{%tr for %}`), ligne d'en-tête répétée."""
        table = self.doc.add_table(rows=4, cols=len(entetes))
        table.style = "Table Grid"
        for i, entete in enumerate(entetes):
            cellule = table.rows[0].cells[i]
            cellule.text = entete
            cellule.paragraphs[0].runs[0].bold = True
        propriete = table.rows[0]._tr.get_or_add_trPr()
        repetition = OxmlElement("w:tblHeader")
        repetition.set(qn("w:val"), "true")
        propriete.append(repetition)
        table.rows[1].cells[0].text = f"{{%tr for {element} in {variable} %}}"
        for i, contenu in enumerate(cellules):
            table.rows[2].cells[i].text = contenu
        table.rows[3].cells[0].text = "{%tr endfor %}"

    def signatures(self, gauche: str, droite: str) -> None:
        table = self.doc.add_table(rows=2, cols=2)
        table.rows[0].cells[0].text = gauche
        table.rows[0].cells[1].text = droite
        table.rows[1].cells[0].text = "Date et signature :\n\n\n"
        table.rows[1].cells[1].text = "Date et signature :\n\n\n"

    def octets(self) -> bytes:
        sortie = io.BytesIO()
        self.doc.save(sortie)
        return sortie.getvalue()


def _parties(r: Redaction) -> None:
    r.titre("Entre les soussignés", 2)
    r.texte(
        "{{ ville.nom }}, représentée par {{ ville.signataire_nom }} ({{ ville.signataire_qualite }}), ci-après « la Ville »,"
    )
    r.texte(
        "et {{ usager.nom }}{% if usager.sigle %} ({{ usager.sigle }}){% endif %}, {{ usager.type }}, dont le siège est "
        "{{ usager.adresse }}{% if usager.rna %}, RNA {{ usager.rna }}{% endif %}{% if usager.siret %}, SIRET {{ usager.siret }}{% endif %}, "
        "représenté(e) par {{ usager.representant }} ({{ usager.representant_qualite }}), ci-après « l'occupant »."
    )


def _creneaux(r: Redaction) -> None:
    r.tableau(
        ["Équipement", "Site", "Créneau", "Séances"],
        "reservations",
        "r",
        ["{{ r.espace }}", "{{ r.site }}", "{{ r.description }}", "{{ r.nombre_seances }}"],
    )


def convention() -> bytes:
    r = Redaction("Convention de mise à disposition d'équipements")
    r.titre("Convention de mise à disposition d'équipements sportifs et associatifs")
    r.texte("Dossier {{ dossier.numero }} — saison {{ saison }}", gras=True)
    _parties(r)
    r.titre("Article 1 — Objet", 2)
    r.texte(
        "La Ville met à disposition de l'occupant, pour « {{ dossier.objet }} »{% if dossier.activite %} ({{ dossier.activite }}){% endif %}, "
        "les équipements et créneaux suivants :"
    )
    _creneaux(r)
    r.titre("Article 2 — Durée", 2)
    r.texte(
        "La présente convention est conclue pour la saison {{ saison }}, aux dates indiquées ci-dessus. Les séances ne sont pas "
        "assurées pendant les vacances scolaires et les jours fériés, sauf mention contraire, ni pendant les fermetures "
        "exceptionnelles annoncées par la Ville."
    )
    r.titre("Article 3 — Conditions financières", 2)
    r.texte(
        "La mise à disposition est consentie selon la {{ ville.deliberation }}. Lorsqu'elle est gratuite, la Ville en "
        "valorise le montant comme avantage en nature, porté à la connaissance de l'occupant par une attestation annuelle."
    )
    r.titre("Article 4 — Conditions préalables", 2)
    r.texte("L'occupation n'est confirmée qu'une fois réunies les conditions suivantes :")
    r.liste("conditions", "c", "{{ c }}")
    r.titre("Article 5 — Obligations de l'occupant", 2)
    r.texte(
        "L'occupant respecte le règlement intérieur des équipements, l'effectif maximal ({{ dossier.effectif }} personnes "
        "déclarées), les consignes de sécurité et les horaires. Il est assuré pour sa responsabilité civile et signale sans "
        "délai tout incident au gardien ou au service des équipements. Toute absence doit être signalée à l'avance."
    )
    r.titre("Article 6 — Résiliation", 2)
    r.texte(
        "La Ville peut suspendre ou résilier la convention pour motif d'intérêt général ou en cas de manquement de l'occupant, "
        "après mise en demeure restée sans effet, sauf urgence liée à la sécurité."
    )
    r.texte("Fait à Châtillon, le {{ date_edition }}.", droite=True)
    r.signatures("Pour l'occupant\n{{ usager.representant }}", "Pour la Ville\n{{ ville.signataire_nom }}")
    return r.octets()


def contrat_location() -> bytes:
    r = Redaction("Contrat de location de salle")
    r.titre("Contrat de location de salle")
    r.texte("Dossier {{ dossier.numero }}", gras=True)
    _parties(r)
    r.titre("Article 1 — Objet et lieu", 2)
    r.texte("La Ville loue à l'occupant, pour « {{ dossier.objet }} » ({{ dossier.effectif }} personnes au plus) :")
    _creneaux(r)
    r.titre("Article 2 — Prix, acompte et caution", 2)
    r.texte(
        "Montant de la location : {{ montants.total }}. Acompte à verser à la réservation : {{ montants.acompte }}. "
        "Caution : {{ caution.montant }}, restituée après l'état des lieux de sortie, déduction faite des éventuelles "
        "dégradations constatées. Tarifs fixés par la {{ ville.deliberation }}."
    )
    r.titre("Article 3 — Annulation", 2)
    r.texte(
        "Toute annulation est notifiée par écrit ; une annulation tardive peut donner lieu à des frais selon le barème en vigueur."
    )
    r.titre("Article 4 — Conditions préalables", 2)
    r.liste("conditions", "c", "{{ c }}")
    r.titre("Article 5 — Utilisation des lieux", 2)
    r.texte(
        "L'occupant restitue les lieux en bon état et à l'heure prévue ; un état des lieux est établi à l'entrée et à la sortie. "
        "Il respecte la tranquillité du voisinage, la capacité d'accueil et les consignes de sécurité."
    )
    r.texte("Fait à Châtillon, le {{ date_edition }}.", droite=True)
    r.signatures("Le locataire\n{{ usager.representant }}", "Pour la Ville\n{{ ville.signataire_nom }}")
    return r.octets()


def avenant() -> bytes:
    r = Redaction("Avenant")
    r.titre("Avenant au document {{ avenant.numero_origine }}")
    r.texte("Dossier {{ dossier.numero }}", gras=True)
    _parties(r)
    r.titre("Objet de l'avenant", 2)
    r.texte("{{ avenant.motif }}")
    r.titre("Créneaux en vigueur après l'avenant", 2)
    _creneaux(r)
    r.texte("Les autres stipulations du document {{ avenant.numero_origine }} demeurent inchangées.")
    r.texte("Fait à Châtillon, le {{ date_edition }}.", droite=True)
    r.signatures("Pour l'occupant\n{{ usager.representant }}", "Pour la Ville\n{{ ville.signataire_nom }}")
    return r.octets()


def _piece_comptable(titre: str, numero: str, mention: str) -> bytes:
    r = Redaction(titre)
    r.titre(f"{titre} n° {numero}")
    r.texte("Émis le {{ date_edition }} — dossier {{ dossier.numero }}", gras=True)
    r.titre("Destinataire", 2)
    r.texte("{{ usager.nom }}\n{{ usager.adresse }}{% if usager.siret %}\nSIRET {{ usager.siret }}{% endif %}")
    r.titre("Détail", 2)
    r.tableau(
        ["Désignation", "Quantité", "Prix unitaire", "Réduction", "Montant"],
        "lignes",
        "l",
        ["{{ l.libelle }}", "{{ l.quantite }}", "{{ l.prix_unitaire }}", "{{ l.reduction }}", "{{ l.montant }}"],
    )
    r.texte("Total : {{ montants.total }}", gras=True, droite=True)
    r.texte(mention)
    return r.octets()


def devis() -> bytes:
    return _piece_comptable(
        "Devis",
        "{{ piece.numero }}",
        "Devis valable jusqu'au {{ piece.validite }}. Tarifs fixés par la {{ ville.deliberation }}. "
        "L'acceptation du devis vaut engagement de réservation.",
    )


def facture() -> bytes:
    return _piece_comptable(
        "Facture",
        "{{ piece.numero }}",
        "À régler avant le {{ piece.echeance }} par virement au Trésor public (IBAN {{ reglement.iban }}, référence "
        "{{ piece.numero }}){% if reglement.payfip %} ou en ligne sur le portail (PayFiP){% endif %}. Un titre de recettes "
        "exécutoire est émis par la Ville ; il est recouvré par le comptable public.",
    )


def avoir() -> bytes:
    return _piece_comptable(
        "Avoir",
        "{{ piece.numero }}",
        "Avoir émis en correction de la facture {{ piece.facture_origine }} (motif : {{ piece.motif }}). "
        "Il est déduit des sommes dues ou remboursé par le comptable public.",
    )


def etat_des_lieux() -> bytes:
    r = Redaction("État des lieux")
    r.titre("État des lieux — {{ seance.espace }}")
    r.texte("Dossier {{ dossier.numero }} — {{ usager.nom }}", gras=True)
    r.texte("Séance du {{ seance.debut }} au {{ seance.fin }} — {{ seance.site }}")
    r.titre("Constat", 2)
    r.tableau(
        ["Élément", "État à l'entrée", "État à la sortie", "Observations"],
        "materiel",
        "m",
        ["{{ m.libelle }}", "{{ m.entree }}", "{{ m.sortie }}", "{{ m.observations }}"],
    )
    r.texte("Observations générales : ........................................................................")
    r.signatures("L'occupant\n{{ usager.representant }}", "Le gardien\n{{ gardien }}")
    return r.octets()


def attribution() -> bytes:
    r = Redaction("Attribution de créneaux")
    r.texte("{{ usager.nom }}\n{{ usager.adresse }}", droite=True)
    r.texte("Châtillon, le {{ date_edition }}", droite=True)
    r.titre("Attribution de vos créneaux pour la saison {{ saison }}")
    r.texte("Madame, Monsieur,")
    r.texte(
        "Après examen de votre demande {{ dossier.numero }} par la commission, la Ville vous attribue les créneaux suivants :"
    )
    r.liste("attribues", "a", "{{ a }}")
    r.texte("{% if refuses %}Les créneaux suivants n'ont pas pu être retenus :{% endif %}")
    r.liste("refuses", "x", "{{ x.creneau }} — motif : {{ x.motif }}")
    r.texte(
        "La convention de mise à disposition vous sera adressée pour signature. Nous vous prions d'agréer, Madame, "
        "Monsieur, l'expression de nos salutations distinguées."
    )
    r.texte("{{ ville.signataire_nom }}\n{{ ville.signataire_qualite }}", droite=True)
    return r.octets()


def refus() -> bytes:
    r = Redaction("Refus motivé")
    r.texte("{{ usager.nom }}\n{{ usager.adresse }}", droite=True)
    r.texte("Châtillon, le {{ date_edition }}", droite=True)
    r.titre("Votre demande {{ dossier.numero }}")
    r.texte("Madame, Monsieur,")
    r.texte("Nous ne pouvons pas donner une suite favorable à votre demande pour les créneaux suivants :")
    r.liste("refuses", "x", "{{ x.creneau }} — motif : {{ x.motif }}")
    r.texte(
        "Vous pouvez contester cette décision par un recours gracieux auprès du Maire dans un délai de deux mois, ou par un "
        "recours contentieux devant le tribunal administratif de Cergy-Pontoise dans le même délai."
    )
    r.texte("{{ ville.signataire_nom }}\n{{ ville.signataire_qualite }}", droite=True)
    return r.octets()


def attestation_valorisation() -> bytes:
    r = Redaction("Attestation de valorisation des avantages en nature")
    r.titre("Attestation de valorisation des avantages en nature — exercice {{ exercice }}")
    r.texte(
        "{{ ville.nom }} atteste avoir mis gratuitement ou à tarif réduit à la disposition de {{ usager.nom }} "
        "({{ usager.rna }}) les équipements suivants au cours de l'exercice {{ exercice }} :"
    )
    r.tableau(
        ["Équipement", "Heures", "Tarif de référence", "Montant payé", "Valorisation"],
        "lignes",
        "l",
        ["{{ l.espace }}", "{{ l.heures }}", "{{ l.tarif_reference }}", "{{ l.paye }}", "{{ l.valorisation }}"],
    )
    r.texte("Valorisation totale : {{ total }}", gras=True, droite=True)
    r.texte(
        "Cette valorisation constitue une subvention en nature à faire figurer dans les comptes de l'association "
        "(comptes 86 et 87) et, le cas échéant, dans le compte rendu financier prévu par la loi du 12 avril 2000."
    )
    r.texte("Méthode : {{ methode }}")
    r.texte("Fait à Châtillon, le {{ date_edition }}.", droite=True)
    r.texte("{{ ville.signataire_nom }}\n{{ ville.signataire_qualite }}", droite=True)
    return r.octets()


def fermeture() -> bytes:
    r = Redaction("Avis de fermeture exceptionnelle")
    r.titre("Fermeture exceptionnelle : {{ fermeture.lieu }}")
    r.texte("{{ usager.nom }}", gras=True)
    r.texte(
        "Nous vous informons que {{ fermeture.lieu }} sera fermé du {{ fermeture.debut }} au {{ fermeture.fin }} "
        "pour le motif suivant : {{ fermeture.motif }}."
    )
    r.texte("Vos séances concernées :")
    r.liste("seances", "s", "{{ s }}")
    r.texte("Le service des équipements vous contactera pour vous proposer une solution de remplacement.")
    r.texte("{{ ville.service }}", droite=True)
    return r.octets()


MODELES_INITIAUX: list[ModeleInitial] = [
    ModeleInitial(
        "convention",
        "Convention de mise à disposition",
        "convention",
        True,
        ("usager", "elu"),
        "Créneaux annuels et occupations régulières des associations et écoles.",
        convention,
    ),
    ModeleInitial(
        "contrat-location",
        "Contrat de location de salle",
        "contrat_location",
        True,
        ("usager", "elu"),
        "Locations ponctuelles (fêtes, réunions) avec acompte et caution.",
        contrat_location,
    ),
    ModeleInitial("avenant", "Avenant", "avenant", True, ("usager", "elu"), "Modification d'un document signé (RG-13).", avenant),
    ModeleInitial("devis", "Devis", "devis", False, (), "Estimation d'une location.", devis),
    ModeleInitial(
        "facture", "Facture", "facture", False, (), "Facture d'occupation (titre de recettes émis par la Ville).", facture
    ),
    ModeleInitial("avoir", "Avoir", "avoir", False, (), "Correction d'une facture émise.", avoir),
    ModeleInitial(
        "etat-des-lieux",
        "État des lieux",
        "etat_des_lieux",
        True,
        ("usager", "agent"),
        "Entrée et sortie d'une location.",
        etat_des_lieux,
    ),
    ModeleInitial(
        "attribution",
        "Courrier d'attribution de créneaux",
        "attribution",
        False,
        (),
        "Décision de la commission annuelle.",
        attribution,
    ),
    ModeleInitial("refus", "Courrier de refus motivé", "refus", False, (), "Refus avec voies et délais de recours.", refus),
    ModeleInitial(
        "attestation-valorisation",
        "Attestation de valorisation",
        "attestation_valorisation",
        False,
        (),
        "Avantages en nature annuels d'une association (VAL-04).",
        attestation_valorisation,
    ),
    ModeleInitial(
        "fermeture", "Avis de fermeture exceptionnelle", "fermeture", False, (), "Information des usagers touchés.", fermeture
    ),
]
