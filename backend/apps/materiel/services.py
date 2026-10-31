"""Règles du matériel (lot 5) : disponibilité sur une période (MAT-02), prêts séance par séance et retours avec
manquants (MAT-03), mouvements de stock (entrée, transfert, perte, inventaire), contrôles périodiques (MAT-04),
pannes (MAT-05).

Un prêt rattaché à une réservation l'est séance par séance : le matériel n'est immobilisé que pendant les séances,
il suit leurs déplacements et leurs annulations, et il est facturé, crédité et valorisé séance par séance (D-059).
Les quantités d'un stock ne changent que par ces services, chacun écrivant son mouvement dans le journal immuable."""

from __future__ import annotations

from collections.abc import Iterable
from datetime import date, datetime, timedelta
from typing import Any

from django.conf import settings
from django.db import transaction
from django.db.models import Q, QuerySet
from django.utils import timezone

from apps.audit.services import journaliser
from apps.communication.services import notifier
from apps.habilitations.models import Utilisateur
from apps.habilitations.services import exiger
from apps.noyau.exceptions import AccesRefuse, ErreurMetier, ErreurValidation
from apps.noyau.parametres import parametre
from apps.referentiel.models import Espace, Site
from apps.reservations.models import Dossier, Occurrence, Reservation
from apps.reservations.recurrence import PARIS
from apps.usagers.models import Contact

from .models import Controle, Materiel, Mouvement, Panne, ReservationMateriel, Stock

SYSTEME = "système"
#: Prêts qui immobilisent le matériel ; une demande ne bloque qu'une fois validée, un prêt sorti jusqu'à son retour.
STATUTS_BLOQUANTS = ("validee", "sortie")
STATUTS_EN_COURS = ("demandee", "validee")
SEANCES_INACTIVES = ("annulee", "refusee")
RESERVATIONS_ACCORDEES = ("validee", "confirmee")
DUREE_MAX_PRET = timedelta(days=31)
DEMANDES_PORTAIL_MAX = 20


def _controler(acteur: Any, action: str, objet: Any = None) -> None:
    if acteur == SYSTEME:
        return
    if isinstance(acteur, Utilisateur):
        exiger(acteur, action, objet)
        return
    raise AccesRefuse("Vous n'avez pas les droits pour cette action.", code="droits_insuffisants")


def _agent(acteur: Any) -> Utilisateur | None:
    return acteur if isinstance(acteur, Utilisateur) else None


def _mouvement(
    type_mouvement: str,
    stock: Stock,
    quantite: int,
    acteur: Any,
    *,
    motif: str = "",
    destination: Stock | None = None,
    reservation: ReservationMateriel | None = None,
) -> Mouvement:
    mouvement = Mouvement.objects.create(
        type=type_mouvement,
        stock=stock,
        stock_destination=destination,
        quantite=quantite,
        reservation=reservation,
        motif=motif[:300],
        agent=_agent(acteur),
        acteur_libelle=str(acteur)[:200],
    )
    journaliser(
        f"materiel_{type_mouvement}",
        stock,
        apres={"quantite": quantite, "motif": motif[:200], "destination": destination.pk if destination else None},
        acteur=_agent(acteur),
    )
    return mouvement


def _texte(instant: datetime) -> str:
    return timezone.localtime(instant, PARIS).strftime("%d/%m/%Y %H:%M")


def _verrouiller_stock(pk: int) -> Stock:
    return Stock.objects.select_for_update(of=("self",)).select_related("materiel").get(pk=pk)


# --- Disponibilité (MAT-02) ----------------------------------------------------------------------------------


def _engage(pret: ReservationMateriel) -> int:
    """Quantité immobilisée : réservée, ou réellement sortie et pas encore rendue."""
    if pret.statut == "sortie" and pret.quantite_sortie is not None:
        return pret.quantite_sortie - (pret.quantite_rendue or 0)
    return pret.quantite


def _prets_engages(stock: Stock, debut: datetime, fin: datetime, exclure: int | None = None) -> QuerySet[ReservationMateriel]:
    if stock.materiel.nature == "consommable":
        # Un consommable prêté est consommé : tous les prêts non soldés comptent, quelle que soit leur date.
        prets = ReservationMateriel.objects.filter(stock=stock, statut__in=STATUTS_BLOQUANTS)
    else:
        # Un prêt sorti immobilise le matériel jusqu'à son retour, même au-delà de sa date de fin.
        prets = ReservationMateriel.objects.filter(stock=stock).filter(
            Q(statut="validee", debut__lt=fin, fin__gt=debut) | Q(statut="sortie", debut__lt=fin)
        )
    return prets.exclude(pk=exclure) if exclure else prets


def pic_d_engagement(stock: Stock, debut: datetime, fin: datetime, exclure: int | None = None) -> int:
    """Plus forte quantité prêtée simultanément sur la période (balayage des débuts et fins de prêt)."""
    prets = list(_prets_engages(stock, debut, fin, exclure))
    if stock.materiel.nature == "consommable":
        return sum(_engage(p) for p in prets)
    evenements: list[tuple[datetime, int]] = []
    for pret in prets:
        fin_effective = fin if pret.statut == "sortie" else min(pret.fin, fin)
        evenements.append((max(pret.debut, debut), _engage(pret)))
        evenements.append((fin_effective, -_engage(pret)))
    pic = courant = 0
    for _instant, variation in sorted(evenements, key=lambda e: (e[0], e[1])):
        courant += variation
        pic = max(pic, courant)
    return pic


def disponible(stock: Stock, debut: datetime, fin: datetime, exclure: int | None = None) -> int:
    """Unités en état moins le plus fort engagement de la période (MAT-02, MAT-05)."""
    return max(0, stock.en_etat - pic_d_engagement(stock, debut, fin, exclure))


def sortis(stock: Stock) -> int:
    return sum(_engage(p) for p in ReservationMateriel.objects.filter(stock=stock, statut="sortie"))


def presents(stock: Stock) -> int:
    """Unités en état physiquement sur place (ni en panne, ni chez un usager)."""
    return max(0, stock.en_etat - sortis(stock))


def _verifier_disponibilite(stock: Stock, quantite: int, debut: datetime, fin: datetime, exclure: int | None = None) -> None:
    libre = disponible(stock, debut, fin, exclure)
    if quantite > libre:
        raise ErreurMetier(
            f"{stock.materiel} : {libre} {stock.materiel.unite}(s) disponible(s) du {_texte(debut)} au {_texte(fin)}, "
            f"{quantite} demandé(s).",
            code="materiel_indisponible",
            details={"disponible": libre},
        )


def jours_touches(debut: datetime, fin: datetime) -> int:
    """Journées civiles (Europe/Paris) touchées par un prêt : un passage de minuit ou d'heure compte juste."""
    premier = timezone.localtime(debut, PARIS).date()
    dernier = timezone.localtime(fin - timedelta(seconds=1), PARIS).date()
    return max(1, (dernier - premier).days + 1)


# --- Prêts (MAT-02, MAT-03) ------------------------------------------------------------------------------------


def _verifier_article(materiel: Materiel, origine: str) -> None:
    if not materiel.actif or not materiel.reservable:
        raise ErreurMetier(f"{materiel} n'est pas réservable.", code="materiel_non_reservable")
    if origine == "portail" and not materiel.propose_portail:
        raise ErreurMetier(f"{materiel} ne se demande pas en ligne.", code="materiel_non_reservable")
    if not materiel.valeur_journaliere_centimes:
        # RG-05 transposé : un prêt (gratuit ou non) garde une valeur de référence, sinon la valorisation est fausse.
        raise ErreurMetier(
            f"{materiel} n'a pas de valeur de référence : renseignez-la au catalogue.", code="valeur_reference_manquante"
        )


def _verifier_acteur(acteur: Any, origine: str, dossier: Dossier) -> None:
    if origine == "portail":
        if not isinstance(acteur, Contact):
            raise AccesRefuse("Une demande en ligne émane d'un contact du portail.", code="droits_insuffisants")
        return
    _controler(acteur, "creer_reservation", dossier)


def _verifier_lieu(stock: Stock, espace: Espace) -> None:
    if espace.batiment.site_id != stock.site_id:
        raise ErreurMetier("Le matériel est prêté sur le site de la séance.", code="materiel_autre_site")
    if stock.materiel.nature == "fixe":
        voisins = {espace.pk, espace.parent_id, *espace.sous_espaces.values_list("pk", flat=True)}
        if stock.espace_id not in voisins:
            raise ErreurMetier("Un équipement fixe ne sert que dans son espace.", code="materiel_fixe_autre_espace")


def _statut_initial(origine: str, reservation: Reservation | None) -> str:
    """Le back-office valide d'emblée un prêt sur une réservation accordée ; sinon le prêt attend (D-059)."""
    if origine == "backoffice" and reservation is not None and reservation.statut in RESERVATIONS_ACCORDEES:
        return "validee"
    return "demandee"


def _periode_du_dossier(dossier: Dossier) -> tuple[datetime, datetime] | None:
    seances = Occurrence.objects.filter(reservation__dossier=dossier).exclude(statut__in=SEANCES_INACTIVES)
    premiere, derniere = seances.order_by("debut").first(), seances.order_by("-fin").first()
    return (premiere.debut, derniere.fin) if premiere and derniere else None


@transaction.atomic
def reserver(
    dossier: Dossier,
    stock: Stock,
    quantite: int,
    *,
    acteur: Any,
    occurrence: Occurrence | None = None,
    debut: datetime | None = None,
    fin: datetime | None = None,
    origine: str = "backoffice",
    commentaire: str = "",
) -> ReservationMateriel:
    """Prêt pour une séance du dossier (période de la séance), ou sur une période qui tient dans celle du dossier
    (31 jours au plus). Refusé si la quantité n'est pas disponible (R5-02)."""
    _verifier_acteur(acteur, origine, dossier)
    stock = _verrouiller_stock(stock.pk)
    _verifier_article(stock.materiel, origine)
    if not 1 <= quantite <= 9999:
        raise ErreurValidation("Quantité entre 1 et 9 999.", code="quantite_invalide")
    reservation: Reservation | None = None
    if occurrence is not None:
        occurrence = Occurrence.objects.select_related("reservation", "espace__batiment").get(pk=occurrence.pk)
        reservation = occurrence.reservation
        if reservation.dossier_id != dossier.pk or occurrence.statut in (*SEANCES_INACTIVES, "realisee", "cloturee"):
            raise ErreurValidation("Choisissez une séance à venir de ce dossier.", code="seance_invalide")
        _verifier_lieu(stock, occurrence.espace)
        debut, fin = occurrence.debut, occurrence.fin
    else:
        periode = _periode_du_dossier(dossier)
        if periode is None:
            raise ErreurMetier("Le dossier n'a plus de séance.", code="reservation_sans_seance")
        if debut is None or fin is None or fin <= debut:
            raise ErreurValidation("Indiquez la période du prêt.", code="periode_invalide")
        if debut < periode[0] - timedelta(days=1) or fin > periode[1] + timedelta(days=1) or fin - debut > DUREE_MAX_PRET:
            raise ErreurValidation(
                "Le prêt tient dans la période des séances du dossier (31 jours au plus).", code="hors_periode"
            )
        sites = set(
            dossier.reservations.exclude(statut__in=SEANCES_INACTIVES).values_list("espace__batiment__site_id", flat=True)
        )
        if stock.site_id not in sites or stock.materiel.nature == "fixe":
            raise ErreurMetier("Le matériel est prêté sur le site d'une des séances du dossier.", code="materiel_autre_site")
        reservation = (
            dossier.reservations.filter(espace__batiment__site_id=stock.site_id).exclude(statut__in=SEANCES_INACTIVES).first()
        )
    if stock.materiel.prestation_code and quantite * jours_touches(debut, fin) > 999:
        raise ErreurValidation("Prêt facturé : 999 unités-jours au plus par prêt.", code="quantite_invalide")
    if origine == "portail":
        en_attente = (
            ReservationMateriel.objects.filter(dossier=dossier, statut="demandee")
            .values("stock", "reservation")
            .distinct()
            .count()
        )
        if en_attente >= DEMANDES_PORTAIL_MAX:
            raise ErreurMetier("Trop de demandes de matériel en attente sur ce dossier.", code="trop_de_demandes")
    _verifier_disponibilite(stock, quantite, debut, fin)
    pret = ReservationMateriel.objects.create(
        dossier=dossier,
        reservation=reservation,
        occurrence=occurrence,
        stock=stock,
        quantite=quantite,
        debut=debut,
        fin=fin,
        statut=_statut_initial(origine, reservation),
        origine=origine,
        commentaire=commentaire[:300],
        valeur_journaliere_centimes=stock.materiel.valeur_journaliere_centimes,
        prestation_code=stock.materiel.prestation_code,
        cree_par=_agent(acteur),
    )
    journaliser(
        "reserver_materiel", pret, apres={"quantite": quantite, "origine": origine, "statut": pret.statut}, acteur=_agent(acteur)
    )
    return pret


@transaction.atomic
def reserver_pour_reservation(
    reservation: Reservation, stock: Stock, quantite: int, *, acteur: Any, origine: str = "backoffice", commentaire: str = ""
) -> list[ReservationMateriel]:
    """Un prêt par séance à venir de la réservation : tout ou rien (la première séance indisponible est indiquée)."""
    seances = list(
        reservation.occurrences.exclude(statut__in=(*SEANCES_INACTIVES, "realisee", "cloturee"))
        .filter(debut__gte=timezone.now())
        .order_by("debut")[:400]
    )
    if not seances:
        raise ErreurMetier("Cette réservation n'a plus de séance à venir.", code="reservation_sans_seance")
    return [
        reserver(reservation.dossier, stock, quantite, acteur=acteur, occurrence=o, origine=origine, commentaire=commentaire)
        for o in seances
    ]


def _verrouiller(pret: ReservationMateriel) -> ReservationMateriel:
    return (
        ReservationMateriel.objects.select_for_update(of=("self",))
        .select_related("stock__materiel", "dossier__usager", "reservation", "occurrence")
        .get(pk=pret.pk)
    )


@transaction.atomic
def valider(pret: ReservationMateriel, *, acteur: Any) -> ReservationMateriel:
    pret = _verrouiller(pret)
    _controler(acteur, "creer_reservation", pret)
    if pret.statut != "demandee":
        raise ErreurMetier("Seule une demande se valide.", code="statut_pret")
    _verifier_article(pret.stock.materiel, pret.origine)
    if (pret.reservation is not None and pret.reservation.statut in SEANCES_INACTIVES) or (
        pret.occurrence is not None and pret.occurrence.statut in SEANCES_INACTIVES
    ):
        raise ErreurMetier("La réservation ou la séance de ce prêt est refusée ou annulée.", code="reservation_inactive")
    _verrouiller_stock(pret.stock_id)
    _verifier_disponibilite(pret.stock, pret.quantite, pret.debut, pret.fin, exclure=pret.pk)
    pret.statut = "validee"
    pret.save(update_fields=["statut"])
    journaliser("valider_pret_materiel", pret, acteur=_agent(acteur))
    return pret


def _crediter(pret: ReservationMateriel, acteur: Any, motif: str) -> None:
    """Un prêt facturé puis annulé est crédité par avoir sur la ligne de sa séance (TAR-05)."""
    if not pret.prestation_code or pret.occurrence is None:
        return
    from apps.finances import facturation

    facturation.crediter_prestations(pret.occurrence, pret.prestation_code, quantite=pret.quantite, acteur=acteur, motif=motif)


def _annuler(pret: ReservationMateriel, motif: str, acteur: Any = SYSTEME) -> None:
    ancien = pret.statut
    pret.statut, pret.motif = ("refusee" if ancien == "demandee" else "annulee"), motif[:300]
    pret.save(update_fields=["statut", "motif"])
    journaliser("annuler_pret_materiel", pret, avant={"statut": ancien}, apres={"motif": pret.motif}, acteur=_agent(acteur))
    if ancien == "validee":
        _crediter(pret, acteur, motif)


@transaction.atomic
def refuser(pret: ReservationMateriel, *, acteur: Any, motif: str) -> ReservationMateriel:
    pret = _verrouiller(pret)
    _controler(acteur, "creer_reservation", pret)
    if pret.statut not in STATUTS_EN_COURS:
        raise ErreurMetier("Ce prêt ne peut plus être refusé.", code="statut_pret")
    if len(motif.strip()) < 3:
        raise ErreurValidation("Indiquez le motif.", code="motif_requis")
    _annuler(pret, motif.strip(), acteur)
    return pret


@transaction.atomic
def sortir(pret: ReservationMateriel, *, acteur: Any, quantite: int | None = None) -> ReservationMateriel:
    """Remise à l'usager : la quantité sortie ne dépasse ni le prêt ni les unités présentes. Un équipement fixe ne sort pas."""
    pret = _verrouiller(pret)
    _controler(acteur, "gerer_materiel", pret)
    if pret.statut != "validee":
        raise ErreurMetier("Seul un prêt validé sort du stock.", code="statut_pret")
    if pret.stock.materiel.nature == "fixe":
        raise ErreurMetier("Un équipement fixe reste dans son espace.", code="materiel_fixe")
    quantite = pret.quantite if quantite is None else quantite
    stock = _verrouiller_stock(pret.stock_id)
    sur_place = presents(stock)
    if not 1 <= quantite <= pret.quantite or quantite > sur_place:
        raise ErreurMetier(f"Sortie impossible : {sur_place} unité(s) en état sur place.", code="quantite_invalide")
    pret.statut, pret.quantite_sortie, pret.quantite_rendue = "sortie", quantite, 0
    pret.save(update_fields=["statut", "quantite_sortie", "quantite_rendue"])
    _mouvement("sortie", stock, quantite, acteur, motif=f"Prêt — dossier {pret.dossier.numero}", reservation=pret)
    return pret


@transaction.atomic
def rendre(
    pret: ReservationMateriel, *, acteur: Any, quantite: int, observations: str = "", solde: bool = True
) -> ReservationMateriel:
    """Retour (R5-03), éventuellement en plusieurs fois (`solde=False`). Au solde, le non-rendu d'un consommable est
    consommé ; sinon les unités manquantes sont retirées du stock (perte) et signalées au service, qui statue
    (retenue sur la caution ou prise en charge) avant la restitution de la caution."""
    pret = _verrouiller(pret)
    _controler(acteur, "gerer_materiel", pret)
    if pret.statut != "sortie" or pret.quantite_sortie is None:
        raise ErreurMetier("Seul un prêt sorti se rend.", code="statut_pret")
    restant = pret.quantite_sortie - (pret.quantite_rendue or 0)
    if not 0 <= quantite <= restant:
        raise ErreurValidation(f"Quantité rendue entre 0 et {restant}.", code="quantite_invalide")
    stock = _verrouiller_stock(pret.stock_id)
    pret.quantite_rendue = (pret.quantite_rendue or 0) + quantite
    if quantite:
        _mouvement("retour", stock, quantite, acteur, motif=f"Retour — dossier {pret.dossier.numero}", reservation=pret)
    if not solde and pret.quantite_rendue < pret.quantite_sortie:
        pret.save(update_fields=["quantite_rendue"])
        return pret
    pret.statut = "rendue"
    ecart = pret.quantite_sortie - pret.quantite_rendue
    if ecart:
        if stock.materiel.nature == "consommable":
            _mouvement("consommation", stock, ecart, acteur, motif=f"Consommé — dossier {pret.dossier.numero}", reservation=pret)
            pret.manquants_regles = True
        else:
            pret.manquants = ecart
            pret.signalement = f"{ecart} {stock.materiel.unite}(s) manquant(s) au retour. {observations}".strip()[:300]
            _mouvement(
                "perte", stock, ecart, acteur, motif=f"Manquant au retour — dossier {pret.dossier.numero}", reservation=pret
            )
            notifier(
                "materiel_manquant",
                {
                    "materiel": str(stock.materiel),
                    "manquants": ecart,
                    "dossier": pret.dossier.numero,
                    "usager": pret.dossier.usager.nom,
                    "lien": f"{settings.BACKOFFICE_URL}/materiel/prets",
                },
                courriels=[str(parametre("portail.service_courriel"))],
                objet=pret,
            )
        stock.quantite -= ecart
        stock.hors_service = min(stock.hors_service, stock.quantite)
        stock.save(update_fields=["quantite", "hors_service"])
        if stock.materiel.nature != "consommable":
            _signaler_prets_touches(stock, "Matériel manquant au retour")
    else:
        pret.manquants_regles = True
    pret.save(update_fields=["statut", "quantite_rendue", "manquants", "manquants_regles", "signalement"])
    return pret


@transaction.atomic
def retrouver(pret: ReservationMateriel, *, acteur: Any, quantite: int) -> ReservationMateriel:
    """Unités manquantes rapportées plus tard : elles réintègrent le stock (mouvement d'entrée tracé)."""
    pret = _verrouiller(pret)
    _controler(acteur, "gerer_materiel", pret)
    if not 1 <= quantite <= pret.manquants:
        raise ErreurValidation(f"Entre 1 et {pret.manquants} unité(s).", code="quantite_invalide")
    stock = _verrouiller_stock(pret.stock_id)
    stock.quantite += quantite
    stock.save(update_fields=["quantite"])
    pret.manquants -= quantite
    pret.quantite_rendue = (pret.quantite_rendue or 0) + quantite
    pret.manquants_regles = pret.manquants_regles or pret.manquants == 0
    pret.save(update_fields=["manquants", "quantite_rendue", "manquants_regles"])
    _mouvement("entree", stock, quantite, acteur, motif=f"Rapporté après coup — dossier {pret.dossier.numero}", reservation=pret)
    return pret


@transaction.atomic
def regler_manquants(pret: ReservationMateriel, *, acteur: Any, decision: str) -> ReservationMateriel:
    """Le service statue sur les manquants (retenue proposée sur la caution, prise en charge par la Ville…)."""
    pret = _verrouiller(pret)
    _controler(acteur, "gerer_materiel", pret)
    if not pret.manquants or pret.manquants_regles:
        raise ErreurMetier("Aucun manquant en attente de décision.", code="sans_manquant")
    if len(decision.strip()) < 5:
        raise ErreurValidation("Indiquez la décision.", code="decision_requise")
    pret.manquants_regles = True
    pret.signalement = f"{pret.signalement} Décision : {decision.strip()}"[:300]
    pret.save(update_fields=["manquants_regles", "signalement"])
    journaliser("regler_manquants_materiel", pret, apres={"decision": decision.strip()[:200]}, acteur=_agent(acteur))
    return pret


def blocage_caution(caution: Any) -> str | None:
    """Vérification enregistrée auprès des cautions (RG-11) : pas de restitution tant que du matériel est dehors ou
    que des manquants attendent une décision."""
    prets = ReservationMateriel.objects.filter(reservation=caution.reservation)
    if prets.filter(statut="sortie").exists():
        return "du matériel prêté n'est pas rendu"
    if prets.filter(manquants__gt=0, manquants_regles=False).exists():
        return "des manquants de matériel attendent une décision (retenue ou prise en charge)"
    return None


# --- Suivi des réservations : annulation, refus, déplacement --------------------------------------------------


def apres_annulation(occurrence: Occurrence) -> None:
    """Crochet des réservations : la séance annulée libère son matériel non sorti (avoir s'il était facturé)."""
    motif = "Séance annulée tardivement" if occurrence.annulation_tardive else "Séance annulée"
    for pret in ReservationMateriel.objects.select_for_update(of=("self",)).filter(
        occurrence=occurrence, statut__in=STATUTS_EN_COURS
    ):
        _annuler(pret, motif)
    reservation = occurrence.reservation
    if not reservation.occurrences.exclude(statut__in=SEANCES_INACTIVES).exists():
        for pret in ReservationMateriel.objects.filter(
            reservation=reservation, occurrence__isnull=True, statut__in=STATUTS_EN_COURS
        ):
            _annuler(pret, "Réservation sans séance")


def apres_changement_statut(reservation: Reservation) -> None:
    """Refus, annulation ou expiration d'une option : le matériel est libéré ; validation : les prêts saisis au
    back-office en attente de la réservation sont validés si le stock le permet, signalés sinon."""
    prets = ReservationMateriel.objects.select_for_update(of=("self",)).filter(reservation=reservation)
    if reservation.statut in SEANCES_INACTIVES:
        for pret in prets.filter(statut__in=STATUTS_EN_COURS):
            _annuler(pret, "Réservation refusée ou annulée")
        return
    if reservation.statut in RESERVATIONS_ACCORDEES:
        for pret in prets.filter(statut="demandee", origine="backoffice").select_related("stock__materiel"):
            try:
                with transaction.atomic():
                    _verifier_disponibilite(pret.stock, pret.quantite, pret.debut, pret.fin, exclure=pret.pk)
                    pret.statut = "validee"
                    pret.save(update_fields=["statut"])
            except ErreurMetier as erreur:
                pret.signalement = erreur.message[:300]
                pret.save(update_fields=["signalement"])


def apres_deplacement(occurrence: Occurrence) -> None:
    """La séance déplacée emmène son matériel : nouvelles heures, disponibilité revérifiée, sinon signalement."""
    for pret in (
        ReservationMateriel.objects.select_for_update(of=("self",))
        .filter(occurrence=occurrence, statut__in=STATUTS_EN_COURS)
        .select_related("stock__materiel")
    ):
        if (pret.debut, pret.fin) == (
            occurrence.debut,
            occurrence.fin,
        ) and occurrence.espace.batiment.site_id == pret.stock.site_id:
            continue
        if occurrence.espace.batiment.site_id != pret.stock.site_id:
            _annuler(pret, "Séance déplacée sur un autre site")
            continue
        pret.debut, pret.fin = occurrence.debut, occurrence.fin
        try:
            _verifier_disponibilite(pret.stock, pret.quantite, pret.debut, pret.fin, exclure=pret.pk)
            pret.signalement = ""
        except ErreurMetier as erreur:
            pret.signalement = f"Séance déplacée : {erreur.message}"[:300]
            notifier(
                "materiel_indisponible",
                {
                    "materiel": str(pret.stock.materiel),
                    "lieu": str(pret.stock),
                    "prets": f"{pret.dossier.numero} ({_texte(pret.debut)})",
                    "lien": f"{settings.BACKOFFICE_URL}/materiel/prets",
                },
                courriels=[str(parametre("portail.service_courriel"))],
            )
        pret.save(update_fields=["debut", "fin", "signalement"])


def avant_suppression(occurrence: Occurrence) -> None:
    """Séance supprimée (série recalculée) : ses prêts en cours sont annulés et signalés."""
    for pret in ReservationMateriel.objects.filter(occurrence=occurrence, statut__in=STATUTS_EN_COURS):
        _annuler(pret, "Séance supprimée par la modification de la série")


def prestations_du_dossier(dossier: Dossier) -> list[dict[str, Any]]:
    """Source de lignes du devis et de la facture (TAR-04) : prêts accordés d'un matériel facturé, séance par séance
    (ou à la journée civile pour un prêt sur une période)."""
    lignes: list[dict[str, Any]] = []
    for pret in (
        dossier.materiels.filter(statut__in=["validee", "sortie", "rendue"]).exclude(prestation_code="").order_by("debut", "pk")
    ):
        quantite = pret.quantite if pret.occurrence_id else pret.quantite * jours_touches(pret.debut, pret.fin)
        lignes.append({"code": pret.prestation_code, "quantite": quantite, "occurrence": pret.occurrence_id})
    return lignes


# --- Stocks : entrée, transfert, perte, inventaire (MAT-01, MAT-03) --------------------------------------------


def stock_pour(materiel: Materiel, site: Site, espace: Espace | None = None) -> Stock:
    if espace is not None and espace.batiment.site_id != site.pk:
        raise ErreurValidation("L'espace n'appartient pas au site.", code="espace_autre_site")
    if materiel.nature == "fixe" and espace is None:
        raise ErreurValidation("Un équipement fixe est affecté à un espace.", code="espace_requis")
    stock, _ = Stock.objects.get_or_create(materiel=materiel, site=site, espace=espace)
    return stock


@transaction.atomic
def entrer(materiel: Materiel, site: Site, quantite: int, *, acteur: Any, espace: Espace | None = None, motif: str = "") -> Stock:
    stock = stock_pour(materiel, site, espace)
    _controler(acteur, "gerer_materiel", stock)
    if not 1 <= quantite <= 100_000:
        raise ErreurValidation("Quantité entre 1 et 100 000.", code="quantite_invalide")
    stock = _verrouiller_stock(stock.pk)
    stock.quantite += quantite
    stock.save(update_fields=["quantite"])
    _mouvement("entree", stock, quantite, acteur, motif=motif or "Entrée en stock")
    return stock


def _engagements_futurs(stock: Stock, en_etat: int) -> list[ReservationMateriel]:
    """Prêts à venir que le stock réduit ne couvrirait plus (un seul balayage par prêt à venir)."""
    maintenant = timezone.now()
    touches = []
    for pret in ReservationMateriel.objects.filter(stock=stock, statut="validee", fin__gt=maintenant).select_related("dossier")[
        :500
    ]:
        if pic_d_engagement(stock, max(pret.debut, maintenant), pret.fin) > en_etat:
            touches.append(pret)
    return touches


@transaction.atomic
def transferer(stock: Stock, site: Site, quantite: int, *, acteur: Any, espace: Espace | None = None, motif: str = "") -> Stock:
    """Déplacement vers un autre lieu : unités présentes seulement, et sans priver des prêts déjà validés."""
    origine = Stock.objects.select_related("materiel").get(pk=stock.pk)
    if origine.materiel.nature == "fixe":
        raise ErreurMetier("Un équipement fixe se réaffecte par une sortie d'inventaire et une entrée.", code="materiel_fixe")
    destination = stock_pour(origine.materiel, site, espace)
    _controler(acteur, "gerer_materiel", origine)
    _controler(acteur, "gerer_materiel", destination)
    if destination.pk == origine.pk:
        raise ErreurValidation("Choisissez un autre lieu.", code="meme_lieu")
    # Verrous dans l'ordre des identifiants : deux transferts croisés ne s'interbloquent pas.
    verrous = {
        s.pk: s
        for s in Stock.objects.select_for_update(of=("self",)).filter(pk__in=sorted([origine.pk, destination.pk])).order_by("pk")
    }
    origine, destination = verrous[origine.pk], verrous[destination.pk]
    sur_place = presents(origine)
    if not 1 <= quantite <= sur_place:
        raise ErreurValidation(f"Entre 1 et {sur_place} unité(s) présentes.", code="quantite_invalide")
    if _engagements_futurs(origine, origine.en_etat - quantite):
        raise ErreurMetier("Ce transfert priverait des prêts déjà validés sur le lieu d'origine.", code="prets_engages")
    origine.quantite -= quantite
    destination.quantite += quantite
    origine.save(update_fields=["quantite"])
    destination.save(update_fields=["quantite"])
    _mouvement("transfert", origine, quantite, acteur, motif=motif or "Transfert", destination=destination)
    return destination


@transaction.atomic
def declarer_perte(stock: Stock, quantite: int, *, acteur: Any, motif: str) -> Stock:
    stock = _verrouiller_stock(stock.pk)
    _controler(acteur, "gerer_materiel", stock)
    if len(motif.strip()) < 3:
        raise ErreurValidation("Indiquez le motif (vol, perte…).", code="motif_requis")
    sur_place = presents(stock)
    if not 1 <= quantite <= sur_place:
        raise ErreurValidation(f"Entre 1 et {sur_place} unité(s) présentes.", code="quantite_invalide")
    stock.quantite -= quantite
    stock.save(update_fields=["quantite"])
    _mouvement("perte", stock, quantite, acteur, motif=motif)
    _signaler_prets_touches(stock, "Matériel perdu ou volé : quantité réduite")
    return stock


@transaction.atomic
def inventorier(stock: Stock, quantite_comptee: int, *, acteur: Any, motif: str = "") -> Stock:
    """Ajustement à la quantité comptée sur place (unités hors service comprises) ; les unités sorties en prêt
    restent au stock ; l'écart est tracé."""
    stock = _verrouiller_stock(stock.pk)
    _controler(acteur, "gerer_materiel", stock)
    dehors = sortis(stock)
    nouvelle = quantite_comptee + dehors
    if nouvelle < stock.hors_service:
        raise ErreurValidation(f"Au moins {stock.hors_service} unité(s) hors service sont comptées.", code="quantite_invalide")
    ecart = nouvelle - stock.quantite
    if ecart == 0:
        return stock
    stock.quantite = nouvelle
    stock.save(update_fields=["quantite"])
    _mouvement("inventaire", stock, ecart, acteur, motif=(motif or "Inventaire") + (f" ({dehors} en prêt)" if dehors else ""))
    if ecart < 0:
        _signaler_prets_touches(stock, "Inventaire : quantité réduite")
    return stock


def _signaler_prets_touches(stock: Stock, motif: str) -> int:
    """Prêts à venir que le stock ne couvre plus : signalés sur le prêt et au service (MAT-05)."""
    touches = _engagements_futurs(stock, stock.en_etat)
    for pret in touches:
        pret.signalement = f"{motif} : prêt du {_texte(pret.debut)} à revoir"[:300]
        pret.save(update_fields=["signalement"])
    if touches:
        notifier(
            "materiel_indisponible",
            {
                "materiel": str(stock.materiel),
                "lieu": str(stock),
                "prets": ", ".join(f"{p.dossier.numero} ({_texte(p.debut)})" for p in touches[:30]),
                "lien": f"{settings.BACKOFFICE_URL}/materiel/prets",
            },
            courriels=[str(parametre("portail.service_courriel"))],
        )
    return len(touches)


# --- Pannes (MAT-05) -------------------------------------------------------------------------------------------


@transaction.atomic
def signaler_panne(
    stock: Stock, *, acteur: Any, quantite: int = 1, description: str, source: str = "backoffice", incident: Any = None
) -> Panne:
    """Les unités en panne (présentes sur place) sortent de la disponibilité : elles ne sont plus réservables (R5-05)."""
    stock = _verrouiller_stock(stock.pk)
    if source != "controle":
        _controler(acteur, "signaler_panne_materiel", stock)
    if len(description.strip()) < 5:
        raise ErreurValidation("Décrivez la panne.", code="description_requise")
    sur_place = presents(stock)
    if not 1 <= quantite <= sur_place:
        raise ErreurValidation(f"Entre 1 et {sur_place} unité(s) présentes.", code="quantite_invalide")
    stock.hors_service += quantite
    stock.save(update_fields=["hors_service"])
    panne = Panne.objects.create(
        stock=stock,
        quantite=quantite,
        description=description.strip()[:2000],
        source=source,
        incident=incident,
        signalee_par=_agent(acteur),
    )
    _mouvement("panne", stock, quantite, acteur, motif=description.strip()[:200])
    _signaler_prets_touches(stock, f"{stock.materiel} en panne")
    return panne


@transaction.atomic
def resoudre_panne(panne: Panne, *, acteur: Any, issue: str, resolution: str = "") -> Panne:
    panne = Panne.objects.select_for_update(of=("self",)).select_related("stock").get(pk=panne.pk)
    _controler(acteur, "gerer_materiel", panne)
    if panne.statut != "ouverte":
        raise ErreurMetier("Cette panne est déjà résolue.", code="panne_resolue")
    if issue not in ("reparee", "rebut"):
        raise ErreurValidation("Issue : « reparee » ou « rebut ».", code="issue_invalide")
    if issue == "reparee" and panne.source == "controle":
        conforme = Controle.objects.filter(stock_id=panne.stock_id, conforme=True, cree_le__gt=panne.signalee_le).exists()
        if not conforme:
            raise ErreurMetier(
                "Équipement mis hors service par un contrôle : un contrôle conforme précède la remise en service.",
                code="controle_conforme_requis",
            )
    stock = _verrouiller_stock(panne.stock_id)
    stock.hors_service -= panne.quantite
    if issue == "rebut":
        stock.quantite -= panne.quantite
    stock.save(update_fields=["hors_service", "quantite"])
    panne.statut, panne.resolue_le, panne.resolution = issue, timezone.now(), resolution.strip()[:2000]
    panne.save(update_fields=["statut", "resolue_le", "resolution"])
    _mouvement("reparation" if issue == "reparee" else "rebut", stock, panne.quantite, acteur, motif=resolution[:200])
    return panne


# --- Contrôles périodiques (MAT-04) ----------------------------------------------------------------------------


@transaction.atomic
def enregistrer_controle(
    stock: Stock,
    *,
    acteur: Any,
    realise_le: date,
    nature: str = "controle",
    conforme: bool = True,
    observations: str = "",
    prestataire: str = "",
) -> Controle:
    """Un contrôle non conforme met les unités présentes hors service (sécurité des usagers) jusqu'à un contrôle conforme ;
    l'échéance suivante ne court que d'un contrôle conforme."""
    stock = _verrouiller_stock(stock.pk)
    _controler(acteur, "gerer_materiel", stock)
    if realise_le > timezone.localdate():
        raise ErreurValidation("Un contrôle se déclare une fois réalisé.", code="date_future")
    if not conforme and len(observations.strip()) < 5:
        raise ErreurValidation("Décrivez la non-conformité.", code="observations_requises")
    periodicite = stock.materiel.periodicite_controle_jours
    controle = Controle.objects.create(
        stock=stock,
        nature=nature,
        realise_le=realise_le,
        conforme=conforme,
        observations=observations.strip()[:4000],
        prestataire=prestataire.strip()[:150],
        prochain_le=realise_le + timedelta(days=periodicite) if periodicite and nature == "controle" and conforme else None,
        agent=_agent(acteur),
    )
    if nature == "controle" and conforme and (stock.dernier_controle is None or realise_le >= stock.dernier_controle):
        stock.dernier_controle = realise_le
        stock.save(update_fields=["dernier_controle"])
    journaliser("controle_materiel", controle, apres={"conforme": conforme}, acteur=_agent(acteur))
    sur_place = presents(stock)
    if not conforme and sur_place:
        signaler_panne(
            stock, acteur=acteur, quantite=sur_place, description=f"Contrôle non conforme : {observations}", source="controle"
        )
    return controle


def echeance_controle(stock: Stock) -> date | None:
    periodicite = stock.materiel.periodicite_controle_jours
    if not periodicite:
        return None
    if stock.dernier_controle is None:
        return timezone.localdate()
    return stock.dernier_controle + timedelta(days=periodicite)


def controles_en_retard(stocks: Iterable[Stock], jour: date | None = None) -> list[tuple[Stock, date]]:
    """MAT-04 : stocks dont l'échéance du contrôle est dépassée (jamais contrôlés compris)."""
    jour = jour or timezone.localdate()
    retard = []
    for stock in stocks:
        echeance = echeance_controle(stock)
        if echeance is not None and stock.quantite and (stock.dernier_controle is None or echeance < jour):
            retard.append((stock, echeance))
    return sorted(retard, key=lambda r: r[1])


def stocks_sous_seuil(stocks: Iterable[Stock]) -> list[Stock]:
    return [s for s in stocks if s.materiel.seuil_alerte is not None and s.en_etat < s.materiel.seuil_alerte]


def alerter_controles() -> int:
    """Tâche hebdomadaire : le service reçoit la liste des contrôles dépassés et des consommables sous le seuil."""
    stocks = list(Stock.objects.filter(materiel__actif=True).select_related("materiel", "site", "espace"))
    retards, seuils = controles_en_retard(stocks), stocks_sous_seuil(stocks)
    if not retards and not seuils:
        return 0
    lignes = [f"- {s} : contrôle attendu le {e:%d/%m/%Y}" for s, e in retards] + [
        f"- {s} : {s.en_etat} en stock (seuil {s.materiel.seuil_alerte})" for s in seuils
    ]
    notifier(
        "materiel_alertes",
        {"nombre": len(lignes), "lignes": "\n".join(lignes[:100]), "lien": f"{settings.BACKOFFICE_URL}/materiel/controles"},
        courriels=[str(parametre("portail.service_courriel"))],
    )
    return len(lignes)


# --- État du stock (MAT-03) -------------------------------------------------------------------------------------


def etat_du_stock(stocks: Iterable[Stock]) -> list[dict[str, Any]]:
    from django.db.models import Count, F, Sum

    liste = list(stocks)
    maintenant = timezone.now()
    dehors = {
        ligne["stock"]: int(ligne["s"] or 0)
        for ligne in ReservationMateriel.objects.filter(stock__in=liste, statut="sortie")
        .values("stock")
        .annotate(s=Sum(F("quantite_sortie") - F("quantite_rendue")))
    }
    a_venir = {
        ligne["stock"]: ligne["n"]
        for ligne in ReservationMateriel.objects.filter(stock__in=liste, statut="validee", fin__gt=maintenant)
        .values("stock")
        .annotate(n=Count("pk"))
    }
    lignes = []
    for stock in liste:
        hors = dehors.get(stock.pk, 0)
        lignes.append(
            {
                "stock": stock,
                "quantite": stock.quantite,
                "hors_service": stock.hors_service,
                "sortis": hors,
                "sur_place": max(0, stock.en_etat - hors),
                "prets_a_venir": a_venir.get(stock.pk, 0),
                "echeance_controle": echeance_controle(stock),
                "sous_seuil": stock.materiel.seuil_alerte is not None and stock.en_etat < stock.materiel.seuil_alerte,
            }
        )
    return lignes
