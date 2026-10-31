"""Règles sur les usagers : pièces exigées et alertes d'expiration (USR-03), priorité RG-03, historique (USR-05)."""

from __future__ import annotations

from datetime import date, datetime, time, timedelta
from typing import Any

from django.db import transaction
from django.db.models import Q, QuerySet
from django.utils import timezone

from apps.audit.services import journaliser
from apps.noyau import fichiers
from apps.noyau.exceptions import ErreurValidation
from apps.noyau.parametres import parametre

from .models import PieceJustificative, TypePiece, Usager


def pieces_exigees(usager: Usager) -> QuerySet[TypePiece]:
    return TypePiece.objects.filter(types_usager__contains=[usager.type], obligatoire=True)


def pieces_manquantes(usager: Usager, jour: date) -> list[TypePiece]:
    """Pièces obligatoires absentes, refusées, non vérifiées ou non valides à la date d'occupation."""
    manquantes = []
    for type_piece in pieces_exigees(usager):
        valides = [p for p in usager.pieces.filter(type_piece=type_piece) if p.valide_le(jour)]
        if not valides:
            manquantes.append(type_piece)
    return manquantes


def alertes_expiration(jour: date | None = None) -> QuerySet[PieceJustificative]:
    """Pièces valides qui expirent dans le délai d'alerte ou sont déjà expirées (USR-03, DSH-03)."""
    jour = jour or timezone.localdate()
    limite = jour + timedelta(days=int(parametre("pieces.alerte_jours_avant_expiration")))
    return (
        PieceJustificative.objects.filter(statut="valide", valide_jusqu_au__isnull=False, valide_jusqu_au__lte=limite)
        .exclude(usager__statut="anonymise")
        .select_related("usager", "type_piece")
        .order_by("valide_jusqu_au")
    )


@transaction.atomic
def deposer_piece(
    usager: Usager,
    type_piece: TypePiece,
    nom: str,
    contenu: bytes,
    *,
    acteur: Any,
    portail: bool = False,
    valide_jusqu_au: date | None = None,
    controle_facade: str = "",
    empreinte_facade: str = "",
) -> PieceJustificative:
    if usager.type not in type_piece.types_usager:
        raise ErreurValidation("Cette pièce n'est pas demandée pour ce type d'usager.", code="piece_non_demandee")
    fichier = fichiers.enregistrer(
        nom, contenu, depose_par=str(acteur), controle_facade=controle_facade, empreinte_facade=empreinte_facade
    )
    if valide_jusqu_au is None and type_piece.validite_mois:
        valide_jusqu_au = timezone.localdate() + timedelta(days=30 * type_piece.validite_mois)
    piece = PieceJustificative.objects.create(
        usager=usager,
        type_piece=type_piece,
        fichier=fichier,
        valide_jusqu_au=valide_jusqu_au,
        depose_par_portail=portail,
    )
    journaliser("deposer_piece", piece, apres={"type": type_piece.code, "fichier": fichier.sha256}, acteur=acteur)
    return piece


@transaction.atomic
def verifier_piece(
    piece: PieceJustificative, *, acteur: Any, valide: bool, motif: str = "", valide_jusqu_au: date | None = None
) -> PieceJustificative:
    if not valide and not motif.strip():
        raise ErreurValidation("Indiquez le motif du refus de la pièce.", code="motif_requis")
    piece = PieceJustificative.objects.select_for_update().get(pk=piece.pk)
    piece.statut = "valide" if valide else "refuse"
    piece.motif_refus = "" if valide else motif.strip()
    if valide_jusqu_au is not None:
        piece.valide_jusqu_au = valide_jusqu_au
    piece.verifie_par = acteur
    piece.verifie_le = timezone.now()
    piece.save()
    journaliser("verifier_piece", piece, apres={"statut": piece.statut, "motif": piece.motif_refus}, acteur=acteur)
    return piece


def en_temps_scolaire(debut: datetime) -> bool:
    from apps.referentiel.calendrier import est_ferie, est_vacances

    local = timezone.localtime(debut)
    regle = parametre("temps_scolaire")
    jour = local.date()
    if est_vacances(jour) or est_ferie(jour):
        return False
    heure = local.time()
    debut_scolaire = time.fromisoformat(regle["debut"])
    fin_scolaire = time.fromisoformat(regle["fin"])
    if local.weekday() == 2 and regle.get("mercredi_matin"):
        return debut_scolaire <= heure < time(12, 0)
    return local.weekday() in regle["jours"] and debut_scolaire <= heure < fin_scolaire


def categorie_priorite(usager: Usager, debut: datetime) -> str:
    """Catégorie RG-03 du demandeur pour un créneau donné."""
    if usager.type == "service_municipal":
        return "service_municipal"
    if usager.type == "ecole":
        return "scolaire_temps_scolaire" if en_temps_scolaire(debut) else "autre"
    if usager.type == "association":
        return "association_conventionnee_locale" if usager.local and usager.convention_active(debut.date()) else "association"
    return "autre"


def rang_priorite(usager: Usager, debut: datetime) -> int:
    """0 = plus prioritaire, selon l'ordre paramétré (ADM-02)."""
    ordre: list[str] = list(parametre("priorites.ordre"))
    categorie = categorie_priorite(usager, debut)
    return ordre.index(categorie) if categorie in ordre else len(ordre)


def historique(usager: Usager) -> dict[str, Any]:
    """Dossiers et occupations de l'usager (USR-05)."""
    from apps.reservations.models import Dossier, Occurrence

    dossiers = Dossier.objects.filter(usager=usager).order_by("-cree_le")
    occupations = Occurrence.objects.filter(reservation__dossier__usager=usager)
    return {
        "dossiers": dossiers,
        "occurrences_total": occupations.count(),
        "occurrences_realisees": occupations.filter(statut__in=["realisee", "cloturee"]).count(),
        "occurrences_annulees": occupations.filter(statut="annulee").count(),
        "absences_non_signalees": occupations.filter(presence="absent_non_signale").count(),
    }


def rechercher(qs: QuerySet[Usager], texte: str) -> QuerySet[Usager]:
    texte = texte.strip()[:80]
    if not texte:
        return qs
    return qs.filter(
        Q(nom__unaccent__icontains=texte)
        | Q(sigle__icontains=texte)
        | Q(siret__startswith=texte)
        | Q(rna__iexact=texte)
        | Q(rattachements__contact__nom__unaccent__icontains=texte)
        | Q(rattachements__contact__courriel__iexact=texte)
    ).distinct()
