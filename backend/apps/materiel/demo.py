"""Jeu de démonstration, lot 5 : catalogue réaliste (mobilier de réception, sonorisation, barnums, équipements fixes
des gymnases soumis à contrôle annuel, consommables), stocks par site, prêts rattachés aux locations, un retour avec
manquants, une panne, un contrôle dépassé. Enregistré dans `socle.EXTENSIONS`."""

from __future__ import annotations

from datetime import timedelta
from typing import Any

from django.utils import timezone

from apps.noyau.exceptions import ErreurMetier
from apps.referentiel.models import Espace, Site
from apps.reservations.models import Reservation

from . import services
from .models import Materiel, ReservationMateriel, Stock

SYSTEME = services.SYSTEME

# (code, libellé, nature, unité, valeur d'une journée en centimes, réservable, portail, contrôle (jours), seuil)
CATALOGUE: list[tuple[str, str, str, str, int, bool, bool, int | None, int | None]] = [
    ("table-pliante", "Table pliante 180 × 75 cm", "mobile", "table", 300, True, True, None, None),
    ("chaise-coque", "Chaise coque empilable", "mobile", "chaise", 50, True, True, None, None),
    ("barnum-3x6", "Barnum 3 × 6 m", "mobile", "barnum", 4000, True, True, 365, None),
    ("sono-mobile", "Sonorisation mobile (2 enceintes, table, micros)", "mobile", "ensemble", 6000, True, True, None, None),
    ("podium", "Podium modulaire 6 × 4 m", "mobile", "ensemble", 15000, True, False, 365, None),
    ("grille-expo", "Grille d'exposition", "mobile", "grille", 200, True, True, None, None),
    ("but-handball", "But de handball (paire)", "fixe", "paire", 2000, False, False, 365, None),
    ("panier-basket", "Panier de basket relevable", "fixe", "panier", 2000, False, False, 365, None),
    ("defibrillateur", "Défibrillateur automatisé externe", "fixe", "appareil", 0, False, False, 365, None),
    ("gobelet-reutilisable", "Gobelet réutilisable", "consommable", "gobelet", 5, True, True, None, 500),
]

# (code du matériel, code du site, code de l'espace ou vide, quantité)
STOCKS: list[tuple[str, str, str, int]] = [
    ("table-pliante", "maison", "", 120),
    ("table-pliante", "centre", "", 60),
    ("chaise-coque", "maison", "", 600),
    ("chaise-coque", "centre", "", 300),
    ("barnum-3x6", "parc", "", 6),
    ("sono-mobile", "maison", "", 2),
    ("podium", "centre", "", 1),
    ("grille-expo", "parc", "", 40),
    ("but-handball", "parc", "parc-gym-a", 2),
    ("but-handball", "centre", "centre-halle", 2),
    ("panier-basket", "parc", "parc-gym-a", 6),
    ("panier-basket", "centre", "centre-gym", 4),
    ("defibrillateur", "parc", "parc-gym-a", 1),
    ("defibrillateur", "centre", "centre-gym", 1),
    ("gobelet-reutilisable", "maison", "", 2000),
]


def charger(resultat: dict[str, Any]) -> dict[str, int]:
    bilan = _catalogue_et_stocks() if not Materiel.objects.filter(code="table-pliante").exists() else {}
    if not ReservationMateriel.objects.exists():
        bilan["prets_materiel"] = _prets()
    return bilan


def _catalogue_et_stocks() -> dict[str, int]:
    articles = {}
    for code, libelle, nature, unite, valeur, reservable, portail, controle, seuil in CATALOGUE:
        articles[code] = Materiel.objects.create(
            code=code,
            libelle=libelle,
            nature=nature,
            unite=unite,
            valeur_journaliere_centimes=valeur,
            reservable=reservable,
            propose_portail=portail,
            periodicite_controle_jours=controle,
            seuil_alerte=seuil,
        )
    sites = {s.code.removeprefix("demo-"): s for s in Site.objects.filter(code__startswith="demo-")}
    stocks = {}
    for code, site, espace, quantite in STOCKS:
        if site not in sites:
            continue
        lieu = Espace.objects.filter(code=espace).select_related("batiment").first() if espace else None
        stocks[(code, site)] = services.entrer(
            articles[code], sites[site], quantite, acteur=SYSTEME, espace=lieu, motif="Inventaire initial"
        )
    aujourd_hui = timezone.localdate()
    # Contrôles annuels : à jour au parc, dépassé au centre (alerte MAT-04).
    for (code, site), stock in stocks.items():
        if articles[code].periodicite_controle_jours:
            realise = aujourd_hui - timedelta(days=400 if site == "centre" else 120)
            services.enregistrer_controle(
                stock, acteur=SYSTEME, realise_le=realise, prestataire="Bureau de contrôle (démonstration)"
            )
    if ("sono-mobile", "maison") in stocks:
        services.signaler_panne(
            stocks[("sono-mobile", "maison")], acteur=SYSTEME, description="Micro sans fil muet, enceinte gauche grésille"
        )
    return {"materiels": len(articles), "stocks": len(stocks)}


def _prets() -> int:
    """Prêts de tables et de chaises sur les locations de la Maison des associations (à défaut, sur ses réservations
    validées à venir) ; le premier revient avec deux tables manquantes (R5-03)."""
    site = Site.objects.filter(code="demo-maison").first()
    tables = Stock.objects.filter(materiel__code="table-pliante", site=site).first()
    chaises = Stock.objects.filter(materiel__code="chaise-coque", site=site).first()
    if site is None or tables is None or chaises is None:
        return 0
    base = Reservation.objects.filter(statut__in=["validee", "confirmee"], espace__batiment__site=site).select_related("dossier")
    candidates = list(base.filter(dossier__type_reservation__code="location")[:4]) or list(
        base.filter(date_debut__gte=timezone.localdate()).order_by("date_debut")[:4]
    )
    prets = 0
    for i, reservation in enumerate(candidates):
        for stock, quantite in ((tables, 15 + 5 * i), (chaises, 80 + 20 * i)):
            try:
                seance = (
                    reservation.occurrences.filter(debut__gte=timezone.now())
                    .exclude(statut__in=["annulee", "refusee"])
                    .order_by("debut")
                    .first()
                    or reservation.occurrences.exclude(statut__in=["annulee", "refusee"]).order_by("-debut").first()
                )
                if seance is None:
                    continue
                pret = services.reserver(reservation.dossier, stock, quantite, acteur=SYSTEME, occurrence=seance)
            except ErreurMetier:
                continue
            prets += 1
            if i == 0 and stock is tables:
                # Retour incomplet : 2 tables manquantes, retirées du stock et signalées (R5-03).
                services.sortir(pret, acteur=SYSTEME)
                services.rendre(pret, acteur=SYSTEME, quantite=quantite - 2, observations="Deux tables non rapportées")
    return prets
