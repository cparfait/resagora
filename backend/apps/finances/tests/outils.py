"""Aides de test des finances : grille votée, tarifs et réservation à facturer (montants en centimes)."""

from __future__ import annotations

from datetime import date, time

from apps.finances.models import GrilleTarifaire, Majoration, Prestation, Tarif
from apps.referentiel.models import Espace
from apps.reservations.tests.outils import reserver, valider_systeme
from apps.usagers.models import Usager
from tests.fabriques import EspaceFabrique, usager_avec_contact

PDF = b"%PDF-1.7\n% piece comptable <pdfaid:part>2</pdfaid:part>\n%%EOF\n"


def grille_votee(
    espace: Espace, *, prix: int = 4000, caution: int = 30000, debut: date = date(2026, 1, 1), nom: str = "Tarifs 2026"
) -> GrilleTarifaire:
    """Grille votée : 40 € de l'heure (association locale 20 €, particulier 40 €), caution 300 €, majorations."""
    grille = GrilleTarifaire.objects.create(
        nom=nom,
        debut=debut,
        statut="votee",
        deliberation_reference="DCM-2025-12-15-07",
        deliberation_date=date(2025, 12, 15),
        heure_soiree=time(20, 0),
    )
    for categorie, montant in {
        "association_locale": prix // 2,
        "association": prix,
        "particulier": prix,
        "entreprise": prix * 2,
        "ecole": prix // 2,
        "service_municipal": prix // 2,
        "autre_collectivite": prix,
    }.items():
        Tarif.objects.create(
            grille=grille, espace=espace, categorie=categorie, unite="heure", prix_centimes=montant, caution_centimes=caution
        )
    Majoration.objects.create(grille=grille, nature="week_end", taux=2500, categories=["particulier", "entreprise"])
    Majoration.objects.create(grille=grille, nature="non_resident", taux=5000)
    Prestation.objects.create(
        grille=grille, code="menage", libelle="Ménage après la manifestation", unite="forfait", prix_centimes=12000
    )
    return grille


def location(
    *,
    usager: Usager | None = None,
    jour: date = date(2026, 12, 9),
    debut: str = "14:00",
    fin: str = "18:00",
    espace: Espace | None = None,
    valider: bool = True,
):
    """Location un mercredi (type « location » : devis, acompte, convention et caution exigés), particulier résident."""
    espace = espace or EspaceFabrique(nom="Salle polyvalente")
    usager = usager or usager_avec_contact(type="particulier", nom="Particulier de test", commune="Châtillon")
    reservation = reserver(espace, jour, debut, fin, usager=usager, type_code="location")
    return valider_systeme(reservation) if valider else reservation
