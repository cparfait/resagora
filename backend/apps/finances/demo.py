"""Jeu de démonstration, lot 3 : grille votée 2026-2027 aux tarifs de CityResa (par espace), gratuités fondées,
devis, acomptes, factures, cautions. La délibération citée est une référence de démonstration. Enregistré dans
`apps.noyau.demo.socle.EXTENSIONS`.
"""

from __future__ import annotations

from datetime import date, time
from typing import Any

from django.utils import timezone

from apps.noyau.exceptions import ErreurMetier
from apps.referentiel.models import Espace
from apps.reservations.models import Reservation

from . import cautions, facturation, titres
from .models import GrilleTarifaire, Majoration, Prestation, Reduction, Tarif

SYSTEME = "système"
DELIBERATION = "DCM-DEMO-2025-12-15-07"

# Tarifs de CityResa (par espace et par profil) → catégories de la plateforme. Les tarifs « particulier extérieur »
# deviennent la majoration « non résident » (CityResa : 1,5 à 2 fois le tarif de la commune, +75 % retenu).
CATEGORIES = {
    "particulier_commune": "particulier",
    "association_commune": "association_locale",
    "association_exterieure": "association",
    "entreprise": "entreprise",
    "service_interne": "service_municipal",
    "collectivite": "autre_collectivite",
}
# Un seul tarif par espace et par catégorie (contrainte du modèle) : l'unité la plus fine disponible.
ORDRE_UNITES = ["heure", "demi_journee", "journee"]
UNITES_PRESTATION = {"forfait": "forfait", "heure": "heure"}
CATEGORIES_CAUTION = {"particulier", "entreprise", "association", "autre_collectivite"}


def _tarifs_espace(tarifs: list[dict[str, Any]]) -> dict[str, tuple[str, int]]:
    """Catégorie → (unité, prix en centimes). RG-05 : un tarif à 0 € de CityResa (associations de la commune,
    services municipaux) garde un prix de référence — celui des associations extérieures, sinon des entreprises — et
    la gratuité devient une réduction de 100 % (voir `reductions`)."""
    par_profil: dict[tuple[str | None, str], int] = {(t["profil"], t["unite"]): round(t["montant"] * 100) for t in tarifs}
    resultat: dict[str, tuple[str, int]] = {}
    for profil, categorie in CATEGORIES.items():
        for unite in ORDRE_UNITES:
            prix = par_profil.get((profil, unite), par_profil.get((None, unite)))
            if prix is None:
                continue
            if prix == 0:
                prix = par_profil.get(("association_exterieure", unite)) or par_profil.get(("entreprise", unite)) or 0
            if prix:
                resultat[categorie] = (unite, prix)
                break
    return resultat


def grille(d: dict[str, Any]) -> GrilleTarifaire:
    g = GrilleTarifaire.objects.create(
        nom="Tarifs 2026-2027",
        debut=date(2026, 1, 1),
        statut="votee",
        deliberation_reference=DELIBERATION,
        deliberation_date=date(2025, 12, 15),
        heure_soiree=time(20, 0),
    )
    espaces = {e.code: e for e in Espace.objects.filter(code__in=[x["cle"] for x in d["espaces"]])}
    for e in d["espaces"]:
        caution = round((e.get("cautionAmount") or 0) * 100)
        for categorie, (unite, prix) in _tarifs_espace(e["tarifs"]).items():
            Tarif.objects.create(
                grille=g,
                espace=espaces[e["cle"]],
                categorie=categorie,
                unite=unite,
                prix_centimes=prix,
                caution_centimes=caution if categorie in CATEGORIES_CAUTION else 0,
            )
    Majoration.objects.create(grille=g, nature="non_resident", taux=7500, categories=["particulier"])
    options = [*d["options"], *(o for e in d["espaces"] for o in e.get("options", []))]
    for o in options:
        unite_prestation = UNITES_PRESTATION.get(o["unite"])
        if unite_prestation is None or not o["montant"]:
            continue  # prix à l'unité (tables) : c'est le matériel prêté
        code = o["cle"].removeprefix("*:").replace(":", "-")
        Prestation.objects.get_or_create(
            grille=g,
            code=code,
            defaults={"libelle": o["label"], "unite": unite_prestation, "prix_centimes": round(o["montant"] * 100)},
        )
    return g


def reductions(usagers: dict[str, list[Any]]) -> int:
    """CityResa met gratuitement ses espaces à disposition des associations de la commune et des services : réduction
    de 100 % sur le tarif de référence (RG-05), qui garde la valorisation des avantages en nature juste."""
    nombre = 0
    for usager in (*(a for a in usagers["association"] if a.local), *usagers["service_municipal"], *usagers.get("ecole", [])):
        Reduction.objects.create(
            usager=usager, taux=10000, fondement=f"{DELIBERATION} — mise à disposition gratuite", debut=date(2026, 1, 1)
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
    d = resultat.get("cityresa")
    if d is None:
        return {}
    bilan = {"grilles_tarifaires": 1}
    grille(d)
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
