"""Devis, factures, acomptes, avoirs, frais d'annulation, encaissements et retards (TAR-04 à TAR-13, RG-04, RG-08).

- Numérotation chronologique sans trou par exercice et par série (compteur verrouillé dans la transaction).
- Une pièce émise ne change plus (déclencheurs de base, RG-13) ; seule sa situation de paiement évolue.
- Le devis accepté fige les montants (RG-04) : la facture reprend ses lignes, quelle que soit la grille ensuite. Un
  dossier modifié après acceptation (séance ajoutée ou déplacée) exige un nouveau devis ; une séance annulée n'est
  pas facturée, ou fait l'objet d'un avoir si elle l'était déjà.
- Chaque ligne de devis n'est facturée qu'une fois ; chaque ligne de facture n'est créditée qu'une fois.
- L'acompte émis est déduit une seule fois, sur les factures successives du dossier.
- Le passage à « soldée » ne vient que d'un encaissement constaté (import Ciril ou pointage de la régie).
"""

from __future__ import annotations

from collections.abc import Callable, Iterable
from datetime import date, timedelta
from typing import Any

from django.db import transaction
from django.db.models import QuerySet, Sum
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
SEANCES_INACTIVES = ("annulee", "refusee")


def _controler(acteur: Any, action: str, objet: Any) -> None:
    if acteur == "système":
        return
    if isinstance(acteur, Utilisateur):
        exiger(acteur, action, objet)
        return
    raise AccesRefuse("Vous n'avez pas les droits pour cette action.", code="droits_insuffisants")


def _verrouiller_dossier(dossier: Dossier) -> Dossier:
    """Une seule émission à la fois par dossier (double clic, deux agents) : pas de double facture."""
    return Dossier.objects.select_for_update().get(pk=dossier.pk)


def lignes_du_dossier(dossier: Dossier, occurrences: Iterable[Occurrence] | None = None) -> list[LigneCalculee]:
    """Lignes calculées pour les séances actives du dossier (ou celles fournies) au tarif en vigueur à leur date."""
    seances = (
        list(occurrences)
        if occurrences is not None
        else list(
            Occurrence.objects.filter(reservation__dossier=dossier)
            .exclude(statut__in=SEANCES_INACTIVES)
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
            ligne.seance_debut, ligne.seance_fin = occurrence.debut, occurrence.fin
            lignes.append(ligne)
    return lignes


Ligne = LigneCalculee | LigneComptable | AFacturer


def _valeurs(ligne: Ligne) -> dict[str, Any]:
    if isinstance(ligne, AFacturer):
        return {
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
    valeurs: dict[str, Any] = {
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
        "seance_debut": ligne.seance_debut,
        "seance_fin": ligne.seance_fin,
    }
    if isinstance(ligne, LigneCalculee):
        valeurs["espace_id"] = ligne.espace.pk if ligne.espace else None
        valeurs["tarif_id"] = ligne.tarif.pk if ligne.tarif else None
    else:
        valeurs["espace_id"], valeurs["tarif_id"] = ligne.espace_id, ligne.tarif_id
    return valeurs


def _ecrire_lignes(piece: PieceComptable, lignes: Iterable[Ligne], *, signe: int = 1, lien: str = "") -> None:
    """`lien` : « devis » (la ligne facture une ligne de devis) ou « origine » (la ligne d'avoir crédite une ligne)."""
    total_reference = total_du = 0
    for rang, ligne in enumerate(lignes, start=1):
        valeurs = _valeurs(ligne)
        valeurs["montant_reference"] *= signe
        valeurs["montant_du"] *= signe
        valeurs["prix_unitaire"] *= signe
        if lien == "devis" and isinstance(ligne, LigneComptable):
            valeurs["ligne_devis"] = ligne
        if lien == "origine" and isinstance(ligne, LigneComptable):
            valeurs["ligne_origine"] = ligne
        LigneComptable.objects.create(piece=piece, rang=rang, **valeurs)
        total_reference += valeurs["montant_reference"]
        total_du += valeurs["montant_du"]
    piece.total_reference, piece.total_du = total_reference, total_du


def _emettre(piece: PieceComptable, acteur: Any) -> PieceComptable:
    """Attribue le numéro définitif (sans trou) et la date d'émission, fige les coordonnées de règlement, produit le PDF."""
    aujourd_hui = timezone.localdate()
    piece.exercice = aujourd_hui.year
    piece.numero = numero(PREFIXES[piece.nature], piece.exercice)
    piece.emise_le = aujourd_hui
    piece.emise_par = acteur if isinstance(acteur, Utilisateur) else None
    if piece.nature == "devis":
        piece.statut = "emis"
        piece.validite = aujourd_hui + timedelta(days=int(parametre("devis.validite_jours")))
    else:
        piece.statut = "a_titrer" if piece.total_du - piece.acompte_deduit > 0 else "solde"
        piece.echeance = aujourd_hui + timedelta(days=int(parametre("factures.echeance_jours")))
        piece.reference_virement = piece.numero.replace("-", "")
        piece.reglement = {
            "titulaire": parametre("comptable.titulaire"),
            "iban": parametre("comptable.iban"),
            "bic": parametre("comptable.bic"),
        }
        if piece.statut == "solde":
            piece.solde_le = aujourd_hui
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


# --- Devis (TAR-04, RG-04) ----------------------------------------------------------------------------------


#: Fournisseurs de prestations automatiques du devis (ex. prêt d'un matériel facturé, lot 5) : dossier → lignes.
SOURCES_PRESTATIONS: list[Callable[[Dossier], list[dict[str, Any]]]] = []


@transaction.atomic
def etablir_devis(dossier: Dossier, *, acteur: Any, prestations: list[dict[str, Any]] | None = None) -> PieceComptable:
    """TAR-04 : devis des séances du dossier au tarif en vigueur, prestations annexes comprises. Un nouveau devis
    remplace les précédents (émis ou acceptés) : seul le plus récent peut être accepté."""
    dossier = _verrouiller_dossier(dossier)
    _controler(acteur, "emettre_facture", dossier)
    if not dossier.reservations.exclude(statut__in=["annulee", "refusee"]).exists():
        raise ErreurMetier("Un devis porte sur les réservations du dossier : le dossier n'en a aucune.", code="rien_a_facturer")
    lignes = lignes_du_dossier(dossier)
    lignes += _lignes_prestations(dossier, [*(prestations or []), *prestations_automatiques(dossier)])
    if not lignes:
        raise ErreurMetier("Aucune séance à chiffrer dans ce dossier.", code="rien_a_facturer")
    anciens = list(PieceComptable.objects.filter(dossier=dossier, nature="devis", statut__in=["emis", "accepte"]))
    piece = PieceComptable.objects.create(nature="devis", dossier=dossier, usager=dossier.usager, objet=dossier.objet)
    _ecrire_lignes(piece, lignes)
    _emettre(piece, acteur)
    for ancien in anciens:
        PieceComptable.objects.filter(pk=ancien.pk).update(statut="remplace")
        journaliser("remplacer_devis", ancien, apres={"par": piece.numero}, acteur=acteur)
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
    seances = {
        o.pk: o
        for o in Occurrence.objects.filter(
            pk__in=[d["occurrence"] for d in prestations if d.get("occurrence")], reservation__dossier=dossier
        )
    }
    for demande in prestations:
        seance = seances.get(demande.get("occurrence") or 0)
        if seance is not None:
            # Prestation d'une séance (prêt de matériel) : tarif à la date de la séance, rattachée pour le suivi.
            jour_seance = timezone.localtime(seance.debut, PARIS).date()
            grille_seance = grille_en_vigueur(jour_seance)
            prestation = Prestation.objects.filter(grille=grille_seance, code=demande.get("code")).first()
        else:
            prestation = Prestation.objects.filter(grille=grille, code=demande.get("code")).first()
        if prestation is None:
            raise ErreurValidation(
                f"Prestation inconnue dans la grille en vigueur : {demande.get('code')}.", code="prestation_inconnue"
            )
        quantite = int(demande.get("quantite", 1))
        if not 1 <= quantite <= 999:
            raise ErreurValidation("Quantité de prestation entre 1 et 999.", code="quantite_invalide")
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
                occurrence_id=seance.pk if seance else None,
                seance_debut=seance.debut if seance else None,
                seance_fin=seance.fin if seance else None,
            )
        )
    return lignes


def prestations_automatiques(dossier: Dossier) -> list[dict[str, Any]]:
    return [ligne for source in SOURCES_PRESTATIONS for ligne in source(dossier)]


def _empreinte_prestations(lignes: Iterable[LigneCalculee | LigneComptable]) -> list[tuple[int | None, str, int]]:
    return sorted((getattr(ligne, "occurrence_id", None), ligne.libelle, int(ligne.quantite)) for ligne in lignes)


@transaction.atomic
def crediter_prestations(occurrence: Occurrence, code: str, *, quantite: int, acteur: Any, motif: str) -> int:
    """Prêt facturé puis annulé (séance maintenue) : avoir sur la ligne de prestation de la séance (TAR-05)."""
    from .models import Prestation
    from .tarification import grille_en_vigueur

    prestation = Prestation.objects.filter(
        grille=grille_en_vigueur(timezone.localtime(occurrence.debut, PARIS).date()), code=code
    ).first()
    if prestation is None:
        return 0
    lignes = list(
        _lignes_deja_facturees()
        .filter(occurrence=occurrence, nature="prestation", libelle=prestation.libelle, quantite=quantite)
        .select_related("piece")[:1]
    )
    for ligne in lignes:
        emettre_avoir(
            ligne.piece, acteur=acteur if isinstance(acteur, Utilisateur) else "système", motif=motif, lignes=[ligne.pk]
        )
    return len(lignes)


def accepter_devis(devis: PieceComptable, *, acteur: Any, portail: bool = False) -> PieceComptable:
    """Acceptation (par l'usager sur le portail ou par un agent) : les montants du devis sont figés (RG-04).
    Un devis remplacé, déjà accepté ou expiré ne s'accepte plus ; l'expiration constatée est enregistrée."""
    expire = False
    with transaction.atomic():
        devis = PieceComptable.objects.select_for_update().get(pk=devis.pk, nature="devis")
        if not portail:
            _controler(acteur, "emettre_facture", devis.dossier)
        if devis.statut != "emis":
            raise ErreurMetier(f"Ce devis ne peut plus être accepté ({devis.get_statut_display().lower()}).", code="statut_devis")
        if devis.validite and devis.validite < timezone.localdate():
            devis.statut = "expire"
            devis.save(update_fields=["statut"])
            expire = True
        else:
            devis.statut, devis.accepte_le, devis.accepte_par = "accepte", timezone.now(), str(acteur)[:200]
            devis.save(update_fields=["statut", "accepte_le", "accepte_par"])
            journaliser("accepter_devis", devis, apres={"numero": devis.numero, "portail": portail}, acteur=acteur)
    if expire:
        raise ErreurMetier("Ce devis a expiré : demandez-en un nouveau.", code="devis_expire")
    return devis


def expirer_devis(jour: date | None = None) -> int:
    """Tâche quotidienne : les devis non acceptés au terme de leur validité passent « expirés »."""
    jour = jour or timezone.localdate()
    return PieceComptable.objects.filter(nature="devis", statut="emis", validite__lt=jour).update(statut="expire")


def devis_accepte(dossier: Dossier) -> PieceComptable | None:
    return PieceComptable.objects.filter(dossier=dossier, nature="devis", statut="accepte").order_by("-accepte_le").first()


def _verifier_devis_a_jour(dossier: Dossier, devis: PieceComptable) -> None:
    """RG-04 : une séance ajoutée ou déplacée depuis l'acceptation n'est pas couverte par les prix figés du devis."""
    chiffrees = {
        ligne.occurrence_id: (ligne.espace_id, ligne.seance_debut, ligne.seance_fin)
        for ligne in devis.lignes.filter(occurrence__isnull=False, nature="occupation")
    }
    for occurrence in Occurrence.objects.filter(reservation__dossier=dossier).exclude(statut__in=SEANCES_INACTIVES):
        if chiffrees.get(occurrence.pk) != (occurrence.espace_id, occurrence.debut, occurrence.fin):
            raise ErreurMetier(
                f"Le dossier a changé depuis l'acceptation du devis {devis.numero} (séance du "
                f"{timezone.localtime(occurrence.debut, PARIS):%d/%m/%Y %H:%M} ajoutée ou déplacée) : établissez un nouveau devis.",
                code="devis_perime",
            )
    # Prestations rattachées aux séances (matériel prêté) : un prêt ajouté, annulé ou modifié périme le devis.
    actuelles = [
        ligne for ligne in _lignes_prestations(dossier, prestations_automatiques(dossier)) if ligne.occurrence_id is not None
    ]
    devisees = [ligne for ligne in devis.lignes.filter(nature="prestation", occurrence__isnull=False)]
    if _empreinte_prestations(actuelles) != _empreinte_prestations(devisees):
        raise ErreurMetier(
            f"Le matériel prêté a changé depuis l'acceptation du devis {devis.numero} : établissez un nouveau devis.",
            code="devis_perime",
        )


# --- Acompte (TAR-09) -------------------------------------------------------------------------------------


@transaction.atomic
def facturer_acompte(dossier: Dossier, *, acteur: Any) -> PieceComptable:
    """TAR-09 : facture d'acompte (taux paramétré) sur le devis accepté, avant confirmation."""
    dossier = _verrouiller_dossier(dossier)
    _controler(acteur, "emettre_facture", dossier)
    if not dossier.type_reservation.exige_acompte:
        raise ErreurMetier("Ce type de réservation n'exige pas d'acompte.", code="acompte_non_exige")
    devis = devis_accepte(dossier)
    if devis is None:
        raise ErreurMetier("L'acompte se calcule sur un devis accepté.", code="devis_requis")
    if PieceComptable.objects.filter(dossier=dossier, nature="acompte").exclude(statut="annulee").exists():
        raise ErreurMetier("Une facture d'acompte existe déjà pour ce dossier.", code="acompte_existant")
    montant = appliquer_taux(devis.total_du, int(parametre("acomptes.taux")))
    if montant <= 0:
        raise ErreurMetier("Le devis ne comporte aucun montant dû : aucun acompte à demander.", code="acompte_nul")
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


def _acompte_disponible(dossier: Dossier) -> int:
    """Acomptes émis (réglés ou non) moins ce qui a déjà été déduit sur les factures non annulées du dossier."""
    acomptes = PieceComptable.objects.filter(dossier=dossier, nature="acompte", numero__isnull=False).exclude(statut="annulee")
    emis = sum(a.total_du - a.montant_avoirs for a in acomptes)
    deja = (
        PieceComptable.objects.filter(dossier=dossier, nature="facture", numero__isnull=False)
        .exclude(statut="annulee")
        .aggregate(total=Sum("acompte_deduit"))["total"]
        or 0
    )
    return max(0, emis - deja)


# --- Facture (TAR-04, TAR-05, RG-04) ------------------------------------------------------------------------


def _lignes_deja_facturees() -> QuerySet[LigneComptable]:
    """Lignes de factures valides qui n'ont pas été créditées par un avoir."""
    return LigneComptable.objects.filter(piece__nature="facture", piece__numero__isnull=False, avoirs__isnull=True).exclude(
        piece__statut="annulee"
    )


@transaction.atomic
def facturer(dossier: Dossier, *, acteur: Any, occurrences: Iterable[Occurrence] | None = None) -> PieceComptable:
    """Facture des séances actives non encore facturées (lignes du devis accepté s'il existe, sinon tarif en vigueur à
    chaque date) et des frais en attente ; acompte disponible déduit une seule fois."""
    dossier = _verrouiller_dossier(dossier)
    _controler(acteur, "emettre_facture", dossier)
    choisies = list(occurrences) if occurrences is not None else None
    if choisies is not None:
        inactives = [o for o in choisies if o.statut in SEANCES_INACTIVES or o.reservation.dossier_id != dossier.pk]
        if inactives:
            raise ErreurValidation("Une séance annulée, refusée ou d'un autre dossier ne se facture pas.", code="seance_inactive")
    devis = devis_accepte(dossier)
    deja = _lignes_deja_facturees().filter(piece__dossier=dossier)
    lignes: list[Ligne]
    if devis is not None:
        _verifier_devis_a_jour(dossier, devis)
        facturees = set(deja.exclude(ligne_devis__isnull=True).values_list("ligne_devis_id", flat=True))
        actives = set(
            Occurrence.objects.filter(reservation__dossier=dossier)
            .exclude(statut__in=SEANCES_INACTIVES)
            .values_list("pk", flat=True)
        )
        identifiants = {o.pk for o in choisies} if choisies is not None else None
        lignes = [
            ligne
            for ligne in devis.lignes.all()
            if ligne.pk not in facturees
            and (ligne.occurrence_id is None or ligne.occurrence_id in actives)
            and (identifiants is None or ligne.occurrence_id in identifiants)
        ]
        lien = "devis"
    else:
        facturees_seances = set(
            deja.exclude(occurrence__isnull=True).exclude(nature="prestation").values_list("occurrence_id", flat=True)
        )
        a_chiffrer = [o for o in choisies if o.pk not in facturees_seances] if choisies is not None else None
        lignes = [ligne for ligne in lignes_du_dossier(dossier, a_chiffrer) if ligne.occurrence_id not in facturees_seances]
        # Sans devis, les prestations des séances (matériel prêté) sont facturées une fois, séance active seulement.
        prestations_facturees = {
            (o, libelle, q)
            for o, libelle, q in deja.filter(nature="prestation").values_list("occurrence_id", "libelle", "quantite")
        }
        actives_seances = set(
            Occurrence.objects.filter(reservation__dossier=dossier)
            .exclude(statut__in=SEANCES_INACTIVES)
            .values_list("pk", flat=True)
        )
        identifiants_choisis = {o.pk for o in choisies} if choisies is not None else None
        for ligne in _lignes_prestations(dossier, prestations_automatiques(dossier)):
            if ligne.occurrence_id is not None and ligne.occurrence_id not in actives_seances:
                continue
            if identifiants_choisis is not None and ligne.occurrence_id not in identifiants_choisis:
                continue
            if (ligne.occurrence_id, ligne.libelle, ligne.quantite) not in prestations_facturees:
                lignes.append(ligne)
        lien = ""
    elements = list(AFacturer.objects.select_for_update().filter(dossier=dossier, facture__isnull=True))
    if not lignes and not elements:
        raise ErreurMetier("Rien à facturer pour ce dossier.", code="rien_a_facturer")
    piece = PieceComptable.objects.create(
        nature="facture", dossier=dossier, usager=dossier.usager, objet=dossier.objet, origine=devis
    )
    _ecrire_lignes(piece, [*lignes, *elements], lien=lien)
    piece.acompte_deduit = min(_acompte_disponible(dossier), max(piece.total_du, 0))
    _emettre(piece, acteur)
    AFacturer.objects.filter(pk__in=[e.pk for e in elements]).update(facture=piece)
    notifier(
        "facture_emise",
        {"piece": piece, "dossier": dossier, "montant": euros(piece.reste_du)},
        usager=dossier.usager,
        objet=piece,
    )
    return piece


# --- Avoir (RG-13, TAR-05) ------------------------------------------------------------------------------


@transaction.atomic
def emettre_avoir(facture: PieceComptable, *, acteur: Any, motif: str, lignes: list[int] | None = None) -> PieceComptable:
    """RG-13 : une facture émise ne se modifie pas ; l'avoir crédite tout ou partie de ses lignes, chacune une seule
    fois, sans dépasser le montant titré (la part réglée par l'acompte se crédite sur la facture d'acompte)."""
    facture = PieceComptable.objects.select_for_update().get(pk=facture.pk)
    _controler(acteur, "emettre_avoir", facture.dossier)
    if facture.nature not in {"facture", "acompte"} or facture.numero is None or facture.statut == "annulee":
        raise ErreurMetier("Seule une facture émise et non annulée peut faire l'objet d'un avoir.", code="statut_facture")
    if len(motif.strip()) < 5:
        raise ErreurValidation("Indiquez le motif de l'avoir.", code="motif_requis")
    disponibles = list(facture.lignes.filter(avoirs__isnull=True).order_by("rang"))
    if lignes:
        inconnues = set(lignes) - {ligne.pk for ligne in facture.lignes.all()}
        if inconnues:
            raise ErreurValidation("Certaines lignes n'appartiennent pas à cette facture.", code="lignes_etrangeres")
        choisies = [ligne for ligne in disponibles if ligne.pk in set(lignes)]
        if len(choisies) != len(set(lignes)):
            raise ErreurMetier("Une ligne choisie a déjà été créditée par un avoir.", code="ligne_deja_creditee")
    else:
        choisies = disponibles
    if not choisies:
        raise ErreurValidation("Aucune ligne à créditer.", code="lignes_requises")
    a_crediter = sum(ligne.montant_du for ligne in choisies)
    toutes = len(choisies) == len(disponibles)
    reprise_acompte = facture.acompte_deduit if toutes and facture.nature == "facture" else 0
    credit = a_crediter - reprise_acompte
    restant = facture.montant_titre - facture.montant_avoirs
    if credit > restant:
        raise ErreurMetier(
            f"L'avoir ({euros(credit)}) dépasserait le montant titré restant ({euros(restant)}) : la part réglée par "
            "l'acompte se crédite sur la facture d'acompte.",
            code="avoir_excessif",
        )
    avoir = PieceComptable.objects.create(
        nature="avoir",
        dossier=facture.dossier,
        usager=facture.usager,
        objet=f"Avoir sur {facture.numero}",
        origine=facture,
        motif=motif.strip(),
    )
    _ecrire_lignes(avoir, choisies, signe=-1, lien="origine")
    if reprise_acompte:
        LigneComptable.objects.create(
            piece=avoir,
            rang=len(choisies) + 1,
            libelle=f"Acompte déjà déduit sur la facture {facture.numero}",
            nature="acompte",
            quantite=1,
            unite="forfait",
            prix_unitaire=reprise_acompte,
            montant_reference=reprise_acompte,
            montant_du=reprise_acompte,
        )
        avoir.total_du += reprise_acompte
        avoir.total_reference += reprise_acompte
    _emettre(avoir, acteur)
    PieceComptable.objects.filter(pk=avoir.pk).update(statut="solde", solde_le=timezone.localdate())
    facture.montant_avoirs += credit
    if toutes:
        facture.statut = "annulee"
    elif facture.reste_du <= 0 and facture.statut != "solde":
        facture.statut, facture.solde_le = "solde", timezone.localdate()
    facture.save(update_fields=["montant_avoirs", "statut", "solde_le"])
    journaliser("avoir_sur_facture", facture, apres={"avoir": avoir.numero, "montant": credit}, acteur=acteur)
    return avoir


# --- Annulations : avoir des séances facturées, frais tardifs (RG-08, TAR-08) ------------------------------


def base_seance(occurrence: Occurrence) -> tuple[int, int, int, str]:
    """(référence, dû, taux de réduction, fondement) de l'occupation d'une séance : lignes d'occupation et de
    majoration du devis accepté (RG-04), sinon tarif en vigueur. Les prestations (matériel) n'en font pas partie."""
    dossier = occurrence.reservation.dossier
    devis = devis_accepte(dossier)
    lignes: list[LigneCalculee] | list[LigneComptable]
    du_devis = devis.lignes.filter(occurrence=occurrence, nature__in=["occupation", "majoration"]) if devis else None
    if du_devis is not None and du_devis.exists():
        lignes = list(du_devis)
    else:
        lignes = calculer_seance(
            espace=occurrence.espace,
            usager=dossier.usager,
            debut=occurrence.debut,
            fin=occurrence.fin,
            type_reservation_id=dossier.type_reservation_id,
        )
    reference = sum(ligne.montant_reference for ligne in lignes)
    du = sum(ligne.montant_du for ligne in lignes)
    return reference, du, (lignes[0].taux_reduction if lignes else 0), (lignes[0].fondement if lignes else "")


def _heures_avant(occurrence: Occurrence) -> int:
    assert occurrence.annulee_le is not None
    return max(0, int((occurrence.debut - occurrence.annulee_le).total_seconds() // 3600))


def taux_frais_annulation(occurrence: Occurrence) -> int:
    """Taux des frais (dix-millièmes) d'une annulation tardive selon le barème ; 0 si l'annulation n'est pas tardive."""
    if not occurrence.annulation_tardive or occurrence.annulee_le is None:
        return 0
    heures_avant = _heures_avant(occurrence)
    bareme = sorted(parametre("annulation.bareme"), key=lambda p: p["heures_avant"], reverse=True)
    return next((int(p["taux"]) for p in bareme if heures_avant >= int(p["heures_avant"])), 0)


def frais_annulation(occurrence: Occurrence) -> AFacturer | None:
    """RG-08, TAR-08 : frais d'une annulation tardive selon le barème (délai avant la séance → taux), calculés sur les
    prix du devis accepté ; la gratuité éventuelle et son fondement sont conservés (valorisation)."""
    taux_frais = taux_frais_annulation(occurrence)
    if taux_frais == 0:
        return None
    reference_seance, du_seance, taux_reduction, fondement = base_seance(occurrence)
    reference = appliquer_taux(reference_seance, taux_frais)
    du = appliquer_taux(du_seance, taux_frais)
    if du == 0 and reference == 0:
        return None
    local = timezone.localtime(occurrence.debut, PARIS)
    element, _ = AFacturer.objects.get_or_create(
        occurrence=occurrence,
        nature="frais",
        defaults={
            "dossier": occurrence.reservation.dossier,
            "libelle": f"Frais d'annulation tardive ({taux_frais / 100:.0f} %) — séance du {local:%d/%m/%Y %H:%M}",
            "montant_reference": reference,
            "taux_reduction": taux_reduction,
            "montant_du": du,
            "fondement": f"Barème d'annulation : annulée {_heures_avant(occurrence)} h avant la séance"
            + (f" ; {fondement}" if fondement else ""),
        },
    )
    journaliser("frais_annulation", occurrence, apres={"montant": du, "taux": taux_frais}, acteur="système")
    return element


def apres_annulation(occurrence: Occurrence) -> None:
    """Séance annulée : si elle était facturée, un avoir crédite ses lignes ; si l'annulation est tardive, les frais
    du barème sont mis en attente de facturation."""
    lignes = list(_lignes_deja_facturees().filter(occurrence=occurrence).select_related("piece"))
    for facture in {ligne.piece for ligne in lignes}:
        try:
            with transaction.atomic():
                emettre_avoir(
                    facture,
                    acteur="système",
                    motif=f"Séance du {timezone.localtime(occurrence.debut, PARIS):%d/%m/%Y %H:%M} annulée",
                    lignes=[ligne.pk for ligne in lignes if ligne.piece_id == facture.pk],
                )
        except ErreurMetier as erreur:
            journaliser("avoir_automatique_impossible", facture, apres={"motif": erreur.message}, acteur="système")
    if occurrence.annulation_tardive:
        try:
            frais_annulation(occurrence)
        except ErreurMetier:
            # Séance sans tarif (usager municipal, scolaire) : pas de frais à facturer.
            return


# --- Encaissements, retards (TAR-10, TAR-13) -------------------------------------------------------------------


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
    elif piece.statut != "en_recouvrement":
        piece.statut = "solde_partiel"
    piece.save(update_fields=["montant_regle", "statut", "solde_le"])
    journaliser(
        "encaissement", piece, apres={"montant": montant, "origine": origine, "reference": reference}, acteur=agent or origine
    )
    return piece


def en_retard(jour: date | None = None) -> QuerySet[PieceComptable]:
    """TAR-10 : factures (titrées ou à titrer) non soldées après l'échéance, avoirs déduits du reste dû."""
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
