"""Pilotage (lot 6) : statistiques d'occupation, de répartition, de recettes et de personnel (STA-01 à STA-05),
tableau de bord « que dois-je traiter aujourd'hui ? » et alertes (DSH-01 à DSH-03, DSH-05, DSH-06), tableau de bord
de la direction (DSH-04). Tout est calculé dans le périmètre de l'agent (RG-14)."""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from datetime import UTC, date, datetime, time, timedelta
from typing import Any

from django.db.models import Q, QuerySet, Sum
from django.utils import timezone

from apps.habilitations.models import Utilisateur
from apps.habilitations.services import peut, sites_autorises
from apps.noyau.parametres import parametre
from apps.referentiel.models import Espace, Fermeture, HoraireOuverture
from apps.reservations.models import Occurrence, Reservation
from apps.reservations.recurrence import PARIS

STATUTS_OCCUPES = ("validee", "confirmee", "realisee", "cloturee")
TYPES_USAGER = {
    "association": "Associations",
    "ecole": "Écoles",
    "entreprise": "Entreprises",
    "particulier": "Particuliers",
    "service_municipal": "Services municipaux",
    "autre_collectivite": "Autres collectivités",
}


def bornes(du: date, au: date) -> tuple[datetime, datetime]:
    return datetime.combine(du, time.min, tzinfo=PARIS), datetime.combine(au + timedelta(days=1), time.min, tzinfo=PARIS)


def _minutes(a: datetime, b: datetime) -> float:
    """Durée réelle, en UTC : une soustraction en heure de Paris se trompe d'une heure au changement d'heure."""
    return max(0.0, (b.astimezone(UTC) - a.astimezone(UTC)).total_seconds() / 60)


def _intersection(debut: datetime, fin: datetime, periode: tuple[datetime, datetime]) -> float:
    return _minutes(max(debut, periode[0]), min(fin, periode[1]))


def espaces_du_perimetre(agent: Utilisateur, action: str, site: int | None = None, espace: int | None = None) -> QuerySet[Espace]:
    qs = Espace.objects.filter(actif=True).select_related("batiment__site", "famille")
    sites = sites_autorises(agent, action)
    if sites is not None:
        qs = qs.filter(batiment__site__in=sites)
    if site:
        qs = qs.filter(batiment__site_id=site)
    if espace:
        qs = qs.filter(pk=espace)
    return qs.order_by("batiment__site__nom", "nom")


# --- STA-01 : taux d'occupation --------------------------------------------------------------------------------
#
# Revue métier du lot 6 (M9, M10, m9) : horaires de saison prioritaires (comme le contrôle des réservations), jours
# de vacances, fériés et fermetures (de l'espace, de ses parents et du site) retirés ; l'occupation d'un espace est
# l'union des créneaux qui le bloquent (lui, ses parents, ses sous-espaces — REF-05), ce qui ne compte jamais deux
# fois un espace partageable ; une séance hors horaires élargit d'autant les heures d'ouverture (taux ≤ 100 %) ; un
# site ne compte que ses espaces de premier niveau. Durées calculées en UTC (changement d'heure).

Intervalle = tuple[datetime, datetime]


def _union(intervalles: list[Intervalle]) -> list[Intervalle]:
    fusion: list[Intervalle] = []
    for debut, fin in sorted(i for i in intervalles if i[1] > i[0]):
        if fusion and debut <= fusion[-1][1]:
            fusion[-1] = (fusion[-1][0], max(fusion[-1][1], fin))
        else:
            fusion.append((debut, fin))
    return fusion


def _intersecter(a: list[Intervalle], b: list[Intervalle]) -> list[Intervalle]:
    resultat, i, j = [], 0, 0
    while i < len(a) and j < len(b):
        debut, fin = max(a[i][0], b[j][0]), min(a[i][1], b[j][1])
        if debut < fin:
            resultat.append((debut, fin))
        if a[i][1] < b[j][1]:
            i += 1
        else:
            j += 1
    return resultat


def _soustraire(a: list[Intervalle], b: list[Intervalle]) -> list[Intervalle]:
    resultat: list[Intervalle] = []
    for debut, fin in a:
        courant = debut
        for b_debut, b_fin in b:
            if b_fin <= courant or b_debut >= fin:
                continue
            if b_debut > courant:
                resultat.append((courant, b_debut))
            courant = max(courant, b_fin)
        if courant < fin:
            resultat.append((courant, fin))
    return resultat


def _duree(intervalles: list[Intervalle]) -> float:
    return sum(_minutes(debut, fin) for debut, fin in intervalles)


def _utc(jour: date, heure: time) -> datetime:
    return datetime.combine(jour, heure, tzinfo=PARIS).astimezone(UTC)


@dataclass
class Calendrier:
    """Ce qui se charge une fois pour une période : fériés, vacances, plage par défaut, arbre des espaces."""

    du: date
    au: date
    feries: set[date]
    vacances: set[date]
    defaut: tuple[time, time]
    parents: dict[int, int | None]

    @classmethod
    def charger(cls, du: date, au: date) -> Calendrier:
        from apps.referentiel.calendrier import jours_particuliers

        feries, vacances = jours_particuliers(du, au)
        defaut = parametre("statistiques.ouverture_defaut")
        return cls(
            du,
            au,
            feries,
            vacances,
            (time.fromisoformat(defaut["debut"]), time.fromisoformat(defaut["fin"])),
            dict(Espace.objects.values_list("pk", "parent_id")),
        )

    def ancetres(self, espace_id: int) -> set[int]:
        vus: set[int] = set()
        courant = self.parents.get(espace_id)
        while courant is not None and courant not in vus:
            vus.add(courant)
            courant = self.parents.get(courant)
        return vus

    def descendants(self, espace_id: int) -> set[int]:
        enfants: dict[int, list[int]] = defaultdict(list)
        for fils, pere in self.parents.items():
            if pere is not None:
                enfants[pere].append(fils)
        resultat: set[int] = set()
        pile = list(enfants.get(espace_id, []))
        while pile:
            fils = pile.pop()
            if fils not in resultat:
                resultat.add(fils)
                pile.extend(enfants.get(fils, []))
        return resultat


def plages_ouverture(
    espace: Espace, calendrier: Calendrier, horaires: list[HoraireOuverture], fermetures: list[Fermeture]
) -> list[Intervalle]:
    """Heures d'ouverture de l'espace sur la période (UTC) : horaires de la saison du jour en priorité, sinon horaires
    permanents, sinon plage par défaut paramétrée ; hors fériés, vacances (sauf plages « pendant les vacances ») et
    fermetures de l'espace, de ses parents ou du site."""
    plages: list[Intervalle] = []
    jour = calendrier.du
    while jour <= calendrier.au:
        if jour not in calendrier.feries:
            if horaires:
                du_jour = [h for h in horaires if h.jour_semaine == jour.weekday()]
                propres = [h for h in du_jour if h.saison is not None and h.saison.debut <= jour <= h.saison.fin]
                candidates = propres or [h for h in du_jour if h.saison_id is None]
                if jour in calendrier.vacances:
                    candidates = [h for h in candidates if h.pendant_vacances]
                for h in candidates:
                    fin = _utc(jour + timedelta(days=1), time.min) if h.fin >= time(23, 59) else _utc(jour, h.fin)
                    plages.append((_utc(jour, h.debut), fin))
            else:
                plages.append((_utc(jour, calendrier.defaut[0]), _utc(jour, calendrier.defaut[1])))
        jour += timedelta(days=1)
    concernes = {espace.pk, *calendrier.ancetres(espace.pk)}
    fermees = _union(
        [
            (f.debut.astimezone(UTC), f.fin.astimezone(UTC))
            for f in fermetures
            if f.espace_id in concernes or (f.site_id is not None and f.site_id == espace.batiment.site_id)
        ]
    )
    return _soustraire(_union(plages), fermees)


def minutes_ouverture(espace: Espace, du: date, au: date) -> float:
    """Minutes d'ouverture d'un espace sur la période (voir `plages_ouverture`)."""
    calendrier = Calendrier.charger(du, au)
    periode = bornes(du, au)
    return _duree(
        plages_ouverture(
            espace,
            calendrier,
            list(HoraireOuverture.objects.filter(espace=espace).select_related("saison")),
            list(Fermeture.objects.filter(debut__lt=periode[1], fin__gt=periode[0])),
        )
    )


def occupation(espaces: QuerySet[Espace], du: date, au: date) -> list[dict[str, Any]]:
    """Par espace : minutes occupées (union des séances validées, confirmées, réalisées qui le bloquent, bornée à ses
    heures d'ouverture) sur minutes d'ouverture."""
    liste = list(espaces)
    if not liste:
        return []
    calendrier = Calendrier.charger(du, au)
    periode = bornes(du, au)
    lies = {e.pk: {e.pk, *calendrier.ancetres(e.pk), *calendrier.descendants(e.pk)} for e in liste}
    tous = set().union(*lies.values())
    seances: dict[int, list[Intervalle]] = defaultdict(list)
    for espace_id, debut, fin in Occurrence.objects.filter(
        espace_id__in=tous, statut__in=STATUTS_OCCUPES, debut__lt=periode[1], fin__gt=periode[0]
    ).values_list("espace_id", "debut", "fin"):
        seances[espace_id].append((debut.astimezone(UTC), fin.astimezone(UTC)))
    horaires: dict[int, list[HoraireOuverture]] = defaultdict(list)
    for h in HoraireOuverture.objects.filter(espace__in=liste).select_related("saison"):
        horaires[h.espace_id].append(h)
    fermetures = list(
        Fermeture.objects.filter(
            Q(espace_id__in=tous) | Q(site__in={e.batiment.site_id for e in liste}), debut__lt=periode[1], fin__gt=periode[0]
        )
    )
    ids = {e.pk for e in liste}
    lignes = []
    for espace in liste:
        ouvertes = plages_ouverture(espace, calendrier, horaires.get(espace.pk, []), fermetures)
        periode_utc = [(periode[0].astimezone(UTC), periode[1].astimezone(UTC))]
        occupees = _intersecter(_union([s for i in lies[espace.pk] for s in seances.get(i, [])]), periode_utc)
        # Une séance tenue hors des horaires (jour férié, soirée prolongée) a bien occupé l'espace : elle compte, et
        # son temps s'ajoute aux heures d'ouverture (le taux reste au plus de 100 %).
        ouvert, occupe = _duree(_union(ouvertes + occupees)), _duree(occupees)
        lignes.append(
            {
                "espace": espace.pk,
                "espace_nom": espace.nom,
                "parent": espace.parent_id,
                "premier_niveau": not (calendrier.ancetres(espace.pk) & ids),
                "site": espace.batiment.site_id,
                "site_nom": espace.batiment.site.nom,
                "famille": espace.famille.libelle if espace.famille_id else "",
                "minutes_reservees": round(occupe),
                "minutes_ouverture": round(ouvert),
                "taux": round(10000 * occupe / ouvert) if ouvert else 0,
            }
        )
    return lignes


def occupation_par_site(lignes: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Un site additionne ses espaces de premier niveau : les sous-espaces sont déjà dans l'occupation du parent."""
    sites: dict[int, dict[str, Any]] = {}
    for ligne in lignes:
        if not ligne.get("premier_niveau", True):
            continue
        site = sites.setdefault(
            ligne["site"], {"site": ligne["site"], "site_nom": ligne["site_nom"], "minutes_reservees": 0, "minutes_ouverture": 0}
        )
        site["minutes_reservees"] += ligne["minutes_reservees"]
        site["minutes_ouverture"] += ligne["minutes_ouverture"]
    for site in sites.values():
        site["taux"] = round(10000 * site["minutes_reservees"] / site["minutes_ouverture"]) if site["minutes_ouverture"] else 0
    return sorted(sites.values(), key=lambda s: s["site_nom"])


# --- STA-02 : répartition par type d'usager et activité ---------------------------------------------------------


def repartition(espaces: QuerySet[Espace], du: date, au: date) -> dict[str, list[dict[str, Any]]]:
    periode = bornes(du, au)
    par_type: dict[str, float] = defaultdict(float)
    par_activite: dict[str, float] = defaultdict(float)
    par_famille: dict[str, float] = defaultdict(float)
    for type_usager, activite, famille, debut, fin in Occurrence.objects.filter(
        espace__in=espaces, statut__in=STATUTS_OCCUPES, debut__lt=periode[1], fin__gt=periode[0]
    ).values_list(
        "reservation__dossier__usager__type", "reservation__dossier__activite", "espace__famille__libelle", "debut", "fin"
    ):
        minutes = _intersection(debut, fin, periode)
        par_type[type_usager] += minutes
        par_activite[(activite or "Non précisée").strip().capitalize()] += minutes
        par_famille[famille or "Sans famille"] += minutes
    total = sum(par_type.values()) or 1

    def liste(source: dict[str, float], libelles: dict[str, str] | None = None) -> list[dict[str, Any]]:
        return [
            {"cle": cle, "libelle": (libelles or {}).get(cle, cle), "minutes": round(v), "part": round(10000 * v / total)}
            for cle, v in sorted(source.items(), key=lambda e: -e[1])
        ]

    return {"types_usager": liste(par_type, TYPES_USAGER), "activites": liste(par_activite)[:30], "familles": liste(par_famille)}


# --- STA-03 : recettes, gratuités et réductions -----------------------------------------------------------------


def _site_de_ligne(ligne: Any) -> int | None:
    espace = ligne.espace or (ligne.occurrence.espace if ligne.occurrence_id else None)
    return espace.batiment.site_id if espace is not None else None


def recettes(agent: Utilisateur, du: date, au: date, site: int | None = None) -> dict[str, Any]:
    """STA-03 (revue métier du lot 6, M11) : pièces émises sur la période. Facturé = toutes les factures (y compris
    celles ensuite créditées), moins tous les avoirs : une séance facturée puis créditée compte 0. Reste dû = montant
    dû de chaque facture, acompte déduit, moins avoirs et règlements. Un agent limité à des sites (ou un filtre de
    site) ne voit que les lignes de ces sites ; règlement et reste dû d'une facture multi-sites sont proratisés.
    Réductions partielles et gratuités (réduction de 100 %) sont distinguées ; les concours en nature (toute la
    Ville) ne sont donnés qu'à qui lit la valorisation sur tous les sites."""
    from apps.finances.models import LigneComptable, PieceComptable
    from apps.noyau.montants import proratiser

    periode = bornes(du, au)
    autorises = sites_autorises(agent, "lire_finances")
    retenus: set[int] | None = None if autorises is None else set(autorises)
    if site:
        retenus = {site} if retenus is None else retenus & {site}
    pieces = (
        PieceComptable.objects.filter(
            numero__isnull=False, nature__in=["facture", "avoir", "acompte"], emise_le__gte=periode[0], emise_le__lt=periode[1]
        )
        .select_related("dossier")
        .prefetch_related("lignes__espace__batiment", "lignes__occurrence__espace__batiment")
    )
    resultat = {"factures": 0, "emis": 0, "avoirs": 0, "regle": 0, "reste_du": 0, "reductions": 0, "gratuites": 0}
    for piece in pieces:
        lignes = [ligne for ligne in piece.lignes.all() if ligne.nature != "acompte"]
        if piece.nature == "acompte":
            # Facture d'acompte : elle sera déduite de la facture de solde (déjà comptée au facturé) ; son règlement
            # compte au réglé, pour la Ville entière ou si le dossier porte sur un site retenu.
            if retenus is None or piece.dossier.reservations.filter(espace__batiment__site__in=retenus).exists():
                resultat["regle"] += piece.montant_regle
            continue
        retenues = lignes if retenus is None else [ligne for ligne in lignes if _site_de_ligne(ligne) in retenus]
        if not retenues:
            continue
        montant = sum(ligne.montant_du for ligne in retenues)
        if piece.nature == "avoir":
            resultat["avoirs"] += abs(montant)
            continue
        resultat["factures"] += 1
        resultat["emis"] += montant
        total = sum(ligne.montant_du for ligne in lignes)
        reste = max(0, piece.reste_du)
        if total > 0 and montant != total:
            resultat["regle"] += proratiser(piece.montant_regle, montant, total)
            resultat["reste_du"] += proratiser(reste, montant, total)
        else:
            resultat["regle"] += piece.montant_regle
            resultat["reste_du"] += reste
        for ligne in retenues:
            ecart = max(0, ligne.montant_reference - ligne.montant_du)
            resultat["gratuites" if ligne.taux_reduction >= 10000 else "reductions"] += ecart
    concours: int | None = None
    if peut(agent, "lire_valorisation") and sites_autorises(agent, "lire_valorisation") is None and not site:
        from apps.valorisation.models import Valorisation

        concours = int(Valorisation.objects.filter(exercice__annee=du.year, actuelle=True).aggregate(s=Sum("total"))["s"] or 0)
    _ = LigneComptable
    return {**resultat, "net": resultat["emis"] - resultat["avoirs"], "concours_en_nature": concours}


# --- STA-05 : indicateurs de personnel -------------------------------------------------------------------------


def indicateurs_personnel(agent: Utilisateur, du: date, au: date, site: int | None = None) -> dict[str, Any]:
    from apps.personnel.models import Agent
    from apps.personnel.services import compteurs

    agents = Agent.objects.filter(actif=True)
    sites = sites_autorises(agent, "lire_personnel")
    if sites is not None:
        agents = agents.filter(sites__in=sites)
    if site:
        agents = agents.filter(sites=site)
    lignes = compteurs(agents.distinct(), du, au)
    total = {
        cle: sum(ligne[cle] for ligne in lignes)
        for cle in ("planifiees", "realisees", "supplementaires", "nuit", "dimanches_feries", "astreintes")
    }
    return {"agents": len(lignes), **total}


# --- DSH-01 à DSH-03 : « que dois-je traiter aujourd'hui ? » ----------------------------------------------------


@dataclass
class Compteur:
    code: str
    libelle: str
    nombre: int
    lien: str
    groupe: str = "a_traiter"
    gravite: str = "info"

    def en_dict(self) -> dict[str, Any]:
        return {
            "code": self.code,
            "libelle": self.libelle,
            "nombre": self.nombre,
            "lien": self.lien,
            "groupe": self.groupe,
            "gravite": self.gravite,
        }


def _sur_site(qs: QuerySet[Any], agent: Utilisateur, action: str, chemin: str) -> QuerySet[Any]:
    sites = sites_autorises(agent, action)
    return qs if sites is None else qs.filter(**{f"{chemin}__in": sites}).distinct()


def _compteurs_attestations(agent: Utilisateur, aujourd_hui: date) -> list[Compteur]:
    """VAL-04 (M7) : attestations du dernier exercice clos restant à déposer, avec leur date limite."""
    compteurs: list[Compteur] = []
    if peut(agent, "calculer_valorisation") and sites_autorises(agent, "calculer_valorisation") is None:
        from apps.valorisation.models import Exercice, Valorisation
        from apps.valorisation.services import TYPES_ATTESTATION

        exercice = Exercice.objects.filter(statut="cloture").order_by("-annee").first()
        if exercice is not None:
            a_deposer = Valorisation.objects.filter(
                exercice=exercice, actuelle=True, total__gt=0, usager__type__in=TYPES_ATTESTATION, deposee_le__isnull=True
            ).count()
            limite = exercice.date_limite()
            compteurs.append(
                Compteur(
                    "attestations",
                    f"Attestations {exercice.annee} à déposer avant le {limite:%d/%m/%Y}",
                    a_deposer,
                    "/pilotage/valorisation",
                    groupe="alertes" if limite <= aujourd_hui + timedelta(days=30) else "a_traiter",
                    gravite="danger" if limite < aujourd_hui else "attention",
                )
            )
    return compteurs


def a_traiter(agent: Utilisateur) -> list[dict[str, Any]]:
    """Compteurs du jour, chacun avec le lien de la liste filtrée qu'il résume (DSH-06) ; seuls les compteurs des
    écrans que l'agent peut ouvrir sont calculés, dans son périmètre (DSH-05)."""
    maintenant = timezone.now()
    aujourd_hui = timezone.localdate()
    compteurs: list[Compteur] = []
    if peut(agent, "instruire_reservation"):
        demandes = _sur_site(
            Reservation.objects.filter(statut__in=["demande", "en_instruction"]),
            agent,
            "instruire_reservation",
            "espace__batiment__site",
        )
        compteurs.append(
            Compteur(
                "demandes",
                "Demandes à instruire",
                demandes.values("dossier").distinct().count(),
                "/reservations/dossiers?statut=demande,en_instruction",
            )
        )
        options = _sur_site(
            Reservation.objects.filter(statut="option", option_expire_le__lt=maintenant + timedelta(hours=48)),
            agent,
            "instruire_reservation",
            "espace__batiment__site",
        )
        compteurs.append(
            Compteur(
                "options",
                "Options expirant sous 48 h",
                options.values("dossier").distinct().count(),
                "/reservations/dossiers?options_expirant_heures=48",
                gravite="attention",
            )
        )
    if peut(agent, "valider_compte_usager"):
        from apps.comptes.models import CompteUsager

        compteurs.append(
            Compteur(
                "comptes",
                "Comptes du portail à valider",
                CompteUsager.objects.filter(statut="a_valider").count(),
                "/usagers/comptes",
            )
        )
    if peut(agent, "lire_message"):
        from apps.communication.models import Message

        messages = _sur_site(
            Message.objects.filter(auteur_contact__isnull=False, lu_par_ville_le__isnull=True),
            agent,
            "lire_message",
            "dossier__reservations__espace__batiment__site",
        )
        compteurs.append(Compteur("messages", "Messages des usagers non lus", messages.count(), "/echanges/messages"))
    if peut(agent, "lire_document"):
        from apps.documents.models import Document

        scans = _sur_site(
            Document.objects.filter(statut="scan_a_controler"),
            agent,
            "lire_document",
            "dossier__reservations__espace__batiment__site",
        )
        compteurs.append(Compteur("scans", "Documents signés à contrôler", scans.count(), "/documents/a-controler"))
    if peut(agent, "lire_materiel"):
        from apps.materiel.models import ReservationMateriel

        prets = _sur_site(ReservationMateriel.objects.filter(statut="demandee"), agent, "lire_materiel", "stock__site")
        compteurs.append(Compteur("prets", "Demandes de matériel à valider", prets.count(), "/materiel/prets?statut=demandee"))
    if peut(agent, "lire_personnel"):
        from apps.personnel.models import Besoin, Incident, SaisieMobile

        besoins = _sur_site(
            Besoin.objects.filter(statut="a_couvrir", debut__gte=maintenant, debut__lt=maintenant + timedelta(days=14)),
            agent,
            "lire_personnel",
            "site",
        )
        compteurs.append(
            Compteur(
                "besoins",
                "Besoins de gardiennage non couverts (14 jours)",
                besoins.count(),
                "/personnel/vacations?besoins_jours=14",
                gravite="attention",
            )
        )
        saisies = _sur_site(
            SaisieMobile.objects.filter(statut="conflit", traitee_par__isnull=True), agent, "lire_personnel", "agent__sites"
        )
        compteurs.append(
            Compteur("saisies", "Saisies du terrain à examiner", saisies.count(), "/personnel/saisies?statut=conflit")
        )
        incidents = _sur_site(Incident.objects.filter(traite=False), agent, "lire_personnel", "site")
        compteurs.append(
            Compteur(
                "incidents",
                "Incidents à traiter",
                incidents.count(),
                "/personnel/incidents?traite=false",
                groupe="alertes",
                gravite="attention",
            )
        )
    if peut(agent, "lire_usager"):
        from apps.usagers.services import alertes_expiration

        compteurs.append(
            Compteur(
                "pieces",
                "Pièces justificatives à renouveler",
                alertes_expiration(aujourd_hui).count(),
                "/usagers/alertes-pieces",
                groupe="alertes",
            )
        )
    if peut(agent, "lire_finances"):
        from apps.finances import cautions, facturation

        retards = _sur_site(
            facturation.en_retard(aujourd_hui), agent, "lire_finances", "dossier__reservations__espace__batiment__site"
        )
        compteurs.append(
            Compteur(
                "factures",
                "Factures impayées en retard",
                retards.count(),
                "/finances/retards",
                groupe="alertes",
                gravite="danger",
            )
        )
        en_alerte = _sur_site(cautions.en_alerte(aujourd_hui), agent, "lire_finances", "reservation__espace__batiment__site")
        compteurs.append(
            Compteur(
                "cautions",
                "Cautions à restituer en retard",
                en_alerte.count(),
                "/finances/cautions-en-retard",
                groupe="alertes",
                gravite="danger",
            )
        )
    if peut(agent, "lire_materiel"):
        from apps.materiel.models import Stock
        from apps.materiel.services import controles_en_retard

        stocks = _sur_site(Stock.objects.filter(materiel__actif=True).select_related("materiel"), agent, "lire_materiel", "site")
        compteurs.append(
            Compteur(
                "controles",
                "Contrôles de matériel dépassés",
                len(controles_en_retard(stocks)),
                "/materiel/controles",
                groupe="alertes",
                gravite="danger",
            )
        )
    compteurs += _compteurs_attestations(agent, aujourd_hui)
    return [c.en_dict() for c in compteurs]


# --- DSH-04 : tableau de bord de la direction -------------------------------------------------------------------


def tableau_direction(agent: Utilisateur, annee: int) -> dict[str, Any]:
    """Indicateurs annuels comparés à l'année précédente, et tendance mensuelle des heures et des recettes."""

    def annuel(an: int) -> dict[str, Any]:
        du, au = date(an, 1, 1), date(an, 12, 31)
        espaces = espaces_du_perimetre(agent, "lire_statistiques")
        lignes = [ligne for ligne in occupation(espaces, du, au) if ligne["premier_niveau"]]
        reservees = sum(ligne["minutes_reservees"] for ligne in lignes)
        ouvertes = sum(ligne["minutes_ouverture"] for ligne in lignes)
        usagers = (
            Occurrence.objects.filter(
                espace__in=espaces, statut__in=STATUTS_OCCUPES, debut__gte=bornes(du, au)[0], debut__lt=bornes(du, au)[1]
            )
            .values("reservation__dossier__usager")
            .distinct()
            .count()
        )
        argent = recettes(agent, du, au) if peut(agent, "lire_finances") else {}
        return {
            "annee": an,
            "heures_reservees": round(reservees / 60),
            "taux_occupation": round(10000 * reservees / ouvertes) if ouvertes else 0,
            "usagers_actifs": usagers,
            "recettes_nettes": argent.get("net", 0),
            "concours_en_nature": argent.get("concours_en_nature", 0),
        }

    courant, precedent = annuel(annee), annuel(annee - 1)
    espaces = espaces_du_perimetre(agent, "lire_statistiques")
    mois = []
    finances = peut(agent, "lire_finances")
    for numero in range(1, 13):
        debut = date(annee, numero, 1)
        fin = (date(annee + (numero == 12), numero % 12 + 1, 1)) - timedelta(days=1)
        lignes = [ligne for ligne in occupation(espaces, debut, fin) if ligne["premier_niveau"]]
        mois.append(
            {
                "mois": numero,
                "heures": round(sum(ligne["minutes_reservees"] for ligne in lignes) / 60),
                "recettes_nettes": recettes(agent, debut, fin)["net"] if finances else None,
            }
        )
    return {"courant": courant, "precedent": precedent, "mois": mois}
