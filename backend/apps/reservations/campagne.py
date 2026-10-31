"""Campagne annuelle des créneaux (PLA-05) et arbitrage selon les priorités (RG-03).

1. Ouverture : les associations déposent leurs demandes de créneaux pour la saison.
2. Instruction : détection des demandes concurrentes (mêmes espaces feuilles, mêmes horaires, mêmes jours).
3. Proposition d'arbitrage : priorité RG-03 (Ville > scolaire en temps scolaire > associations
   conventionnées locales > autres associations > entreprises et particuliers), puis reconduction
   d'un créneau de la saison précédente, puis date de dépôt.
4. Commission : décisions en lot, attribution (validation), refus motivés, notification groupée.
"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

from django.db import transaction
from django.utils import timezone

from apps.audit.services import journaliser
from apps.communication.services import notifier
from apps.habilitations.services import exiger
from apps.noyau.exceptions import ErreurMetier, ErreurValidation
from apps.usagers.services import categorie_priorite, rang_priorite

from . import services
from .models import Campagne, Reservation
from .recurrence import generer_plages

TRANSITIONS_CAMPAGNE = {
    "preparation": {"ouverte"},
    "ouverte": {"instruction"},
    "instruction": {"commission", "ouverte"},
    "commission": {"attribuee", "instruction"},
    "attribuee": {"close"},
    "close": set(),
}


@dataclass
class Candidat:
    reservation_id: int
    dossier: str
    usager: str
    categorie: str
    rang: int
    reconduction: bool
    depose_le: datetime | None
    proposition: str = "attribuer"


@dataclass
class GroupeConcurrent:
    espace: str
    creneau: str
    candidats: list[Candidat] = field(default_factory=list)


def _reconduction(reservation: Reservation) -> bool:
    """Le même usager occupait le même espace la saison précédente (ancienneté)."""
    saison = reservation.dossier.saison
    if saison is None:
        return False
    return Reservation.objects.filter(
        dossier__usager=reservation.dossier.usager,
        espace=reservation.espace,
        statut__in=["validee", "confirmee", "realisee", "cloturee"],
        dossier__saison__fin__lt=saison.debut,
    ).exists()


def _cle_tri(reservation: Reservation, debut: datetime) -> tuple[int, int, datetime]:
    depose = reservation.dossier.depose_le or reservation.dossier.cree_le
    return (rang_priorite(reservation.dossier.usager, debut), 0 if _reconduction(reservation) else 1, depose)


def analyser(campagne: Campagne) -> list[GroupeConcurrent]:
    """Groupes de demandes qui se disputent au moins une séance, triés par proposition d'arbitrage."""
    demandes = list(
        Reservation.objects.filter(dossier__campagne=campagne, statut__in=["demande", "en_instruction"]).select_related(
            "dossier__usager", "dossier__saison", "espace"
        )
    )
    occupations: dict[int, list[tuple[datetime, datetime]]] = {r.pk: generer_plages(r) for r in demandes}
    feuilles = {r.pk: {f.pk for f in r.espace.feuilles()} for r in demandes}
    voisins: dict[int, set[int]] = defaultdict(set)
    for i, a in enumerate(demandes):
        for b in demandes[i + 1 :]:
            if not feuilles[a.pk] & feuilles[b.pk]:
                continue
            if any(da < fb and db < fa for da, fa in occupations[a.pk] for db, fb in occupations[b.pk]):
                voisins[a.pk].add(b.pk)
                voisins[b.pk].add(a.pk)
    par_id = {r.pk: r for r in demandes}
    vus: set[int] = set()
    groupes: list[GroupeConcurrent] = []
    for r in demandes:
        if r.pk in vus or not voisins[r.pk]:
            continue
        composante, a_visiter = set(), [r.pk]
        while a_visiter:
            courant = a_visiter.pop()
            if courant in composante:
                continue
            composante.add(courant)
            a_visiter.extend(voisins[courant] - composante)
        vus |= composante
        membres = sorted((par_id[i] for i in composante), key=lambda x: _cle_tri(x, occupations[x.pk][0][0]))
        groupe = GroupeConcurrent(espace=membres[0].espace.nom, creneau=membres[0].description)
        attribues: list[Reservation] = []
        for m in membres:
            debut = occupations[m.pk][0][0]
            en_conflit = any(
                feuilles[m.pk] & feuilles[a.pk]
                and any(da < fb and db < fa for da, fa in occupations[m.pk] for db, fb in occupations[a.pk])
                for a in attribues
            )
            if not en_conflit:
                attribues.append(m)
            groupe.candidats.append(
                Candidat(
                    m.pk,
                    m.dossier.numero,
                    m.dossier.usager.nom,
                    categorie_priorite(m.dossier.usager, debut),
                    rang_priorite(m.dossier.usager, debut),
                    _reconduction(m),
                    m.dossier.depose_le,
                    "refuser" if en_conflit else "attribuer",
                )
            )
        groupes.append(groupe)
    return groupes


@transaction.atomic
def changer_statut(campagne: Campagne, statut: str, *, acteur: Any) -> Campagne:
    campagne = Campagne.objects.select_for_update().get(pk=campagne.pk)
    exiger(acteur, "arbitrer_campagne" if statut in {"attribuee", "close"} else "gerer_campagne", campagne)
    if statut not in TRANSITIONS_CAMPAGNE[campagne.statut]:
        raise ErreurMetier(
            f"La campagne ne peut pas passer de « {campagne.get_statut_display()} » à ce statut.", code="transition_interdite"
        )
    avant = campagne.statut
    campagne.statut = statut
    campagne.save(update_fields=["statut"])
    if statut == "instruction":
        for reservation in Reservation.objects.filter(dossier__campagne=campagne, statut="demande"):
            services._changer_statut(reservation, "en_instruction", acteur)
    journaliser("campagne_statut", campagne, avant={"statut": avant}, apres={"statut": statut}, acteur=acteur)
    return campagne


@transaction.atomic
def attribuer(campagne: Campagne, decisions: dict[int, dict[str, str]], *, acteur: Any) -> dict[str, int]:
    """Décision de la commission : `{reservation_id: {"decision": "attribuer"|"refuser", "motif": "..."}}`.

    Les attributions valident les réservations (verrous posés, RG-01 garanti par la base) ; les refus sont
    motivés ; chaque usager reçoit un seul message récapitulatif.
    """
    campagne = Campagne.objects.select_for_update().get(pk=campagne.pk)
    exiger(acteur, "arbitrer_campagne", campagne)
    if campagne.statut != "commission":
        raise ErreurMetier("Les attributions se font quand la campagne est en commission.", code="campagne_hors_commission")
    reservations = {
        r.pk: r
        for r in Reservation.objects.filter(dossier__campagne=campagne, pk__in=list(decisions)).select_related("dossier__usager")
    }
    if set(decisions) - set(reservations):
        raise ErreurValidation("Certaines demandes n'appartiennent pas à cette campagne.", code="hors_campagne")
    recap: dict[int, dict[str, list[str]]] = defaultdict(lambda: {"attribues": [], "refuses": []})
    bilan = {"attribuees": 0, "refusees": 0}
    for identifiant, decision in sorted(decisions.items(), key=lambda d: d[1].get("decision") != "attribuer"):
        reservation = reservations[identifiant]
        texte = f"- {reservation.espace.nom} : {reservation.description}"
        if decision.get("decision") == "attribuer":
            services._changer_statut(reservation, "validee", acteur, valide_par=acteur, valide_le=timezone.now())
            for occurrence in reservation.occurrences.filter(statut="validee"):
                services.poser_verrous(occurrence)
            recap[reservation.dossier.usager_id]["attribues"].append(texte)
            bilan["attribuees"] += 1
        else:
            motif = (decision.get("motif") or "").strip()
            if not motif:
                raise ErreurValidation(
                    f"Motif obligatoire pour le refus de la demande {reservation.dossier.numero}.", code="motif_requis"
                )
            services._changer_statut(reservation, "refusee", acteur, motif_refus=motif)
            recap[reservation.dossier.usager_id]["refuses"].append(f"{texte} (motif : {motif})")
            bilan["refusees"] += 1
    usagers = {r.dossier.usager_id: r.dossier.usager for r in reservations.values()}
    for usager_id, lignes in recap.items():
        notifier(
            "campagne_attribution",
            {
                "saison": campagne.saison.nom,
                "attribues": "\n".join(lignes["attribues"]) or "aucun",
                "refuses": "\n".join(lignes["refuses"]),
            },
            usager=usagers[usager_id],
            objet=campagne,
        )
    journaliser("campagne_attribution", campagne, apres=bilan, acteur=acteur)
    return bilan
