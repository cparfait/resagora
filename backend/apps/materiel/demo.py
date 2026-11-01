"""Jeu de démonstration, lot 5 : le matériel de CityResa (catalogue et stock, à l'Espace Maison Blanche), les prêts
demandés par ses réservations, plus deux scénarios de formation : un retour avec manquants (R5-03) et une panne.
Enregistré dans `socle.EXTENSIONS`."""

from __future__ import annotations

from typing import Any

from django.utils import timezone

from apps.noyau.exceptions import ErreurMetier
from apps.referentiel.models import Site
from apps.reservations.models import Reservation

from . import services
from .models import Materiel, ReservationMateriel, Stock

SYSTEME = services.SYSTEME
SITE_STOCK = "demo-maison-blanche"
UNITES = {"unite": "unité", "jour": "unité", "gratuit": "unité"}


def charger(resultat: dict[str, Any]) -> dict[str, int]:
    d = resultat.get("cityresa")
    if d is None:
        return {}
    bilan: dict[str, int] = {}
    if not Materiel.objects.filter(code=d["materiels"][0]["cle"]).exists():
        bilan = _catalogue_et_stocks(d)
    if not ReservationMateriel.objects.exists():
        bilan["prets_materiel"] = _prets(resultat.get("materiels_demandes", []))
    return bilan


def _catalogue_et_stocks(d: dict[str, Any]) -> dict[str, int]:
    site = Site.objects.get(code=SITE_STOCK)
    for m in d["materiels"]:
        article = Materiel.objects.create(
            code=m["cle"],
            libelle=m["name"],
            nature="mobile",
            description=m.get("description", ""),
            unite=UNITES.get(m["unite"], "unité"),
            valeur_journaliere_centimes=round(m["montant"] * 100),
            reservable=True,
            propose_portail=True,
        )
        services.entrer(article, site, m["stockTotal"], acteur=SYSTEME, motif="Inventaire initial")
    sono = Stock.objects.filter(materiel__code="sono", site=site).first()
    if sono is not None:
        services.signaler_panne(sono, acteur=SYSTEME, description="Micro HF muet, l'enceinte grésille sur batterie")
    return {"materiels": len(d["materiels"]), "stocks": len(d["materiels"])}


def _prets(demandes: list[tuple[Reservation, list[list[Any]]]]) -> int:
    """Le matériel demandé par les réservations de CityResa ; le premier prêt de tables revient avec deux tables
    manquantes (R5-03)."""
    prets, manquants_poses = 0, False
    for reservation, articles in demandes:
        seance = (
            reservation.occurrences.filter(debut__gte=timezone.now())
            .exclude(statut__in=["annulee", "refusee"])
            .order_by("debut")
            .first()
            or reservation.occurrences.exclude(statut__in=["annulee", "refusee"]).order_by("-debut").first()
        )
        if seance is None:
            continue
        for code, quantite in articles:
            stock = Stock.objects.filter(materiel__code=code, site__code=SITE_STOCK).first()
            if stock is None:
                continue
            try:
                pret = services.reserver(reservation.dossier, stock, quantite, acteur=SYSTEME, occurrence=seance)
            except ErreurMetier:
                continue
            prets += 1
            if code == "tables" and quantite > 2 and pret.statut == "validee" and not manquants_poses:
                services.sortir(pret, acteur=SYSTEME)
                services.rendre(pret, acteur=SYSTEME, quantite=quantite - 2, observations="Deux tables non rapportées")
                manquants_poses = True
    return prets
