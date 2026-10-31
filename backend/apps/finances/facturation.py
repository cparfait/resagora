"""Devis, factures, acomptes, avoirs, frais d'annulation, encaissements et retards (TAR-04 à TAR-13, RG-04, RG-08).

- Numérotation chronologique sans trou par exercice et par nature (compteur verrouillé dans la transaction).
- Une pièce émise ne change plus (déclencheur de base, RG-13) ; seule sa situation de paiement évolue.
- Le devis accepté fige les montants (RG-04) : la facture reprend ses lignes, quelle que soit la grille ensuite.
- Le passage à « soldée » ne vient que d'un encaissement constaté (import Ciril ou pointage de la régie).
"""

from __future__ import annotations

from collections.abc import Iterable
from datetime import date, timedelta
from typing import Any

from django.db import transaction
from django.db.models import QuerySet
from django.utils import timezone

from apps.audit.services import journaliser
from apps.communication.services import notifier
from apps.habilitations.models import Utilisateur
from apps.habilitations.services import exiger
from apps.noyau.exceptions import AccesRefuse, ErreurMetier, ErreurValidation
from apps.noyau.montants import appliquer_taux, euros
from apps.noyau.numerotation import numero
from apps.noyau.parametres import parametre
from apps.reservations.models import Dossier, Occurrence, Reservation
from apps.reservations.recurrence import PARIS

from .models import AFacturer, Encaissement, LigneComptable, PieceComptable
from .tarification import LigneCalculee, calculer_seance

PREFIXES = {"devis": "DV", "acompte": "FA", "facture": "F", "avoir": "AV"}
STATUTS_FACTURES_OUVERTES = {"a_titrer", "titre_emis", "solde_partiel", "en_recouvrement"}


def _controler(acteur: Any, action: str, objet: Any) -> None:
    if acteur == "système":
        return
    if isinstance(acteur, Utilisateur):
        exiger(acteur, action, objet)
        return
    raise AccesRefuse("Vous n'avez pas les droits pour cette action.", code="droits_insuffisants")


def lignes_du_dossier(dossier: Dossier, occurrences: Iterable[Occurrence] | None = None) -> list[LigneCalculee]:
    """Lignes calculées pour les séances actives du dossier (ou celles fournies) au tarif en vigueur à leur date."""
    seances = (
        list(occurrences)
        if occurrences is not None
        else list(
            Occurrence.objects.filter(reservation__dossier=dossier)
            .exclude(statut__in=["annulee", "refusee"])
            .select_related("espace__famille", "reservation")
            .order_by("debut")
        )
    )
    lignes: list[LigneCalculee] = []
    for occurrence in seances:
        for ligne in calculer_seance(
            espace=occurrence.espace,
            usager=dossier.usager,
            debut=occurrence.debut,
            fin=occurrence.fin,
            type_reservation_id=dossier.type_reservation_id,
        ):
            ligne.occurrence_id = occurrence.pk
            lignes.append(ligne)
    return lignes


def _ecrire_lignes(piece: PieceComptable, lignes: Iterable[LigneCalculee | LigneComptable | AFacturer], signe: int = 1) -> None:
    total_reference = total_du = 0
    for rang, ligne in enumerate(lignes, start=1):
        if isinstance(ligne, AFacturer):
            valeurs: dict[str, Any] = {
                "libelle": ligne.libelle,
                "nature": ligne.nature,
                "quantite": 1,
                "unite": "forfait",
                "prix_unitaire": ligne.montant_reference,
                "montant_reference": ligne.montant_reference,
                "taux_reduction": ligne.taux_reduction,
                "montant_du": ligne.montant_du,
                "fondement": ligne.fondement,
                "occurrence_id": ligne.occurrence_id,
                "espace_id": None,
                "tarif_id": None,
            }
        else:
            valeurs = {
                "libelle": ligne.libelle,
                "nature": ligne.nature,
                "quantite": ligne.quantite,
                "unite": ligne.unite,
                "prix_unitaire": ligne.prix_unitaire,
                "montant_reference": ligne.montant_reference,
                "taux_reduction": ligne.taux_reduction,
                "montant_du": ligne.montant_du,
                "fondement": ligne.fondement,
                "occurrence_id": ligne.occurrence_id,
                "espace_id": ligne.espace.pk
                if isinstance(ligne, LigneCalculee) and ligne.espace
                else getattr(ligne, "espace_id", None),
                "tarif_id": ligne.tarif.pk
                if isinstance(ligne, LigneCalculee) and ligne.tarif
                else getattr(ligne, "tarif_id", None),
            }
        valeurs["montant_reference"] *= signe
        valeurs["montant_du"] *= signe
        valeurs["prix_unitaire"] *= signe
        LigneComptable.objects.create(piece=piece, rang=rang, **valeurs)
        total_reference += valeurs["montant_reference"]
        total_du += valeurs["montant_du"]
    piece.total_reference, piece.total_du = total_reference, total_du


def _emettre(piece: PieceComptable, acteur: Any) -> PieceComptable:
    """Attribue le numéro définitif (sans trou) et la date d'émission, puis produit le PDF."""
    aujourd_hui = timezone.localdate()
    piece.exercice = aujourd_hui.year
    piece.numero = numero(PREFIXES[piece.nature], piece.exercice)
    piece.emise_le = aujourd_hui
    piece.emise_par = acteur if isinstance(acteur, Utilisateur) else None
    if piece.nature == "devis":
        piece.statut = "emis"
        piece.validite = aujourd_hui + timedelta(days=int(parametre("devis.validite_jours")))
    else:
        piece.statut = "a_titrer" if piece.total_du > 0 else "solde"
        piece.echeance = aujourd_hui + timedelta(days=int(parametre("factures.echeance_jours")))
        piece.reference_virement = piece.numero.replace("-", "")
    piece.save()
    _produire_pdf(piece, acteur)
    journaliser(f"emettre_{piece.nature}", piece, apres={"numero": piece.numero, "total_du": piece.total_du}, acteur=acteur)
    return piece


def _produire_pdf(piece: PieceComptable, acteur: Any) -> None:
    from apps.documents.models import ModeleDocument
    from apps.documents.services import generer

    code = {"devis": "devis", "acompte": "facture", "facture": "facture", "avoir": "avoir"}[piece.nature]
    modele = ModeleDocument.objects.filter(code=code, actif=True, version_active__isnull=False).first()
    if modele is None:
        raise ErreurMetier(f"Le modèle de document « {code} » n'a pas de version active.", code="modele_inactif")
    document = generer(modele, piece, acteur=acteur, controle_droits=False)
    PieceComptable.objects.filter(pk=piece.pk).update(document=document)
    piece.document = document


@transaction.atomic
def etablir_devis(dossier: Dossier, *, acteur: Any, prestations: list[dict[str, Any]] | None = None) -> PieceComptable:
    """TAR-04 : devis des séances du dossier au tarif en vigueur, prestations annexes comprises."""
    _controler(acteur, "emettre_facture", dossier)
    lignes = lignes_du_dossier(dossier)
    lignes += _lignes_prestations(dossier, prestations or [])
    if not lignes:
        raise ErreurMetier("Aucune séance à chiffrer dans ce dossier.", code="rien_a_facturer")
    piece = PieceComptable.objects.create(nature="devis", dossier=dossier, usager=dossier.usager, objet=dossier.objet)
    _ecrire_lignes(piece, lignes)
    _emettre(piece, acteur)
    notifier(
        "devis_emis", {"piece": piece, "dossier": dossier, "montant": euros(piece.total_du)}, usager=dossier.usager, objet=piece
    )
    return piece


def _lignes_prestations(dossier: Dossier, prestations: list[dict[str, Any]]) -> list[LigneCalculee]:
    from .models import Prestation
    from .tarification import grille_en_vigueur, reduction_applicable

    if not prestations:
        return []
    premiere = dossier.reservations.order_by("date_debut").first()
    jour = premiere.date_debut if premiere else timezone.localdate()
    grille = grille_en_vigueur(jour)
    reduction = reduction_applicable(dossier.usager, jour, dossier.type_reservation_id)
    taux = reduction.taux if reduction else 0
    lignes = []
    for demande in prestations:
        prestation = Prestation.objects.filter(grille=grille, code=demande.get("code")).first()
        if prestation is None:
            raise ErreurValidation(
                f"Prestation inconnue dans la grille en vigueur : {demande.get('code')}.", code="prestation_inconnue"
            )
        quantite = max(1, int(demande.get("quantite", 1)))
        montant = prestation.prix_centimes * quantite
        lignes.append(
            LigneCalculee(
                libelle=prestation.libelle,
                nature="prestation",
                quantite=quantite,
                unite=prestation.unite,
                prix_unitaire=prestation.prix_centimes,
                montant_reference=montant,
                taux_reduction=taux,
                montant_du=montant - appliquer_taux(montant, taux),
                fondement=reduction.fondement if reduction else "",
            )
        )
    return lignes


@transaction.atomic
def accepter_devis(devis: PieceComptable, *, acteur: Any, portail: bool = False) -> PieceComptable:
    """Acceptation (par l'usager sur le portail ou par un agent) : les montants du devis sont figés (RG-04)."""
    devis = PieceComptable.objects.select_for_update().get(pk=devis.pk, nature="devis")
    if not portail:
        _controler(acteur, "emettre_facture", devis.dossier)
    if devis.statut != "emis":
        raise ErreurMetier("Ce devis ne peut plus être accepté.", code="statut_devis")
    if devis.validite and devis.validite < timezone.localdate():
        devis.statut = "expire"
        devis.save(update_fields=["statut"])
        raise ErreurMetier("Ce devis a expiré : demandez-en un nouveau.", code="devis_expire")
    devis.statut, devis.accepte_le, devis.accepte_par = "accepte", timezone.now(), str(acteur)[:200]
    devis.save(update_fields=["statut", "accepte_le", "accepte_par"])
    journaliser("accepter_devis", devis, apres={"numero": devis.numero}, acteur=acteur)
    return devis


def devis_accepte(dossier: Dossier) -> PieceComptable | None:
    return PieceComptable.objects.filter(dossier=dossier, nature="devis", statut="accepte").order_by("-accepte_le").first()


@transaction.atomic
def facturer_acompte(dossier: Dossier, *, acteur: Any) -> PieceComptable:
    """TAR-09 : facture d'acompte (taux paramétré) sur le devis accepté, avant confirmation."""
    _controler(acteur, "emettre_facture", dossier)
    if not dossier.type_reservation.exige_acompte:
        raise ErreurMetier("Ce type de réservation n'exige pas d'acompte.", code="acompte_non_exige")
    devis = devis_accepte(dossier)
    if devis is None:
        raise ErreurMetier("L'acompte se calcule sur un devis accepté.", code="devis_requis")
    if PieceComptable.objects.filter(dossier=dossier, nature="acompte").exclude(statut="annulee").exists():
        raise ErreurMetier("Une facture d'acompte existe déjà pour ce dossier.", code="acompte_existant")
    montant = appliquer_taux(devis.total_du, int(parametre("acomptes.taux")))
    piece = PieceComptable.objects.create(
        nature="acompte", dossier=dossier, usager=dossier.usager, objet=f"Acompte — {dossier.objet}", origine=devis
    )
    _ecrire_lignes(
        piece,
        [
            LigneCalculee(
                libelle=f"Acompte de {int(parametre('acomptes.taux')) / 100:.0f} % sur le devis {devis.numero}",
                nature="acompte",
                quantite=1,
                unite="forfait",
                prix_unitaire=montant,
                montant_reference=montant,
                taux_reduction=0,
                montant_du=montant,
            )
        ],
    )
    _emettre(piece, acteur)
    notifier(
        "facture_emise",
        {"piece": piece, "dossier": dossier, "montant": euros(piece.total_du)},
        usager=dossier.usager,
        objet=piece,
    )
    return piece


@transaction.atomic
def facturer(dossier: Dossier, *, acteur: Any, occurrences: Iterable[Occurrence] | None = None) -> PieceComptable:
    """Facture des séances (devis accepté s'il existe, sinon tarif en vigueur à chaque date) et des frais en attente,
    acompte réglé déduit."""
    _controler(acteur, "emettre_facture", dossier)
    devis = devis_accepte(dossier)
    deja = set(
        LigneComptable.objects.filter(piece__dossier=dossier, piece__nature="facture")
        .exclude(piece__statut="annulee")
        .values_list("occurrence_id", flat=True)
    )
    lignes: list[LigneCalculee | LigneComptable | AFacturer]
    if devis is not None and occurrences is None:
        lignes = [ligne for ligne in devis.lignes.all() if ligne.occurrence_id not in deja or ligne.occurrence_id is None]
    else:
        choisies = [o for o in (occurrences or []) if o.pk not in deja] if occurrences is not None else None
        lignes = [ligne for ligne in lignes_du_dossier(dossier, choisies) if ligne.occurrence_id not in deja]
    elements = list(AFacturer.objects.select_for_update().filter(dossier=dossier, facture__isnull=True))
    lignes = [*lignes, *elements]
    if not lignes:
        raise ErreurMetier("Rien à facturer pour ce dossier.", code="rien_a_facturer")
    piece = PieceComptable.objects.create(
        nature="facture", dossier=dossier, usager=dossier.usager, objet=dossier.objet, origine=devis
    )
    _ecrire_lignes(piece, lignes)
    acomptes = PieceComptable.objects.filter(dossier=dossier, nature="acompte", statut="solde")
    piece.acompte_deduit = min(sum(a.total_du for a in acomptes), max(piece.total_du, 0))
    _emettre(piece, acteur)
    AFacturer.objects.filter(pk__in=[e.pk for e in elements]).update(facture=piece)
    if piece.total_du - piece.acompte_deduit <= 0:
        PieceComptable.objects.filter(pk=piece.pk).update(statut="solde", solde_le=timezone.localdate())
        piece.statut = "solde"
    notifier(
        "facture_emise",
        {"piece": piece, "dossier": dossier, "montant": euros(piece.reste_du)},
        usager=dossier.usager,
        objet=piece,
    )
    return piece


@transaction.atomic
def emettre_avoir(facture: PieceComptable, *, acteur: Any, motif: str, lignes: list[int] | None = None) -> PieceComptable:
    """RG-13 : une facture émise ne se modifie pas ; l'avoir annule tout ou partie de ses lignes."""
    facture = PieceComptable.objects.select_for_update().get(pk=facture.pk)
    _controler(acteur, "emettre_avoir", facture.dossier)
    if facture.nature not in {"facture", "acompte"} or facture.statut in {"brouillon", "annulee"}:
        raise ErreurMetier("Seule une facture émise peut faire l'objet d'un avoir.", code="statut_facture")
    if len(motif.strip()) < 5:
        raise ErreurValidation("Indiquez le motif de l'avoir.", code="motif_requis")
    choisies = list(facture.lignes.filter(pk__in=lignes)) if lignes else list(facture.lignes.all())
    if not choisies:
        raise ErreurValidation("Aucune ligne à annuler.", code="lignes_requises")
    deja = sum(-a.total_du for a in facture.derivees.filter(nature="avoir"))
    a_annuler = sum(ligne.montant_du for ligne in choisies)
    if deja + a_annuler > facture.total_du:
        raise ErreurMetier("Le total des avoirs dépasserait le montant de la facture.", code="avoir_excessif")
    avoir = PieceComptable.objects.create(
        nature="avoir",
        dossier=facture.dossier,
        usager=facture.usager,
        objet=f"Avoir sur {facture.numero}",
        origine=facture,
        motif=motif.strip(),
    )
    _ecrire_lignes(avoir, choisies, signe=-1)
    _emettre(avoir, acteur)
    PieceComptable.objects.filter(pk=avoir.pk).update(statut="solde")
    if deja + a_annuler == facture.total_du:
        PieceComptable.objects.filter(pk=facture.pk).update(statut="annulee")
    journaliser("avoir_sur_facture", facture, apres={"avoir": avoir.numero, "montant": a_annuler}, acteur=acteur)
    return avoir


def frais_annulation(occurrence: Occurrence) -> AFacturer | None:
    """RG-08, TAR-08 : frais d'une annulation tardive selon le barème (délai avant la séance → taux)."""
    if not occurrence.annulation_tardive or occurrence.annulee_le is None:
        return None
    heures_avant = max(0, int((occurrence.debut - occurrence.annulee_le).total_seconds() // 3600))
    bareme = sorted(parametre("annulation.bareme"), key=lambda p: p["heures_avant"], reverse=True)
    taux_frais = next((int(p["taux"]) for p in bareme if heures_avant >= int(p["heures_avant"])), 0)
    if taux_frais == 0:
        return None
    dossier = occurrence.reservation.dossier
    lignes = calculer_seance(
        espace=occurrence.espace,
        usager=dossier.usager,
        debut=occurrence.debut,
        fin=occurrence.fin,
        type_reservation_id=dossier.type_reservation_id,
    )
    reference = appliquer_taux(sum(ligne.montant_reference for ligne in lignes), taux_frais)
    du = appliquer_taux(sum(ligne.montant_du for ligne in lignes), taux_frais)
    if du == 0 and reference == 0:
        return None
    local = timezone.localtime(occurrence.debut, PARIS)
    element, _ = AFacturer.objects.get_or_create(
        occurrence=occurrence,
        nature="frais",
        defaults={
            "dossier": dossier,
            "libelle": f"Frais d'annulation tardive ({taux_frais / 100:.0f} %) — séance du {local:%d/%m/%Y %H:%M}",
            "montant_reference": reference,
            "taux_reduction": 0,
            "montant_du": du,
            "fondement": f"Barème d'annulation : annulée {heures_avant} h avant la séance",
        },
    )
    journaliser("frais_annulation", occurrence, apres={"montant": du, "taux": taux_frais}, acteur="système")
    return element


def apres_annulation_tardive(occurrence: Occurrence) -> None:
    try:
        frais_annulation(occurrence)
    except ErreurMetier:
        # Séance sans tarif (usager municipal, scolaire) : pas de frais à facturer.
        return


@transaction.atomic
def pointer(piece: PieceComptable, *, acteur: Any, montant: int, jour: date, reference: str) -> PieceComptable:
    """TAR-13 : pointage manuel par la régie (date et référence obligatoires), jamais sur simple déclaration."""
    piece = PieceComptable.objects.select_for_update().get(pk=piece.pk)
    _controler(acteur, "encaisser", piece.dossier)
    if len(reference.strip()) < 3:
        raise ErreurValidation("Indiquez la référence du règlement (relevé, titre, virement).", code="reference_requise")
    return enregistrer_encaissement(piece, montant=montant, jour=jour, reference=reference, origine="pointage", agent=acteur)


def enregistrer_encaissement(
    piece: PieceComptable, *, montant: int, jour: date, reference: str, origine: str, agent: Any = None, import_lot: Any = None
) -> PieceComptable:
    if piece.nature not in {"facture", "acompte"} or piece.statut in {"brouillon", "annulee", "solde"}:
        raise ErreurMetier(f"La pièce {piece.numero} n'attend pas de règlement.", code="statut_facture")
    if montant <= 0:
        raise ErreurValidation("Le montant encaissé doit être positif.", code="montant_invalide")
    if montant > piece.reste_du:
        raise ErreurMetier(f"Le montant dépasse le reste dû ({euros(piece.reste_du)}).", code="montant_excessif")
    Encaissement.objects.create(
        piece=piece,
        montant=montant,
        date=jour,
        reference=reference.strip()[:100],
        origine=origine,
        import_lot=import_lot,
        agent=agent if isinstance(agent, Utilisateur) else None,
    )
    piece.montant_regle += montant
    if piece.reste_du == 0:
        piece.statut, piece.solde_le = "solde", jour
    else:
        piece.statut = "solde_partiel"
    piece.save(update_fields=["montant_regle", "statut", "solde_le"])
    journaliser(
        "encaissement", piece, apres={"montant": montant, "origine": origine, "reference": reference}, acteur=agent or origine
    )
    return piece


def en_retard(jour: date | None = None) -> QuerySet[PieceComptable]:
    """TAR-10 : factures titrées (ou à titrer) non soldées après l'échéance."""
    jour = jour or timezone.localdate()
    return (
        PieceComptable.objects.filter(nature__in=["facture", "acompte"], statut__in=STATUTS_FACTURES_OUVERTES, echeance__lt=jour)
        .select_related("usager", "dossier")
        .order_by("echeance")
    )


def acompte_manquant(reservation: Reservation) -> str | None:
    """RG-06 « acompte payé » : facture d'acompte soldée (ou devis sans montant dû)."""
    dossier = reservation.dossier
    if PieceComptable.objects.filter(dossier=dossier, nature="acompte", statut="solde").exists():
        return None
    devis = devis_accepte(dossier)
    if devis is not None and devis.total_du == 0:
        return None
    if PieceComptable.objects.filter(dossier=dossier, nature="acompte").exclude(statut="annulee").exists():
        return "régler l'acompte (facture émise, règlement non constaté)"
    return "accepter le devis puis régler l'acompte" if devis is None else "régler l'acompte"
