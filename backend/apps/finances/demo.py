"""Jeu de démonstration, lot 3 : grille votée 2026-2027, gratuités fondées, devis, acomptes, factures, cautions.

Les montants sont fictifs (ordre de grandeur des tarifs municipaux d'Île-de-France) ; la délibération citée est
une référence de démonstration. Enregistré dans `apps.noyau.demo.socle.EXTENSIONS`.
"""

from __future__ import annotations

from datetime import date, time
from typing import Any

from django.utils import timezone

from apps.noyau.exceptions import ErreurMetier
from apps.referentiel.models import FamilleEspace
from apps.reservations.models import Reservation

from . import cautions, facturation, titres
from .models import GrilleTarifaire, Majoration, Prestation, Reduction, Tarif

SYSTEME = "système"
DELIBERATION = "DCM-DEMO-2025-12-15-07"

# Prix horaires de référence en centimes, par famille et catégorie ; caution par famille.
PRIX: dict[str, dict[str, int]] = {
    "gymnase": {
        "association_locale": 1500,
        "association": 2500,
        "ecole": 1500,
        "entreprise": 6000,
        "particulier": 4000,
        "service_municipal": 1500,
        "autre_collectivite": 3000,
    },
    "dojo": {
        "association_locale": 1000,
        "association": 1800,
        "ecole": 1000,
        "entreprise": 4000,
        "particulier": 3000,
        "service_municipal": 1000,
        "autre_collectivite": 2000,
    },
    "salle-sport": {
        "association_locale": 1000,
        "association": 1800,
        "ecole": 1000,
        "entreprise": 4000,
        "particulier": 3000,
        "service_municipal": 1000,
        "autre_collectivite": 2000,
    },
    "terrain-exterieur": {
        "association_locale": 2000,
        "association": 3500,
        "ecole": 2000,
        "entreprise": 8000,
        "particulier": 5000,
        "service_municipal": 2000,
        "autre_collectivite": 4000,
    },
    "salle-fetes": {
        "association_locale": 2500,
        "association": 4500,
        "ecole": 2500,
        "entreprise": 9000,
        "particulier": 4500,
        "service_municipal": 2500,
        "autre_collectivite": 6000,
    },
    "salle-reunion": {
        "association_locale": 500,
        "association": 1200,
        "ecole": 500,
        "entreprise": 3000,
        "particulier": 1500,
        "service_municipal": 500,
        "autre_collectivite": 1500,
    },
    "salle-associative": {
        "association_locale": 500,
        "association": 1200,
        "ecole": 500,
        "entreprise": 3000,
        "particulier": 1500,
        "service_municipal": 500,
        "autre_collectivite": 1500,
    },
    "piste-athletisme": {
        "association_locale": 1500,
        "association": 2500,
        "ecole": 1500,
        "entreprise": 6000,
        "particulier": 4000,
        "service_municipal": 1500,
        "autre_collectivite": 3000,
    },
    "salle-spectacle": {
        "association_locale": 3000,
        "association": 6000,
        "ecole": 3000,
        "entreprise": 12000,
        "particulier": 7000,
        "service_municipal": 3000,
        "autre_collectivite": 8000,
    },
}
CAUTIONS = {"salle-fetes": 50000, "salle-spectacle": 80000, "gymnase": 30000, "terrain-exterieur": 30000}


def grille() -> GrilleTarifaire:
    g = GrilleTarifaire.objects.create(
        nom="Tarifs 2026-2027",
        debut=date(2026, 1, 1),
        statut="votee",
        deliberation_reference=DELIBERATION,
        deliberation_date=date(2025, 12, 15),
        heure_soiree=time(20, 0),
    )
    for famille in FamilleEspace.objects.filter(code__in=PRIX):
        for categorie, prix in PRIX[famille.code].items():
            Tarif.objects.create(
                grille=g,
                famille=famille,
                categorie=categorie,
                unite="heure",
                prix_centimes=prix,
                caution_centimes=CAUTIONS.get(famille.code, 0)
                if categorie in {"particulier", "entreprise", "association"}
                else 0,
            )
    Majoration.objects.create(grille=g, nature="week_end", taux=2500, categories=["particulier", "entreprise"])
    Majoration.objects.create(grille=g, nature="soiree", taux=2000, categories=["particulier", "entreprise"])
    Majoration.objects.create(grille=g, nature="ferie", taux=5000, categories=["particulier", "entreprise"])
    Majoration.objects.create(grille=g, nature="non_resident", taux=5000, categories=["particulier"])
    Prestation.objects.create(
        grille=g, code="menage", libelle="Ménage après la manifestation", unite="forfait", prix_centimes=12000
    )
    Prestation.objects.create(
        grille=g, code="sonorisation", libelle="Sonorisation et éclairage", unite="forfait", prix_centimes=8000
    )
    return g


def reductions(usagers: dict[str, list[Any]]) -> int:
    nombre = 0
    for association in usagers["association"]:
        if association.local and association.conventionne:
            Reduction.objects.create(
                usager=association,
                taux=10000,
                fondement=f"{DELIBERATION} — gratuité des créneaux des associations conventionnées ({association.convention_reference})",
                debut=date(2026, 9, 1),
                fin=date(2027, 8, 31),
            )
            nombre += 1
        elif association.local:
            Reduction.objects.create(
                usager=association,
                taux=5000,
                fondement=f"{DELIBERATION} — demi-tarif des associations de la commune",
                debut=date(2026, 9, 1),
            )
            nombre += 1
    for usager in (*usagers["ecole"], *usagers["service_municipal"]):
        Reduction.objects.create(
            usager=usager, taux=10000, fondement=f"{DELIBERATION} — mise à disposition gratuite", debut=date(2026, 9, 1)
        )
        nombre += 1
    return nombre


def _chiffrable(reservation: Reservation) -> bool:
    """Le jeu ne chiffre que les réservations couvertes par la grille (une réservation saisie en recette peut ne pas l'être)."""
    from .tarification import categorie, tarif_de_reference

    try:
        tarif_de_reference(reservation.espace, categorie(reservation.dossier.usager), reservation.date_debut)
    except ErreurMetier:
        return False
    return True


def charger(resultat: dict[str, Any]) -> dict[str, int]:
    if GrilleTarifaire.objects.filter(deliberation_reference=DELIBERATION).exists():
        return {}
    bilan = {"grilles_tarifaires": 1}
    grille()
    bilan["reductions"] = reductions(resultat["usagers"])
    devis = factures = cautions_recues = 0
    locations = Reservation.objects.filter(
        dossier__type_reservation__code="location", statut__in=["validee", "confirmee"]
    ).select_related("dossier__usager", "espace")
    for i, reservation in enumerate(locations):
        if not _chiffrable(reservation):
            continue
        cautions.preparer(reservation)
        piece = facturation.etablir_devis(reservation.dossier, acteur=SYSTEME, prestations=[{"code": "menage"}] if i % 2 else [])
        devis += 1
        if reservation.statut == "confirmee":
            facturation.accepter_devis(piece, acteur=SYSTEME)
            acompte = facturation.facturer_acompte(reservation.dossier, acteur=SYSTEME)
            facturation.enregistrer_encaissement(
                acompte, montant=acompte.total_du, jour=timezone.localdate(), reference=f"VIR DEMO {i:04d}", origine="pointage"
            )
            caution = reservation.cautions.first()
            if caution is not None:
                cautions.recevoir(caution, acteur=SYSTEME, mode="cheque", reference=f"Chèque de démonstration {i:04d}")
                cautions_recues += 1
    entreprises = Reservation.objects.filter(dossier__usager__type="entreprise", statut="validee").select_related("dossier")
    emises = []
    for reservation in entreprises:
        if not _chiffrable(reservation):
            continue
        emises.append(facturation.facturer(reservation.dossier, acteur=SYSTEME))
        factures += 1
    if emises:
        titres.exporter(emises[:1], acteur=SYSTEME)
        bilan["lots_titres"] = 1
    bilan.update({"devis": devis, "factures": factures, "cautions_recues": cautions_recues})
    return bilan
