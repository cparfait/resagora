"""Calcul de la valorisation des avantages en nature (VAL-01 à VAL-08), selon le skill `valorisation-subventions` :

    V = Σ séances ((montant de référence − montant payé) × part d'occupation)
      + Σ prêts de matériel (quantité × journées × valeur journalière − montant payé pour ce prêt)
      + Σ personnel dédié (minutes de gardiennage × part × coût horaire chargé de l'exercice)

Base (VAL-03, RG-12) : séances réalisées, validées ou confirmées, séances annulées hors délai et absences non signalées
(paramètre de l'exercice) ; une absence signalée et une annulation dans les délais ne sont pas valorisées. Le montant
de référence est celui du devis accepté (RG-04), sinon du tarif voté conservé (RG-05) : un tarif manquant bloque le
calcul. Le montant payé est ce qui a été facturé pour la séance, avoirs déduits, frais d'annulation compris. Une
réduction partielle ne valorise que l'écart. Montants en centimes, arrondis au plus proche (demi-centime au-dessus)."""

from __future__ import annotations

import csv
import io
import re
from dataclasses import dataclass, field
from datetime import date, datetime, time, timedelta
from decimal import Decimal
from itertools import pairwise
from typing import Any

from django.db import transaction
from django.db.models import Q, QuerySet, Sum
from django.utils import timezone

from apps.audit.services import journaliser
from apps.habilitations.models import Utilisateur
from apps.habilitations.services import exiger
from apps.noyau.exceptions import AccesRefuse, ErreurMetier, ErreurValidation
from apps.noyau.montants import appliquer_taux, euros, proratiser
from apps.noyau.parametres import parametre
from apps.noyau.tableur import cellule_sure
from apps.reservations.models import Occurrence
from apps.reservations.recurrence import PARIS
from apps.usagers.models import Usager

from .models import Exercice, LigneValorisation, MethodeValorisation, SubventionNumeraire, Valorisation

SYSTEME = "système"
STATUTS_VALORISES = ("validee", "confirmee", "realisee", "cloturee")
#: Ni valorisation ni attestation : services municipaux (la Ville elle-même) et particuliers (pas de concours à une
#: personne physique, et aucun nom de particulier dans l'annexe publique du compte administratif) — D-061.
TYPES_EXCLUS = ("service_municipal", "particulier")
#: Seules les associations reçoivent une attestation (comptes 86/87, règlement ANC 2018-06).
TYPES_ATTESTATION = ("association",)
#: Annexe du compte administratif (CGCT L. 2313-1) : concours aux tiers ; les écoles publiques n'y figurent pas
#: (statistiques seulement, skill valorisation-subventions).
TYPES_ANNEXE = ("association", "entreprise", "autre_collectivite")


def _controler(acteur: Any, action: str, objet: Any = None) -> None:
    if acteur == SYSTEME:
        return
    if isinstance(acteur, Utilisateur):
        exiger(acteur, action, objet)
        return
    raise AccesRefuse("Vous n'avez pas les droits pour cette action.", code="droits_insuffisants")


def _bornes(debut: date, fin: date) -> tuple[datetime, datetime]:
    return datetime.combine(debut, time.min, tzinfo=PARIS), datetime.combine(fin + timedelta(days=1), time.min, tzinfo=PARIS)


@dataclass
class LigneCalculee:
    nature: str
    libelle: str
    quantite: int
    montant_reference: int
    montant_paye: int
    montant_valorise: int
    methode: str = "tarif_reference"
    part: int = 10000
    occurrence: Occurrence | None = None
    pret: Any = None
    espace: Any = None
    observation: str = ""


@dataclass
class Resultat:
    usager: Usager
    exercice: Exercice
    jusqu_au: date
    lignes: list[LigneCalculee] = field(default_factory=list)
    anomalies: list[str] = field(default_factory=list)

    def somme(self, nature: str) -> int:
        return sum(ligne.montant_valorise for ligne in self.lignes if ligne.nature == nature)

    @property
    def total(self) -> int:
        return sum(ligne.montant_valorise for ligne in self.lignes)

    @property
    def minutes(self) -> int:
        return sum(ligne.quantite for ligne in self.lignes if ligne.nature == "espace")


# --- Base de calcul (VAL-03) -------------------------------------------------------------------------------------


def seances_valorisables(
    usager: Usager, debut: date, fin: date, *, absences_valorisees: bool | None = None
) -> QuerySet[Occurrence]:
    borne_debut, borne_fin = _bornes(debut, fin)
    filtre = Q(statut__in=STATUTS_VALORISES) | Q(statut="annulee", annulation_tardive=True)
    qs = (
        Occurrence.objects.filter(reservation__dossier__usager=usager, debut__gte=borne_debut, debut__lt=borne_fin)
        .filter(filtre)
        .exclude(presence="absent_signale")
        .select_related("espace__famille", "espace__batiment__site", "reservation__dossier")
        .order_by("debut")
    )
    if absences_valorisees is None:
        absences_valorisees = bool(parametre("valorisation.absences_non_signalees_valorisees"))
    if not absences_valorisees:
        qs = qs.exclude(presence="absent_non_signale")
    return qs


def part_occupation(occurrence: Occurrence) -> int:
    """Part d'un espace partagé : sur chaque intervalle, l'occupation se répartit à parts égales entre les
    réservations simultanées d'usagers différents (en dix-millièmes)."""
    if not occurrence.espace.partageable:
        return 10000
    voisines = list(
        Occurrence.objects.filter(
            espace=occurrence.espace, statut__in=STATUTS_VALORISES, debut__lt=occurrence.fin, fin__gt=occurrence.debut
        )
        .exclude(pk=occurrence.pk)
        .exclude(reservation__dossier__usager_id=occurrence.reservation.dossier.usager_id)
        .values_list("debut", "fin")
    )
    if not voisines:
        return 10000
    bornes = sorted(
        {
            occurrence.debut,
            occurrence.fin,
            *[max(d, occurrence.debut) for d, _ in voisines],
            *[min(f, occurrence.fin) for _, f in voisines],
        }
    )
    duree = (occurrence.fin - occurrence.debut).total_seconds()
    cumul = 0.0
    for a, b in pairwise(bornes):
        presents = 1 + sum(1 for d, f in voisines if d < b and f > a)
        cumul += (b - a).total_seconds() / presents
    return round(10000 * cumul / duree) if duree else 10000


def _facture_net(lignes: QuerySet[Any]) -> int | None:
    """Montant net facturé par des lignes de facture émises (chaque ligne moins ses avoirs) ; None si aucune."""
    total, trouve = 0, False
    for ligne in lignes.filter(piece__nature="facture", piece__numero__isnull=False).prefetch_related("avoirs__piece"):
        trouve = True
        credite = sum(abs(a.montant_du) for a in ligne.avoirs.all() if a.piece.numero)
        total += max(0, ligne.montant_du - credite)
    return total if trouve else None


def _paye_pour(occurrence: Occurrence, du_occupation: int) -> int:
    """B1 (revue métier du lot 6) : ce que l'usager paie pour la séance — occupation et majorations facturées, avoirs
    déduits, plus les frais d'annulation tardive (facturés, sinon calculés au barème). Une séance non encore facturée
    compte son dû calculé ; une séance annulée ne doit plus que ses frais. Les acomptes n'en font pas partie."""
    from apps.finances.facturation import taux_frais_annulation
    from apps.finances.models import LigneComptable

    lignes = LigneComptable.objects.filter(occurrence=occurrence)
    occupation = _facture_net(lignes.filter(nature__in=["occupation", "majoration"]))
    if occupation is None:
        occupation = 0 if occurrence.statut == "annulee" else du_occupation
    frais = _facture_net(lignes.filter(nature="frais"))
    if frais is None:
        taux = taux_frais_annulation(occurrence) if occurrence.statut == "annulee" else 0
        frais = appliquer_taux(du_occupation, taux) if taux else 0
    return occupation + frais


def _methode(
    exercice: Exercice, famille_id: int | None, cache: dict[int | None, MethodeValorisation | None]
) -> MethodeValorisation | None:
    if famille_id not in cache:
        cache[famille_id] = MethodeValorisation.objects.filter(exercice=exercice, famille_id=famille_id).first()
    return cache[famille_id]


def _ligne_seance(occurrence: Occurrence, usager: Usager, methode: MethodeValorisation | None) -> LigneCalculee:
    from apps.finances.facturation import base_seance

    minutes = int((occurrence.fin - occurrence.debut).total_seconds() // 60)
    part = part_occupation(occurrence)
    # M1 : prix du devis accepté (RG-04), sinon tarif en vigueur ; ErreurMetier si aucun tarif de référence (RG-05).
    reference_tarif, du, _taux, _fondement = base_seance(occurrence)
    nom = methode.methode if methode else "tarif_reference"
    if nom == "cout_revient" and methode and methode.cout_horaire_centimes:
        reference = proratiser(methode.cout_horaire_centimes, minutes, 60)
    elif nom == "valeur_locative" and methode and methode.loyer_m2_annuel_centimes and occurrence.espace.surface_m2:
        annuel = methode.loyer_m2_annuel_centimes * int(occurrence.espace.surface_m2)
        reference = proratiser(annuel, minutes, 60 * max(1, methode.heures_annuelles_reference))
    else:
        nom, reference = "tarif_reference", reference_tarif
    paye = _paye_pour(occurrence, du)
    # M2 : chaque usager d'un espace partagé est facturé du créneau entier ; seule sa part de l'écart est valorisée.
    valorise = appliquer_taux(max(0, reference - paye), part)
    local = timezone.localtime(occurrence.debut, PARIS)
    observation = []
    if occurrence.statut == "annulee":
        observation.append("annulation hors délai")
    if occurrence.presence == "absent_non_signale":
        observation.append("absence non signalée")
    if part < 10000:
        observation.append(f"espace partagé ({part / 100:.0f} %)")
    return LigneCalculee(
        nature="espace",
        libelle=f"{occurrence.espace.nom}, {local:%d/%m/%Y %H:%M}",
        quantite=minutes,
        montant_reference=reference,
        montant_paye=paye,
        montant_valorise=valorise,
        methode=nom,
        part=part,
        occurrence=occurrence,
        espace=occurrence.espace,
        observation=", ".join(observation),
    )


def _lignes_personnel(occurrence: Occurrence, part: int, cout: int) -> list[LigneCalculee]:
    """Personnel dédié : la plage de gardiennage de la séance (ouverture et fermeture comprises), au coût chargé de
    l'exercice. Une séance annulée, même hors délai, n'a pas été gardiennée (sa vacation est annulée, RG-09)."""
    if occurrence.statut == "annulee" or not occurrence.espace.gardiennage_requis or not cout:
        return []
    plage = occurrence.espace.plage_gardiennage(occurrence.debut, occurrence.fin)
    if plage is None:
        return []
    minutes = int((plage[1] - plage[0]).total_seconds() // 60)
    montant = appliquer_taux(proratiser(cout, minutes, 60), part)
    return [
        LigneCalculee(
            nature="personnel",
            libelle=f"Gardiennage — {occurrence.espace.nom}, {timezone.localtime(occurrence.debut, PARIS):%d/%m/%Y}",
            quantite=minutes,
            montant_reference=montant,
            montant_paye=0,
            montant_valorise=montant,
            part=part,
            occurrence=occurrence,
            espace=occurrence.espace,
        )
    ]


def _lignes_materiel(usager: Usager, debut: date, fin: date) -> list[LigneCalculee]:
    """Prêts accordés : valeur de référence et prestation figées sur le prêt (RG-05) ; un prêt de séance compte une
    journée, un prêt sur une période les journées civiles touchées ; quantité réellement remise si elle est connue.
    Une séance annulée dans les délais ne valorise pas son matériel (son prêt est annulé avec elle)."""
    from apps.finances.models import LigneComptable
    from apps.materiel.models import ReservationMateriel
    from apps.materiel.services import jours_touches

    borne_debut, borne_fin = _bornes(debut, fin)
    lignes = []
    utilisees: set[int] = set()
    for pret in (
        ReservationMateriel.objects.filter(
            dossier__usager=usager, statut__in=["validee", "sortie", "rendue"], debut__gte=borne_debut, debut__lt=borne_fin
        )
        .select_related("stock__materiel", "dossier", "occurrence")
        .order_by("debut", "pk")
    ):
        jours = 1 if pret.occurrence_id else jours_touches(pret.debut, pret.fin)
        quantite = pret.quantite_sortie if pret.quantite_sortie is not None else pret.quantite
        reference = quantite * jours * pret.valeur_journaliere_centimes
        paye = _paye_pret(pret, jours, utilisees, LigneComptable)
        lignes.append(
            LigneCalculee(
                nature="materiel",
                libelle=f"{quantite} × {pret.stock.materiel.libelle}, {jours} jour{'s' if jours > 1 else ''}",
                quantite=quantite * jours,
                montant_reference=reference,
                montant_paye=paye,
                montant_valorise=max(0, reference - paye),
                pret=pret,
                observation="" if pret.valeur_journaliere_centimes else "valeur de référence absente",
            )
        )
    return lignes


def _paye_pret(pret: Any, jours: int, utilisees: set[int], ligne_comptable: Any) -> int:
    """M3 (revue métier du lot 6) : la ligne de prestation facturée pour CE prêt — même dossier, même séance (ou
    aucune pour un prêt sur une période), libellé de la prestation et quantité facturée — avoirs déduits ; une ligne
    ne paie qu'un seul prêt."""
    from apps.finances.models import Prestation
    from apps.finances.tarification import grille_en_vigueur

    if not pret.prestation_code:
        return 0
    jour = timezone.localtime(pret.debut, PARIS).date()
    prestation = Prestation.objects.filter(grille=grille_en_vigueur(jour), code=pret.prestation_code).first()
    if prestation is None:
        return 0
    quantite = pret.quantite if pret.occurrence_id else pret.quantite * jours
    candidates = (
        ligne_comptable.objects.filter(
            piece__dossier_id=pret.dossier_id,
            piece__nature="facture",
            piece__numero__isnull=False,
            nature="prestation",
            occurrence_id=pret.occurrence_id,
            libelle=prestation.libelle,
            quantite=quantite,
        )
        .exclude(pk__in=utilisees)
        .order_by("pk")
    )
    ligne = candidates.first()
    if ligne is None:
        return 0
    utilisees.add(ligne.pk)
    return _facture_net(ligne_comptable.objects.filter(pk=ligne.pk)) or 0


def calculer(usager: Usager, exercice: Exercice, *, jusqu_au: date | None = None) -> Resultat:
    """Calcul pur (sans écriture) ; `jusqu_au` borne une simulation en cours d'année (VAL-07). Les paramètres
    (coût du personnel, absences) sont ceux de l'exercice (M8)."""
    fin = min(jusqu_au or exercice.fin, exercice.fin)
    resultat = Resultat(usager=usager, exercice=exercice, jusqu_au=fin)
    methodes: dict[int | None, MethodeValorisation | None] = {}
    cout_personnel = exercice.cout_personnel()
    for occurrence in seances_valorisables(usager, exercice.debut, fin, absences_valorisees=exercice.absences_valorisees()):
        try:
            ligne = _ligne_seance(occurrence, usager, _methode(exercice, occurrence.espace.famille_id, methodes))
        except ErreurMetier as erreur:
            if erreur.code not in ("sans_grille", "sans_tarif_reference"):
                raise
            resultat.anomalies.append(
                f"{occurrence.espace.nom}, {timezone.localtime(occurrence.debut, PARIS):%d/%m/%Y} : {erreur.message}"
            )
            continue
        resultat.lignes.append(ligne)
        resultat.lignes += _lignes_personnel(occurrence, ligne.part, cout_personnel)
    resultat.lignes += _lignes_materiel(usager, exercice.debut, fin)
    return resultat


# --- Enregistrement, clôture, recalcul (VAL-02, VAL-08) -----------------------------------------------------------


def beneficiaires(exercice: Exercice) -> QuerySet[Usager]:
    """Usagers ayant eu une séance ou un prêt de matériel dans l'exercice (m5), hors types exclus."""
    debut, fin = _bornes(exercice.debut, exercice.fin)
    seances = Q(dossiers__reservations__occurrences__debut__gte=debut, dossiers__reservations__occurrences__debut__lt=fin)
    prets = Q(
        dossiers__materiels__debut__gte=debut,
        dossiers__materiels__debut__lt=fin,
        dossiers__materiels__statut__in=["validee", "sortie", "rendue"],
    )
    ids = set(Usager.objects.filter(seances).values_list("pk", flat=True)) | set(
        Usager.objects.filter(prets).values_list("pk", flat=True)
    )
    return Usager.objects.filter(pk__in=ids).exclude(type__in=TYPES_EXCLUS).exclude(statut="anonymise").order_by("nom")


def _valorisable(usager: Usager) -> None:
    if usager.type in TYPES_EXCLUS:
        raise ErreurMetier(
            "Les services municipaux et les particuliers ne sont pas valorisés (D-061).", code="beneficiaire_exclu"
        )


def _enregistrer(resultat: Resultat, *, acteur: Any, figee: bool, motif: str = "") -> Valorisation:
    precedente = (
        Valorisation.objects.select_for_update().filter(exercice=resultat.exercice, usager=resultat.usager, actuelle=True).first()
    )
    version = (precedente.version + 1) if precedente else 1
    if precedente is not None:
        Valorisation.objects.filter(pk=precedente.pk).update(actuelle=False)
    valorisation = Valorisation.objects.create(
        exercice=resultat.exercice,
        usager=resultat.usager,
        version=version,
        actuelle=True,
        figee=False,
        minutes=resultat.minutes,
        montant_espaces=resultat.somme("espace"),
        montant_materiel=resultat.somme("materiel"),
        montant_personnel=resultat.somme("personnel"),
        total=resultat.total,
        calcule_par=str(acteur)[:200],
        motif_recalcul=motif,
    )
    LigneValorisation.objects.bulk_create(
        [
            LigneValorisation(
                valorisation=valorisation,
                nature=ligne.nature,
                occurrence=ligne.occurrence,
                pret=ligne.pret,
                espace=ligne.espace,
                libelle=ligne.libelle[:250],
                methode=ligne.methode,
                quantite=ligne.quantite,
                part=ligne.part,
                montant_reference=ligne.montant_reference,
                montant_paye=ligne.montant_paye,
                montant_valorise=ligne.montant_valorise,
                observation=ligne.observation[:250],
            )
            for ligne in resultat.lignes
        ]
    )
    if figee:
        # Figée après l'écriture de ses lignes : le déclencheur interdit ensuite toute modification (VAL-08).
        Valorisation.objects.filter(pk=valorisation.pk).update(figee=True)
        valorisation.figee = True
    journaliser(
        "calculer_valorisation",
        valorisation,
        apres={"version": version, "total": valorisation.total, "motif": motif[:200]},
        acteur=acteur if isinstance(acteur, Utilisateur) else None,
    )
    return valorisation


@transaction.atomic
def valoriser(usager: Usager, exercice: Exercice, *, acteur: Any) -> Valorisation:
    """VAL-02 : calcul enregistré (nouvelle version). Refusé sur un exercice clos : passer par la procédure de recalcul.
    La valorisation porte sur toute la Ville : réservée à un périmètre « tous sites » (M1, M4 des revues)."""
    _controler(acteur, "calculer_valorisation", exercice)
    _valorisable(usager)
    exercice = Exercice.objects.select_for_update().get(pk=exercice.pk)
    if exercice.statut == "cloture":
        raise ErreurMetier(
            f"L'exercice {exercice.annee} est clôturé : les montants sont figés. Un recalcul passe par la procédure tracée.",
            code="exercice_cloture",
        )
    resultat = calculer(usager, exercice)
    if resultat.anomalies:
        raise ErreurMetier(
            "Tarif de référence manquant (RG-05) : " + " ; ".join(resultat.anomalies[:10]),
            code="tarif_reference_manquant",
            details={"anomalies": resultat.anomalies},
        )
    return _enregistrer(resultat, acteur=acteur, figee=False)


def valoriser_exercice(exercice: Exercice, *, acteur: Any) -> dict[str, Any]:
    """Calcul de tous les bénéficiaires ; les anomalies d'un bénéficiaire n'arrêtent pas les autres."""
    _controler(acteur, "calculer_valorisation", exercice)
    bilan: dict[str, Any] = {"calcules": 0, "anomalies": []}
    for usager in beneficiaires(exercice):
        try:
            valoriser(usager, exercice, acteur=acteur)
            bilan["calcules"] += 1
        except ErreurMetier as erreur:
            if erreur.code == "exercice_cloture":
                raise
            bilan["anomalies"].append(f"{usager.nom} : {erreur.message}")
    return bilan


def _identique(valorisation: Valorisation, resultat: Resultat) -> bool:
    return (
        valorisation.total == resultat.total
        and valorisation.minutes == resultat.minutes
        and valorisation.montant_espaces == resultat.somme("espace")
        and valorisation.montant_materiel == resultat.somme("materiel")
        and valorisation.montant_personnel == resultat.somme("personnel")
    )


@transaction.atomic
def cloturer(exercice: Exercice, *, acteur: Any) -> Exercice:
    """VAL-08 : la clôture recalcule chaque bénéficiaire sur l'état définitif des séances et des pièces (B3) ; une
    version restée exacte est figée, sinon une nouvelle version figée la remplace. Toutes les versions de l'exercice
    sont figées (m6) et ses paramètres de calcul sont arrêtés (M8). Réservée à un périmètre « tous sites »."""
    _controler(acteur, "cloturer_valorisation", exercice)
    exercice = Exercice.objects.select_for_update().get(pk=exercice.pk)
    if exercice.statut == "cloture":
        raise ErreurMetier("Exercice déjà clôturé.", code="exercice_cloture")
    if exercice.fin >= timezone.localdate():
        raise ErreurMetier("Un exercice se clôture une fois terminé.", code="exercice_en_cours")
    exercice.cout_horaire_personnel_centimes = exercice.cout_personnel()
    exercice.absences_non_signalees_valorisees = exercice.absences_valorisees()
    exercice.save(update_fields=["cout_horaire_personnel_centimes", "absences_non_signalees_valorisees"])
    resultats = [calculer(usager, exercice) for usager in beneficiaires(exercice)]
    anomalies = [f"{r.usager.nom} : {a}" for r in resultats for a in r.anomalies]
    if anomalies:
        raise ErreurMetier(
            f"Tarif de référence manquant (RG-05), clôture impossible : {' ; '.join(anomalies[:5])}.",
            code="tarif_reference_manquant",
            details={"anomalies": anomalies[:200]},
        )
    recalcules = 0
    for resultat in resultats:
        actuelle = Valorisation.objects.filter(exercice=exercice, usager=resultat.usager, actuelle=True).first()
        if actuelle is not None and _identique(actuelle, resultat):
            continue
        _enregistrer(
            resultat, acteur=acteur, figee=False, motif="Recalcul à la clôture : séances ou pièces modifiées depuis le calcul."
        )
        recalcules += 1
    Valorisation.objects.filter(exercice=exercice, figee=False).update(figee=True)
    exercice.statut, exercice.cloture_le = "cloture", timezone.now()
    exercice.cloture_par = acteur if isinstance(acteur, Utilisateur) else None
    exercice.save(update_fields=["statut", "cloture_le", "cloture_par"])
    journaliser(
        "cloturer_exercice_valorisation",
        exercice,
        apres={"beneficiaires": len(resultats), "recalcules": recalcules},
        acteur=acteur if isinstance(acteur, Utilisateur) else None,
    )
    return exercice


@transaction.atomic
def recalculer_apres_cloture(valorisation: Valorisation, *, acteur: Any, motif: str) -> Valorisation:
    """Procédure tracée (VAL-08) : nouvelle version figée, motivée, par un agent habilité à clôturer ; l'ancienne
    reste consultable et l'attestation éventuelle est à rééditer."""
    _controler(acteur, "cloturer_valorisation", valorisation)
    if len(motif.strip()) < 20:
        raise ErreurValidation("Motivez le recalcul (au moins une phrase) : il est tracé au journal.", code="motif_requis")
    valorisation = Valorisation.objects.select_for_update().select_related("exercice", "usager").get(pk=valorisation.pk)
    if valorisation.exercice.statut != "cloture":
        raise ErreurMetier("L'exercice est ouvert : recalculez directement.", code="exercice_ouvert")
    if not valorisation.actuelle:
        raise ErreurMetier("Seule la dernière version se recalcule.", code="version_remplacee")
    resultat = calculer(valorisation.usager, valorisation.exercice)
    if resultat.anomalies:
        raise ErreurMetier(
            "Tarif de référence manquant (RG-05) : " + " ; ".join(resultat.anomalies[:10]), code="tarif_reference_manquant"
        )
    nouvelle = _enregistrer(resultat, acteur=acteur, figee=True, motif=motif.strip())
    if valorisation.document_id and nouvelle.usager.type in TYPES_ATTESTATION and nouvelle.total > 0:
        # m7 : l'attestation déposée est remplacée ; la nouvelle part en signature et l'association est prévenue.
        editer_attestation(nouvelle, acteur=acteur)
    return nouvelle


# --- Subventions en numéraire et seuils (VAL-06) -----------------------------------------------------------------


MONTANT_IMPORT = re.compile(r"^(\d{1,3}(?:[ \u00a0\u202f]\d{3})+|\d+)(?:,(\d{1,2}))?$")
MONTANT_MAX_CENTIMES = 10_000_000_000  # 100 millions d'euros


def _montant(texte: str) -> int:
    """Montant en euros au format français (« 22 980 », « 22980,50 ») ; le point n'est accepté que comme séparateur
    décimal d'un nombre sans espace (« 22980.50 ») — « 22.980 » est ambigu et refusé (M6)."""
    brut = texte.strip().replace("€", "").strip()
    if re.fullmatch(r"\d+\.\d{1,2}", brut):
        brut = brut.replace(".", ",")
    trouve = MONTANT_IMPORT.match(brut)
    if trouve is None:
        raise ValueError(f"montant illisible « {texte[:40]} » (format attendu : 22 980,50)")
    entiers = re.sub(r"\D", "", trouve.group(1))
    decimales = (trouve.group(2) or "").ljust(2, "0")
    valeur = int(Decimal(entiers) * 100 + Decimal(decimales or "0"))
    if valeur > MONTANT_MAX_CENTIMES:
        raise ValueError("montant supérieur à 100 millions d'euros")
    return valeur


def _rapprocher(identifiant: str) -> tuple[Usager | None, str]:
    """SIRET, puis RNA, puis nom exact ; un nom porté par plusieurs usagers est ambigu (m2 sécurité)."""
    candidats = Usager.objects.exclude(type__in=TYPES_EXCLUS).exclude(statut="anonymise")
    for filtre in ({"siret": identifiant}, {"rna__iexact": identifiant}, {"nom__iexact": identifiant}):
        trouves = list(candidats.filter(**filtre)[:2])
        if len(trouves) == 1:
            return trouves[0], ""
        if len(trouves) > 1:
            return None, "plusieurs bénéficiaires correspondent : indiquez le SIRET ou le RNA"
    return None, "bénéficiaire inconnu"


@transaction.atomic
def importer_subventions(exercice: Exercice, contenu: bytes, *, acteur: Any, confirmer: bool = False) -> dict[str, Any]:
    """Import CSV (séparateur « ; ») : identifiant (SIRET, RNA ou nom), montant en euros, objet, délibération.
    Un nouvel import remplace le précédent de l'exercice, une fois tout le fichier lu ; s'il reste des lignes
    rejetées, rien n'est remplacé sans confirmation (M6). Refusé sur un exercice clos (B2)."""
    _controler(acteur, "calculer_valorisation", exercice)
    exercice = Exercice.objects.select_for_update().get(pk=exercice.pk)
    if exercice.statut == "cloture":
        raise ErreurMetier(f"L'exercice {exercice.annee} est clôturé : ses subventions sont figées.", code="exercice_cloture")
    if len(contenu) > 2_000_000:
        raise ErreurValidation("Fichier trop volumineux (2 Mo au plus).", code="fichier_trop_gros")
    for encodage in ("utf-8-sig", "cp1252"):
        try:
            texte = contenu.decode(encodage)
            break
        except UnicodeDecodeError:
            continue
    else:
        raise ErreurValidation("Encodage du fichier non reconnu.", code="encodage_invalide")
    csv.field_size_limit(10_000)
    lecteur = csv.reader(io.StringIO(texte), delimiter=";")
    try:
        entete = [c.strip().lower() for c in next(lecteur, [])]
        attendues = {"identifiant", "montant"}
        if not attendues <= set(entete):
            raise ErreurValidation("Colonnes attendues : identifiant ; montant ; objet ; deliberation.", code="colonnes_absentes")
        index = {nom: entete.index(nom) for nom in entete}
        a_creer: list[SubventionNumeraire] = []
        rejets: list[str] = []
        for numero, ligne in enumerate(lecteur, start=2):
            if numero > 5001:
                rejets.append("Au-delà de 5 000 lignes : fin de l'import.")
                break
            if not any(c.strip() for c in ligne):
                continue

            def valeur(nom: str, cellules: list[str] = ligne) -> str:
                return cellules[index[nom]].strip() if nom in index and index[nom] < len(cellules) else ""

            identifiant = valeur("identifiant")[:120]
            usager, motif = _rapprocher(identifiant) if identifiant else (None, "identifiant absent")
            if usager is None:
                rejets.append(f"Ligne {numero} : « {identifiant[:60]} » — {motif}.")
                continue
            try:
                montant = _montant(valeur("montant"))
            except ValueError as erreur:
                rejets.append(f"Ligne {numero} : {erreur}.")
                continue
            a_creer.append(
                SubventionNumeraire(
                    exercice=exercice,
                    usager=usager,
                    montant_centimes=montant,
                    objet=valeur("objet")[:250],
                    deliberation_reference=valeur("deliberation")[:120],
                    reference_import=f"ligne {numero}",
                )
            )
    except csv.Error as erreur:
        raise ErreurValidation("Fichier CSV illisible (champ trop long ou mal délimité).", code="csv_invalide") from erreur
    if rejets and not confirmer:
        return {"importees": 0, "a_importer": len(a_creer), "rejets": rejets, "confirmation_requise": True}
    if not a_creer:
        raise ErreurValidation("Aucune ligne importable : l'import précédent est conservé.", code="import_vide")
    SubventionNumeraire.objects.filter(exercice=exercice).exclude(reference_import="").delete()
    SubventionNumeraire.objects.bulk_create(a_creer)
    journaliser(
        "importer_subventions",
        exercice,
        apres={"importees": len(a_creer), "rejets": len(rejets), "total_centimes": sum(s.montant_centimes for s in a_creer)},
        acteur=acteur if isinstance(acteur, Utilisateur) else None,
    )
    return {"importees": len(a_creer), "rejets": rejets, "confirmation_requise": False}


def seuils() -> tuple[int, int]:
    return int(parametre("valorisation.seuil_convention_centimes")), int(parametre("valorisation.seuil_compte_rendu_centimes"))


def synthese(exercice: Exercice) -> list[dict[str, Any]]:
    """VAL-05, VAL-06 : par bénéficiaire, nature + numéraire, et alertes de seuil (convention, compte rendu financier)."""
    convention, compte_rendu = seuils()
    numeraire: dict[int, int] = {}
    for ligne in SubventionNumeraire.objects.filter(exercice=exercice).values("usager_id").annotate(s=Sum("montant_centimes")):
        numeraire[ligne["usager_id"]] = int(ligne["s"])
    lignes = []
    for valorisation in (
        Valorisation.objects.filter(exercice=exercice, actuelle=True).select_related("usager").order_by("usager__nom")
    ):
        especes = numeraire.pop(valorisation.usager_id, 0)
        lignes.append(_ligne_synthese(valorisation.usager, valorisation, especes, convention, compte_rendu))
    for usager in Usager.objects.filter(pk__in=numeraire):
        lignes.append(_ligne_synthese(usager, None, numeraire[usager.pk], convention, compte_rendu))
    return sorted(lignes, key=lambda ligne: -ligne["total"])


def _ligne_synthese(
    usager: Usager, valorisation: Valorisation | None, especes: int, convention: int, compte_rendu: int
) -> dict[str, Any]:
    nature = valorisation.total if valorisation else 0
    total = nature + especes
    alertes = []
    if total > convention:
        alertes.append("convention")
    if total > compte_rendu:
        alertes.append("compte_rendu")
    return {
        "usager": usager,
        "valorisation": valorisation,
        "nature": nature,
        "numeraire": especes,
        "total": total,
        "alertes": alertes,
    }


def annexe_csv(exercice: Exercice) -> bytes:
    """VAL-05 : état annexé au compte administratif (CGCT L. 2313-1), bénéficiaire, nature et montants."""
    sortie = io.StringIO()
    ecrivain = csv.writer(sortie, delimiter=";")
    ecrivain.writerow(
        [
            "Bénéficiaire",
            "SIRET",
            "RNA",
            "Nature du concours",
            "Concours en nature (€)",
            "Subventions en numéraire (€)",
            "Total (€)",
        ]
    )
    for ligne in synthese(exercice):
        usager, valorisation = ligne["usager"], ligne["valorisation"]
        if usager.type not in TYPES_ANNEXE or ligne["total"] <= 0:
            continue
        natures = []
        if valorisation is not None:
            if valorisation.montant_espaces:
                natures.append("mise à disposition de locaux")
            if valorisation.montant_materiel:
                natures.append("prêt de matériel")
            if valorisation.montant_personnel:
                natures.append("personnel")
        ecrivain.writerow(
            [
                cellule_sure(usager.nom),
                cellule_sure(usager.siret),
                cellule_sure(usager.rna),
                ", ".join(natures) or "—",
                f"{ligne['nature'] / 100:.2f}".replace(".", ","),
                f"{ligne['numeraire'] / 100:.2f}".replace(".", ","),
                f"{ligne['total'] / 100:.2f}".replace(".", ","),
            ]
        )
    return ("﻿" + sortie.getvalue()).encode("utf-8")


# --- Attestation (VAL-04) ----------------------------------------------------------------------------------------


@transaction.atomic
def editer_attestation(valorisation: Valorisation, *, acteur: Any) -> Valorisation:
    """Attestation PDF/A de la version actuelle, déposée sur le portail de l'association (document immuable)."""
    from apps.documents import services as documents

    _controler(acteur, "calculer_valorisation", valorisation)
    valorisation = Valorisation.objects.select_for_update().select_related("exercice", "usager").get(pk=valorisation.pk)
    if not valorisation.actuelle:
        raise ErreurMetier("Cette version a été remplacée.", code="version_remplacee")
    if valorisation.usager.type not in TYPES_ATTESTATION:
        raise ErreurMetier("Les attestations sont destinées aux associations.", code="attestation_non_prevue")
    if not valorisation.figee:
        raise ErreurMetier(
            "L'attestation porte sur un exercice clôturé : les montants doivent être définitifs (VAL-04, VAL-08).",
            code="exercice_ouvert",
        )
    if valorisation.document_id:
        raise ErreurMetier("L'attestation de cette version est déjà éditée.", code="attestation_existante")
    if valorisation.total <= 0:
        raise ErreurMetier("Aucun avantage en nature à attester.", code="valorisation_nulle")
    document = documents.generer("attestation-valorisation", valorisation, acteur=acteur, controle_droits=False)
    Valorisation.objects.filter(pk=valorisation.pk).update(document=document)
    valorisation.refresh_from_db()
    if document.modele.signature_requise:
        # m8 : l'attestation est signée par l'élu délégataire ; elle est déposée sur le portail une fois signée.
        documents.envoyer_en_signature(document, acteur=acteur, controle_droits=False)
    else:
        deposer_attestation(document)
        valorisation.refresh_from_db()
    return valorisation


def deposer_attestation(document: Any) -> None:
    """Dépôt sur le portail de l'attestation signée (appelé à la fin de la signature) et avis à l'association."""
    from apps.communication.services import notifier

    valorisation = (
        Valorisation.objects.filter(document=document, deposee_le__isnull=True).select_related("exercice", "usager").first()
    )
    if valorisation is None:
        return
    Valorisation.objects.filter(pk=valorisation.pk).update(deposee_le=timezone.now())
    notifier(
        "attestation_valorisation_disponible",
        {"exercice": valorisation.exercice.annee, "montant": euros(valorisation.total), "usager": valorisation.usager.nom},
        usager=valorisation.usager,
        objet=valorisation,
    )


def libelle_methode(code: str) -> str:
    return {
        "tarif_reference": "tarif de référence voté",
        "cout_revient": "coût de revient horaire",
        "valeur_locative": "valeur locative",
    }.get(code, code)
