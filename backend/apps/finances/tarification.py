"""Calcul des montants (TAR-01 à TAR-03, RG-04, RG-05).

montant_reference = quantité × tarif(espace, catégorie, unité, date) + majorations (week-end, soirée, férié,
non-résident) + prestations ; montant_du = montant_reference × (1 − taux de réduction). Le tarif appliqué est
celui de la grille votée en vigueur à la date d'occupation ; un devis accepté le fige (RG-04).
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, time
from typing import Any

from django.db.models import Q
from django.utils import timezone

from apps.noyau.exceptions import ErreurMetier, ErreurValidation
from apps.noyau.montants import appliquer_taux, euros, proratiser
from apps.referentiel.models import Espace
from apps.reservations.recurrence import PARIS
from apps.usagers.models import Usager

from .models import GrilleTarifaire, Majoration, Reduction, Tarif

MINUTES_PAR_UNITE = {"demi_journee": 240, "journee": 24 * 60}


@dataclass
class LigneCalculee:
    libelle: str
    nature: str
    quantite: int
    unite: str
    prix_unitaire: int
    montant_reference: int
    taux_reduction: int
    montant_du: int
    fondement: str = ""
    tarif: Tarif | None = None
    espace: Espace | None = None
    occurrence_id: int | None = None


def categorie(usager: Usager) -> str:
    if usager.type == "association":
        return "association_locale" if usager.local else "association"
    return usager.type


def grille_en_vigueur(jour: date) -> GrilleTarifaire:
    grille = (
        GrilleTarifaire.objects.filter(statut="votee", debut__lte=jour)
        .filter(Q(fin__isnull=True) | Q(fin__gte=jour))
        .order_by("-debut")
        .first()
    )
    if grille is None:
        raise ErreurMetier(f"Aucune grille tarifaire votée n'est en vigueur le {jour:%d/%m/%Y}.", code="sans_grille")
    return grille


def tarif_de_reference(espace: Espace, cat: str, jour: date) -> Tarif:
    """RG-05 : tarif de l'espace (ou de sa famille) pour la catégorie ; sans tarif, ni facture ni gratuité valorisable."""
    grille = grille_en_vigueur(jour)
    tarif = (
        Tarif.objects.filter(grille=grille, espace=espace, categorie=cat).first()
        or Tarif.objects.filter(grille=grille, famille_id=espace.famille_id, espace__isnull=True, categorie=cat).first()
    )
    if tarif is None:
        raise ErreurMetier(
            f"Aucun tarif de référence pour {espace.nom} ({dict(_categories())[cat]}) dans la grille « {grille.nom} » : "
            "une gratuité ou une réduction ne peut pas être appliquée sans tarif de référence (RG-05).",
            code="sans_tarif_reference",
        )
    return tarif


def _categories() -> list[tuple[str, str]]:
    from .models import CATEGORIES

    return CATEGORIES


def reduction_applicable(usager: Usager, jour: date, type_reservation_id: int | None = None) -> Reduction | None:
    if usager.pk is None:  # usager fictif de la simulation publique : aucune réduction personnelle
        return None
    qs = Reduction.objects.filter(usager=usager, debut__lte=jour).filter(Q(fin__isnull=True) | Q(fin__gte=jour))
    if type_reservation_id is not None:
        qs = qs.filter(Q(type_reservation__isnull=True) | Q(type_reservation_id=type_reservation_id))
    return qs.order_by("-taux").first()


def verifier_reduction(taux: int, fondement: str) -> None:
    """TAR-03 : une réduction (et a fortiori une gratuité) exige un fondement écrit."""
    if not 0 < taux <= 10000:
        raise ErreurValidation("Le taux de réduction est compris entre 0,01 % et 100 %.", code="taux_invalide")
    if len(fondement.strip()) < 5:
        raise ErreurValidation(
            "Indiquez le fondement de la réduction (délibération, convention ou décision) : une gratuité sans fondement est refusée.",
            code="fondement_requis",
        )


def _prix(tarif: Tarif, minutes: int) -> tuple[int, int]:
    """(quantité, montant) selon l'unité du tarif ; l'heure est facturée à la minute, arrondie au centime."""
    if tarif.unite == "heure":
        return minutes, proratiser(tarif.prix_centimes, minutes, 60)
    if tarif.unite == "forfait":
        return 1, tarif.prix_centimes
    unite = MINUTES_PAR_UNITE[tarif.unite]
    nombre = max(1, -(-minutes // unite))
    return nombre, tarif.prix_centimes * nombre


def _majorations(grille: GrilleTarifaire, cat: str, usager: Usager, debut: datetime, fin: datetime) -> list[Majoration]:
    from apps.referentiel.calendrier import est_ferie

    local = timezone.localtime(debut, PARIS)
    local_fin = timezone.localtime(fin, PARIS)
    applicables = []
    for majoration in grille.majorations.all():
        if majoration.categories and cat not in majoration.categories:
            continue
        conditions = {
            "week_end": local.weekday() >= 5,
            "ferie": est_ferie(local.date()),
            "non_resident": not usager.resident,
            "soiree": grille.heure_soiree is not None
            and (local_fin.time() > grille.heure_soiree or local_fin.date() > local.date()),
        }
        if conditions.get(majoration.nature, False):
            applicables.append(majoration)
    return applicables


def calculer_seance(
    *, espace: Espace, usager: Usager, debut: datetime, fin: datetime, type_reservation_id: int | None = None, libelle: str = ""
) -> list[LigneCalculee]:
    """Lignes d'une séance : occupation puis majorations, avec la réduction de l'usager appliquée à chacune."""
    jour = timezone.localtime(debut, PARIS).date()
    cat = categorie(usager)
    tarif = tarif_de_reference(espace, cat, jour)
    minutes = int((fin - debut).total_seconds() // 60)
    quantite, base = _prix(tarif, minutes)
    reduction = reduction_applicable(usager, jour, type_reservation_id)
    taux = reduction.taux if reduction else 0
    fondement = reduction.fondement if reduction else ""
    titre = libelle or f"{espace.nom}, {timezone.localtime(debut, PARIS):%d/%m/%Y %H:%M}–{timezone.localtime(fin, PARIS):%H:%M}"
    lignes = [
        LigneCalculee(
            libelle=titre,
            nature="occupation",
            quantite=quantite,
            unite=tarif.unite,
            prix_unitaire=tarif.prix_centimes,
            montant_reference=base,
            taux_reduction=taux,
            montant_du=base - appliquer_taux(base, taux),
            fondement=fondement,
            tarif=tarif,
            espace=espace,
        )
    ]
    for majoration in _majorations(tarif.grille, cat, usager, debut, fin):
        supplement = appliquer_taux(base, min(majoration.taux, 10000))
        lignes.append(
            LigneCalculee(
                libelle=f"Majoration : {majoration.get_nature_display().lower()} ({majoration.taux / 100:.0f} %)",
                nature="majoration",
                quantite=1,
                unite="forfait",
                prix_unitaire=supplement,
                montant_reference=supplement,
                taux_reduction=taux,
                montant_du=supplement - appliquer_taux(supplement, taux),
                fondement=fondement,
                tarif=tarif,
                espace=espace,
            )
        )
    return lignes


def caution_exigee(espace: Espace, usager: Usager, jour: date) -> int:
    """CAU-01 : montant de caution prévu par la grille pour l'espace et la catégorie (0 si aucun)."""
    try:
        return tarif_de_reference(espace, categorie(usager), jour).caution_centimes
    except ErreurMetier:
        return 0


def simuler(*, espace: Espace, debut: datetime, fin: datetime, categorie_usager: str, resident: bool) -> dict[str, Any]:
    """TAR-11 : estimation publique (sans réduction personnelle), majorations comprises, caution indiquée."""
    fictif = Usager(type="association" if categorie_usager.startswith("association") else categorie_usager, resident=resident)
    fictif.local = categorie_usager == "association_locale"
    lignes = calculer_seance(espace=espace, usager=fictif, debut=debut, fin=fin)
    total = sum(ligne.montant_reference for ligne in lignes)
    caution = lignes[0].tarif.caution_centimes if lignes and lignes[0].tarif else 0
    return {
        "lignes": [
            {"libelle": ligne.libelle, "montant": ligne.montant_reference, "montant_texte": euros(ligne.montant_reference)}
            for ligne in lignes
        ],
        "total": total,
        "total_texte": euros(total),
        "caution": caution,
        "caution_texte": euros(caution),
        "mention": "Estimation indicative selon la grille en vigueur ; le montant définitif figure sur le devis.",
    }


def _debut_fin(jour: date, heure_debut: time, heure_fin: time) -> tuple[datetime, datetime]:
    from apps.reservations.recurrence import plage_locale

    return plage_locale(jour, heure_debut, heure_fin)
