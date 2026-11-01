"""Plannings simulés : créneaux réguliers des associations de CityResa sur la saison 2026-2027, selon leur discipline,
et manifestations ponctuelles (galas, lotos, tournois, assemblées générales). Les données de CityResa occupent peu les
salles ; cette simulation remplit les plannings et les impressions de façon réaliste.

Chaque dossier simulé porte la mention `MENTION` dans ses observations (absent de CityResa) ; `charger_demo
--sans-simulation` charge les seules données de CityResa, pour une comparaison stricte. Les créneaux passent par le
service de réservation : horaires d'ouverture et conflits sont contrôlés, un créneau refusé est remplacé par le suivant.
"""

from __future__ import annotations

import random
from datetime import date, time, timedelta

from django.utils import timezone

from apps.noyau.exceptions import ErreurMetier
from apps.referentiel.models import Espace, Saison
from apps.reservations import services
from apps.reservations.models import Dossier, Reservation, TypeReservation
from apps.usagers.models import Usager

SYSTEME = services.SYSTEME
MENTION = "Créneau simulé (démonstration) — absent des données de CityResa."
GYMNASES = ["sablons", "gambetta", "roland-garros", "langevin", "republique"]
SOIREE = [(time(17, 0), time(18, 30)), (time(18, 30), time(20, 0)), (time(20, 0), time(21, 30)), (time(20, 30), time(22, 0))]
MERCREDI = [(time(14, 0), time(16, 0)), (time(16, 0), time(18, 0))]
SAMEDI = [(time(9, 0), time(11, 0)), (time(10, 0), time(12, 0)), (time(14, 0), time(16, 0))]
SCOLAIRE = [(time(9, 0), time(11, 30)), (time(13, 30), time(16, 0)), (time(8, 30), time(10, 0))]

# Association (clé CityResa) → (discipline, espaces possibles, nombre de créneaux hebdomadaires).
DISCIPLINES: dict[str, tuple[str, list[str], int]] = {
    "gama": ("Aïkido", ["doret"], 4),
    "abac": ("Badminton", ["gambetta", "roland-garros"], 5),
    "ascb": ("Basket-ball", ["sablons", "republique"], 5),
    "ccpc": ("Capoeira", ["doret", "langevin"], 3),
    "acsc": ("Sports de contact", ["doret", "langevin"], 4),
    "ajbi": ("Boxe anglaise", ["langevin", "republique"], 4),
    "scmc-culturisme": ("Culturisme", ["republique"], 3),
    "arounddance": ("Danse", ["mb-polyvalente", "gabriel-peri"], 3),
    "cecet92": ("Escrime", ["gambetta"], 3),
    "cepc": ("Éducation physique", ["langevin", "sablons"], 3),
    "scmc-football": ("Football", ["moquet"], 5),
    "asfsc": ("Football en salle", ["sablons", "republique"], 4),
    "grs": ("Gymnastique rythmique", ["gambetta", "sablons"], 4),
    "scmc-gv": ("Gymnastique volontaire", ["gabriel-peri", "chalet", "mb-polyvalente"], 4),
    "kravmaga": ("Krav-maga", ["doret", "langevin"], 3),
    "scmc-judo": ("Judo", ["doret"], 5),
    "ucc": ("Multisport", GYMNASES, 3),
    "rugby13": ("Rugby à XIII", ["moquet"], 4),
    "rugby15": ("Rugby à XV", ["moquet"], 4),
    "taekwondo": ("Taekwondo", ["doret", "langevin"], 4),
    "ttmc": ("Tennis de table", ["gabriel-peri", "chalet"], 4),
    "atc": ("Trampoline", ["republique", "gambetta"], 3),
    "sgdt": ("Gym, danse et twirling", ["gambetta", "mb-polyvalente"], 4),
    "espace-yoga": ("Yoga", ["chalet", "henri-matisse"], 3),
    "scmc-yoga": ("Yoga", ["henri-matisse", "mb-reunion-1"], 3),
    "scmc-volley": ("Volley-ball", ["roland-garros", "sablons"], 4),
    "usc": ("Multisport", ["terrain-multisport", "sablons"], 3),
    "scmc-athletisme": ("Athlétisme", ["moquet"], 4),
    "ccr92": ("Course sur route", ["moquet"], 2),
    "omeps": ("Réunion de bureau", ["mb-reunion-3"], 1),
}
# Manifestations ponctuelles : (association, objet, espace, semaines après aujourd'hui, jour ISO, début, fin, statut).
MANIFESTATIONS: list[tuple[str, str, str, int, int, time, time, str]] = [
    ("sgdt", "Gala de fin de trimestre", "mb-polyvalente", 3, 6, time(17, 0), time(23, 0), "confirmee"),
    ("omeps", "Loto des sports", "mb-polyvalente", 5, 6, time(14, 0), time(19, 0), "validee"),
    ("arounddance", "Soirée dansante", "mb-polyvalente", 7, 6, time(19, 0), time(23, 30), "demande"),
    ("rugby15", "Repas de fin d'année du club", "gabriel-peri", 6, 6, time(19, 0), time(23, 30), "en_instruction"),
    ("ascb", "Tournoi de Noël des jeunes", "sablons", 6, 7, time(9, 0), time(18, 0), "confirmee"),
    ("abac", "Tournoi régional de badminton", "gambetta", 4, 7, time(8, 30), time(19, 0), "validee"),
    ("scmc-judo", "Passage de grades", "doret", 2, 6, time(14, 0), time(18, 0), "confirmee"),
    ("cecet92", "Démonstration d'escrime artistique", "folie-desmares", 8, 6, time(15, 0), time(18, 0), "demande"),
]
SANS_LIEU = [
    "scmc-aquaforme",
    "scmc-billard",
    "scmc-natation",
    "cpb92",
    "petanque",
    "casc",
    "randofass",
    "ccesaf",
    "arsenal",
    "tcmc",
    "ctac92",
]


def deja_simule() -> bool:
    return Dossier.objects.filter(observations=MENTION).exists()


def _premier(jour_iso: int, apres: date) -> date:
    return apres + timedelta(days=(jour_iso - apres.isoweekday()) % 7)


def _creer(
    usager: Usager,
    type_code: str,
    espace: Espace,
    jour: date,
    debut: time,
    fin: time,
    *,
    objet: str,
    activite: str,
    statut: str,
    saison: Saison | None = None,
    regle: str = "",
    date_fin: date | None = None,
) -> Reservation | None:
    rattachement = usager.rattachements.filter(principal=True).first()
    dossier = services.creer_dossier(
        acteur=SYSTEME,
        usager=usager,
        type_reservation=TypeReservation.objects.get(code=type_code),
        objet=objet,
        saison=saison,
        contact=rattachement.contact if rattachement else None,
    )
    Dossier.objects.filter(pk=dossier.pk).update(activite=activite, observations=MENTION, effectif=random.randint(8, 40))
    try:
        reservation = services.ajouter_reservation(
            dossier,
            acteur=SYSTEME,
            espace=espace,
            date_debut=jour,
            date_fin=date_fin or jour,
            heure_debut=debut,
            heure_fin=fin,
            recurrence=regle,
        )
        if statut in {"validee", "confirmee"}:
            services._changer_statut(reservation, "validee", SYSTEME, valide_le=timezone.now())
            feuilles = espace.feuilles()
            for occurrence in reservation.occurrences.filter(statut="validee"):
                services.poser_verrous(occurrence, feuilles)
            if statut == "confirmee":
                services._changer_statut(reservation, "confirmee", SYSTEME, confirme_le=timezone.now())
        elif statut == "en_instruction":
            services._changer_statut(reservation, "en_instruction", SYSTEME)
        return reservation
    except ErreurMetier:
        Dossier.objects.filter(pk=dossier.pk).delete()
        return None


def charger(saison: Saison, graine: int = 92320) -> dict[str, int]:
    """Ajoute les plannings simulés (idempotent : rien si déjà fait)."""
    if deja_simule():
        return {}
    alea = random.Random(graine)
    random.seed(graine)
    espaces = {e.code: e for e in Espace.objects.select_related("batiment__site")}
    usagers = {u.nom: u for u in Usager.objects.filter(type="association")}
    noms = {}
    from apps.noyau.demo import cityresa

    for u in cityresa.donnees()["usagers"]:
        if u["nom"] in usagers:
            noms[u["cle"]] = usagers[u["nom"]]
    bilan = {"creneaux_simules": 0, "manifestations_simulees": 0, "assemblees_simulees": 0}
    fin_saison = min(saison.fin, date(saison.fin.year, 6, 30))
    for cle, (discipline, lieux, nombre) in DISCIPLINES.items():
        usager = noms.get(cle)
        if usager is None:
            continue
        plages = (
            [(j, d, f) for j in range(1, 6) for d, f in SOIREE]
            + [(3, d, f) for d, f in MERCREDI]
            + [(6, d, f) for d, f in SAMEDI]
        )
        alea.shuffle(plages)
        poses = 0
        for jour_iso, debut, fin in plages:
            if poses >= nombre:
                break
            # Tous les lieux possibles du club, dans un ordre tiré au sort : le premier libre et ouvert est retenu.
            for code_espace in alea.sample(lieux, len(lieux)):
                espace = espaces.get(code_espace)
                if espace is None:
                    continue
                premier = _premier(jour_iso, saison.debut)
                code = ["MO", "TU", "WE", "TH", "FR", "SA", "SU"][jour_iso - 1]
                if _creer(
                    usager,
                    "creneau_annuel",
                    espace,
                    premier,
                    debut,
                    fin,
                    objet=f"Entraînements — {discipline}",
                    activite=discipline,
                    statut="confirmee" if alea.random() < 0.85 else "validee",
                    saison=saison,
                    regle=f"FREQ=WEEKLY;INTERVAL=1;BYDAY={code}",
                    date_fin=fin_saison,
                ):
                    poses += 1
                    bilan["creneaux_simules"] += 1
                    break
    # Sport scolaire en journée (coordonné par l'OMEPS) : les gymnases servent aussi aux écoles.
    omeps = noms.get("omeps")
    if omeps is not None:
        for rang, code_espace in enumerate([*GYMNASES, "doret"]):
            espace = espaces.get(code_espace)
            if espace is None:
                continue
            for jour_iso in (1, 2, 4, 5):
                debut, fin = SCOLAIRE[(rang + jour_iso) % len(SCOLAIRE)]
                code = ["MO", "TU", "WE", "TH", "FR", "SA", "SU"][jour_iso - 1]
                if _creer(
                    omeps,
                    "creneau_annuel",
                    espace,
                    _premier(jour_iso, saison.debut),
                    debut,
                    fin,
                    objet="Sport scolaire — écoles élémentaires",
                    activite="Éducation physique scolaire",
                    statut="confirmee",
                    saison=saison,
                    regle=f"FREQ=WEEKLY;INTERVAL=1;BYDAY={code}",
                    date_fin=fin_saison,
                ):
                    bilan["creneaux_simules"] += 1
    aujourd_hui = timezone.localdate()
    for cle, objet, code_espace, semaines, jour_iso, debut, fin, statut in MANIFESTATIONS:
        usager, espace = noms.get(cle), espaces.get(code_espace)
        if usager and espace:
            jour = _premier(jour_iso, aujourd_hui + timedelta(weeks=semaines))
            if _creer(
                usager,
                "ponctuelle",
                espace,
                jour,
                debut,
                fin,
                objet=objet,
                activite=DISCIPLINES.get(cle, ("",))[0],
                statut=statut,
            ):
                bilan["manifestations_simulees"] += 1
    salles = ["mb-reunion-1", "mb-reunion-2", "mb-reunion-3"]
    for rang, cle in enumerate(SANS_LIEU):
        usager = noms.get(cle)
        if usager is None:
            continue
        jour = _premier(1 + rang % 4, aujourd_hui + timedelta(weeks=1 + rang % 8))
        statut = ["confirmee", "validee", "demande", "confirmee"][rang % 4]
        for decalage in range(3):  # salle prise ou fermée : la suivante
            if _creer(
                usager,
                "ponctuelle",
                espaces[salles[(rang + decalage) % 3]],
                jour,
                time(19, 0),
                time(21, 0),
                objet="Assemblée générale",
                activite="Vie associative",
                statut=statut,
            ):
                bilan["assemblees_simulees"] += 1
                break
    return bilan
