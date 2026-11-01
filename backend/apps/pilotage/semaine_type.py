"""Semaine type d'un espace ou d'un site (IMP-01) : les créneaux réguliers d'une saison — réservations hebdomadaires,
récurrentes — rangés par jour de la semaine, sans dates. Pour un espace, les créneaux de ses parents et de ses
sous-espaces y figurent (un gymnase réservé en entier occupe ses moitiés). Les demandes et options apparaissent comme
provisoires ; un particulier n'est jamais nommé (« Réservation privée », D-062). Droits rôle × périmètre."""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import date, time
from typing import Any

from django.conf import settings
from django.utils import timezone

from apps.audit.services import journaliser
from apps.documents import impression
from apps.habilitations.models import Utilisateur
from apps.habilitations.services import exiger, sites_autorises
from apps.noyau.exceptions import ErreurValidation
from apps.pilotage.impressions import nom_complet
from apps.referentiel.models import Espace, Saison, Site
from apps.reservations.models import Reservation

JOURS = ["Lundi", "Mardi", "Mercredi", "Jeudi", "Vendredi", "Samedi", "Dimanche"]
CODES_JOURS = {"MO": 0, "TU": 1, "WE": 2, "TH": 3, "FR": 4, "SA": 5, "SU": 6}
REGULIERS = ("validee", "confirmee", "realisee")
PROVISOIRES = ("demande", "en_instruction", "option")
ECART_TOLERE = 14


@dataclass
class Creneau:
    jour: int
    debut: str
    fin: str
    espace: int
    espace_nom: str
    occupant: str
    type_usager: str
    activite: str
    statut: str
    provisoire: bool
    frequence: str
    pendant_vacances: bool
    du: date
    au: date
    dossier: str
    dossier_id: int
    reservation: int

    def en_dict(self) -> dict[str, Any]:
        return {**self.__dict__, "jour_libelle": JOURS[self.jour]}


def saison_par_defaut() -> Saison | None:
    aujourd_hui = timezone.localdate()
    return (
        Saison.objects.filter(debut__lte=aujourd_hui, fin__gte=aujourd_hui).order_by("-debut").first()
        or Saison.objects.filter(active=True).order_by("-debut").first()
        or Saison.objects.order_by("-debut").first()
    )


def _jours(reservation: Reservation) -> list[int]:
    regle = reservation.recurrence.upper()
    trouve = re.search(r"BYDAY=([A-Z,]+)", regle)
    if trouve:
        jours = sorted({CODES_JOURS[c[-2:]] for c in trouve.group(1).split(",") if c[-2:] in CODES_JOURS})
        if jours:
            return jours
    return [reservation.date_debut.weekday()]


def _frequence(reservation: Reservation) -> str:
    intervalle = re.search(r"INTERVAL=(\d+)", reservation.recurrence.upper())
    pas = int(intervalle.group(1)) if intervalle else 1
    return "chaque semaine" if pas == 1 else f"une semaine sur {pas}"


def creneaux(agent: Utilisateur, *, saison: Saison, site: Site | None = None, espace: Espace | None = None) -> list[Creneau]:
    if (site is None) == (espace is None):
        raise ErreurValidation("Choisissez un site ou un espace.", code="cible_requise")
    exiger(agent, "lire_reservation", espace or site)
    if espace is not None:
        ids = espace.ids_lies()
    else:
        ids = set(Espace.objects.filter(batiment__site=site, actif=True).values_list("pk", flat=True))
    autorises = sites_autorises(agent, "lire_reservation")
    reservations = (
        Reservation.objects.filter(
            espace_id__in=ids,
            statut__in=[*REGULIERS, *PROVISOIRES],
            date_debut__lte=saison.fin,
            date_fin__gte=saison.debut,
        )
        .filter(recurrence__icontains="FREQ=WEEKLY")
        .select_related("espace__batiment__site", "dossier__usager")
    )
    if autorises is not None:
        reservations = reservations.filter(espace__batiment__site__in=autorises)
    resultat = []
    for r in reservations[:2000]:
        usager = r.dossier.usager
        for jour in _jours(r):
            resultat.append(
                Creneau(
                    jour=jour,
                    debut=f"{r.heure_debut:%H:%M}",
                    fin=f"{r.heure_fin:%H:%M}",
                    espace=r.espace_id,
                    espace_nom=r.espace.nom,
                    occupant="Réservation privée" if usager.type == "particulier" else usager.nom,
                    type_usager=usager.type,
                    activite=r.dossier.activite if usager.type != "particulier" else "",
                    statut=r.statut,
                    provisoire=r.statut in PROVISOIRES,
                    frequence=_frequence(r),
                    pendant_vacances=not r.exclure_vacances,
                    du=max(r.date_debut, saison.debut),
                    au=min(r.date_fin, saison.fin),
                    dossier=r.dossier.numero,
                    dossier_id=r.dossier_id,
                    reservation=r.pk,
                )
            )
    return sorted(resultat, key=lambda c: (c.jour, c.debut, c.espace_nom, c.occupant))


def _lignes_bloc(c: Creneau, saison: Saison, cible: Espace) -> list[str]:
    lignes = [f"{c.debut} – {c.fin}", c.occupant + (f" ({c.activite})" if c.activite else "")]
    if c.espace != cible.pk:
        lignes.append(c.espace_nom)
    if c.frequence != "chaque semaine":
        lignes.append(c.frequence)
    if c.pendant_vacances:
        lignes.append("aussi pendant les vacances")
    # Quelques jours d'écart avec la saison (rentrée, dernière semaine) ne changent pas la lecture de la semaine type.
    if (c.du - saison.debut).days > ECART_TOLERE:
        lignes.append(f"à partir du {c.du:%d/%m}")
    if (saison.fin - c.au).days > ECART_TOLERE:
        lignes.append(f"jusqu'au {c.au:%d/%m}")
    if c.provisoire:
        lignes.append("provisoire")
    return lignes


def edition(
    agent: Utilisateur,
    *,
    saison: Saison,
    site: Site | None = None,
    espace: Espace | None = None,
    format_papier: str = "A4",
    mise_en_page: str = "calendrier",
) -> impression.Edition:
    impression.verifier_mise_en_page(mise_en_page)
    liste = creneaux(agent, saison=saison, site=site, espace=espace)
    if espace is not None:
        cible, lien = nom_complet(espace), f"semaine-type?espace={espace.pk}"
    else:
        assert site is not None
        cible, lien = site.nom, f"semaine-type?site={site.pk}"
    groupes = [
        (
            JOURS[jour],
            [
                [
                    f"{c.debut} – {c.fin}",
                    c.espace_nom,
                    c.occupant + (f" ({c.activite})" if c.activite else "") + (" — provisoire" if c.provisoire else ""),
                    f"du {c.du:%d/%m} au {c.au:%d/%m}, {c.frequence}" + (", vacances comprises" if c.pendant_vacances else ""),
                ]
                for c in liste
                if c.jour == jour
            ],
        )
        for jour in range(7)
    ]

    def grille(cible: Espace, intitule: str) -> impression.Grille:
        lies = cible.ids_lies()
        return impression.Grille(
            intitule=intitule,
            jours=JOURS,
            blocs=[
                impression.Bloc(
                    c.jour, time.fromisoformat(c.debut), time.fromisoformat(c.fin), _lignes_bloc(c, saison, cible), c.provisoire
                )
                for c in liste
                if c.espace in lies
            ],
            afficher_intitule=bool(intitule),
        )

    grilles = []
    if mise_en_page == "calendrier":
        if espace is not None:
            grilles = [grille(espace, "")]
        else:
            # Une grille par espace du site qui a des créneaux : tout un site sur une grille serait illisible.
            occupes = {c.espace for c in liste}
            for espace_du_site in Espace.objects.filter(batiment__site=site, actif=True).order_by("nom"):
                if occupes & espace_du_site.ids_lies():
                    grilles.append(grille(espace_du_site, espace_du_site.nom))
    return impression.Edition(
        titre=f"Semaine type — {cible}",
        sous_titre=(
            f"Saison {saison.nom} ({saison.debut:%d/%m/%Y} – {saison.fin:%d/%m/%Y}) : créneaux réguliers, "
            "hors réservations ponctuelles ; sauf mention, hors vacances scolaires. En gris clair : demandes et options non "
            "confirmées."
        ),
        entetes=["Horaires", "Espace", "Occupant", "Période"],
        lignes=[],
        groupes=[(intitule, lignes) for intitule, lignes in groupes if lignes],
        lien=f"{settings.BACKOFFICE_URL.rstrip('/')}/pilotage/{lien}&saison={saison.pk}",
        format_papier=format_papier,
        paysage=format_papier == "A3",
        mention_vide="Aucun créneau régulier sur cette saison.",
        grilles=grilles,
    )


def imprimer(
    agent: Utilisateur,
    *,
    saison: Saison,
    site: Site | None = None,
    espace: Espace | None = None,
    format_papier: str = "A4",
    mise_en_page: str = "calendrier",
) -> bytes:
    """IMP-01 : semaine type imprimée ; les droits sont vérifiés par creneaux()."""
    pdf = impression.imprimer(
        edition(agent, saison=saison, site=site, espace=espace, format_papier=format_papier, mise_en_page=mise_en_page)
    )
    journaliser(
        "imprimer_semaine_type",
        espace or site,
        apres={"saison": saison.pk, "format": format_papier, "mise_en_page": mise_en_page},
        acteur=agent,
    )
    return pdf
