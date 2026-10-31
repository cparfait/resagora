"""Jeu de démonstration, lot 4 : huit gardiens fictifs rattachés aux comptes de recette de l'annuaire (gardien01 à
gardien08), habilitations (dont une expirée), trames de semaine type appliquées sur six semaines, besoins issus des
réservations, une absence avec remplacement à pourvoir, un incident. Enregistré dans `socle.EXTENSIONS`."""

from __future__ import annotations

from datetime import date, datetime, time, timedelta
from typing import Any

from django.db.models import Q
from django.utils import timezone

from apps.noyau.demo.socle import Generateur
from apps.referentiel.models import Saison, Site
from apps.reservations.models import Occurrence
from apps.reservations.recurrence import PARIS

from . import services
from .models import Agent, HabilitationAgent, Incident, LigneTrame, Trame, TypeHabilitation

SYSTEME = services.SYSTEME

# Semaine type d'un site gardienné : (jour, début, fin, rang de l'agent sur le site).
SEMAINE_TYPE: list[tuple[int, time, time, int]] = [
    *[(j, time(16, 30), time(22, 45), j % 2) for j in range(5)],
    (5, time(8, 0), time(14, 0), 0),
    (5, time(14, 0), time(20, 0), 1),
    (6, time(8, 30), time(13, 30), 0),
]


def _sites_gardiennes() -> list[Site]:
    return list(
        Site.objects.filter(code__startswith="demo-", batiments__espaces__gardiennage_requis=True).distinct().order_by("code")
    )


def charger(resultat: dict[str, Any]) -> dict[str, int]:
    if Agent.objects.filter(identifiant_ad__startswith="gardien").exists():
        return {}
    faux = Generateur(4)
    sites = _sites_gardiennes()
    if not sites:
        return {}
    ssiap, psc1 = TypeHabilitation.objects.get(code="ssiap1"), TypeHabilitation.objects.get(code="psc1")
    aujourd_hui = timezone.localdate()
    agents: list[Agent] = []
    for n in range(1, 9):
        site = sites[(n - 1) % len(sites)]
        agent = Agent.objects.create(
            matricule=f"DEMO{n:04d}",
            identifiant_ad=f"gardien{n:02d}",
            prenom=faux.first_name(),
            nom=faux.last_name(),
            courriel=f"gardien{n:02d}@chatillon.test",
            telephone=faux.phone_number(),
            site_prefere=site,
        )
        agent.sites.add(site, *([sites[n % len(sites)]] if n % 3 == 0 else []))
        # Le gardien n° 8 a un SSIAP expiré : il n'est plus proposé sur les sites qui l'exigent (PER-01).
        echeance = aujourd_hui - timedelta(days=20) if n == 8 else aujourd_hui + timedelta(days=365 + 30 * n)
        HabilitationAgent.objects.create(
            agent=agent, type=ssiap, obtenue_le=echeance - timedelta(days=3 * 365), valide_jusqu_au=echeance
        )
        if n % 2:
            HabilitationAgent.objects.create(agent=agent, type=psc1, obtenue_le=aujourd_hui - timedelta(days=400))
        agents.append(agent)
    bilan = {"agents": len(agents), "trames": 0, "vacations": 0, "besoins": 0}
    saison = Saison.objects.filter(debut__lte=aujourd_hui, fin__gte=aujourd_hui).first() or resultat.get("saison")
    du, au = aujourd_hui - timedelta(days=7), aujourd_hui + timedelta(days=35)
    for site in sites:
        titulaires = [a for a in agents if a.site_prefere_id == site.pk and a.matricule != "DEMO0008"] or agents[:2]
        if saison is not None:
            trame = Trame.objects.create(nom=f"Semaine type — {site.nom}", saison=saison, site=site)
            for jour, debut, fin, rang in SEMAINE_TYPE:
                LigneTrame.objects.create(
                    trame=trame, jour=jour, heure_debut=debut, heure_fin=fin, agent=titulaires[rang % len(titulaires)]
                )
            bilan["vacations"] += services.appliquer_trame(trame, acteur=SYSTEME, du=du, au=au)["creees"]
            bilan["trames"] += 1
        calcul = du
        while calcul <= au:
            bilan["besoins"] += services.recalculer_besoins(site.pk, calcul).get("crees", 0)
            calcul += timedelta(days=1)
    # Absence la semaine prochaine : les vacations du gardien redeviennent à pourvoir, un remplaçant est proposé.
    lundi = aujourd_hui + timedelta(days=7 - aujourd_hui.weekday())
    services.saisir_absence(
        agents[0],
        acteur=SYSTEME,
        debut=datetime.combine(lundi, time(0), tzinfo=PARIS),
        fin=datetime.combine(lundi + timedelta(days=2), time(23, 59), tzinfo=PARIS),
        nature="formation",
        commentaire="Recyclage SSIAP",
    )
    _incident(agents[1], aujourd_hui)
    bilan["incidents"] = Incident.objects.count()
    return bilan


def _incident(agent: Agent, jour: date) -> None:
    seance = (
        Occurrence.objects.filter(
            Q(espace__batiment__site__in=agent.sites.all()), debut__date__lt=jour, statut__in=["validee", "confirmee", "realisee"]
        )
        .select_related("espace__batiment__site")
        .order_by("-debut")
        .first()
    )
    site = seance.espace.batiment.site if seance else agent.site_prefere
    if site is None:
        return
    services.signaler_incident(
        acteur=SYSTEME,
        source="mobile",
        site=site,
        nature="degradation",
        gravite="mineur",
        description="Panneau de basket : filet arraché côté vestiaires.",
        constate_le=seance.fin if seance else timezone.now() - timedelta(days=1),
        occurrence=seance,
        agent=agent,
    )
