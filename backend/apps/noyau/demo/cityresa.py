"""Données d'exemple de CityResa (`cityresa.json`, produit par `outils/cityresa/extraire.mjs`) : mêmes sites, espaces,
usagers et réservations que l'application CityResa, pour comparer les deux applications avec les mêmes données.

Les associations de CityResa viennent du guide des sports de la Ville : seules les structures sont reprises, leurs
contacts sont fictifs (CLAUDE.md, règle 7). Les dates sont décalées d'un nombre entier de semaines depuis le jour de
l'extraction : la disposition des réservations par rapport à aujourd'hui et leurs jours de semaine sont conservés.
"""

from __future__ import annotations

import json
from datetime import date, time, timedelta
from decimal import Decimal
from pathlib import Path
from typing import Any

from dateutil.relativedelta import relativedelta
from django.utils import timezone

from apps.noyau.exceptions import ErreurMetier
from apps.referentiel.models import Batiment, Espace, FamilleEspace, HoraireOuverture, Saison, Site
from apps.reservations import services
from apps.reservations.models import Dossier, Reservation, TypeReservation
from apps.usagers.models import Contact, Rattachement, Usager

SYSTEME = services.SYSTEME
DONNEES = Path(__file__).parent / "cityresa.json"

FAMILLES = {
    "Gymnase": "gymnase",
    "Dojo": "dojo",
    "Stade / terrain": "terrain-exterieur",
    "Salle de réunion": "salle-reunion",
    "Salle polyvalente": "salle-associative",
    "Salle des fêtes": "salle-fetes",
    "Auditorium": "salle-spectacle",
}
SPORTIVES = {"gymnase", "dojo", "terrain-exterieur", "salle-sport"}
TYPES_USAGER = {"service_interne": "service_municipal"}
JOURS_RRULE = {1: "MO", 2: "TU", 3: "WE", 4: "TH", 5: "FR", 6: "SA", 7: "SU"}


def donnees() -> dict[str, Any]:
    return json.loads(DONNEES.read_text(encoding="utf-8"))


def _decalage(reference: str) -> timedelta:
    """Semaines entières écoulées depuis l'extraction : les jours de semaine des créneaux ne bougent pas."""
    ecart = (timezone.localdate() - date.fromisoformat(reference)).days
    return timedelta(days=7 * (ecart // 7))


def _heure(texte: str) -> time:
    heures, minutes = (int(x) for x in texte.split(":"))
    return time(23, 59) if heures >= 24 or (heures, minutes) == (0, 0) else time(heures, minutes)


# --- Sites et espaces --------------------------------------------------------------------------------------------


def referentiel(d: dict[str, Any], bilan: Any) -> dict[str, Espace]:
    familles = {f.code: f for f in FamilleEspace.objects.all()}
    sites, batiments = {}, {}
    natures = {e["site"]: FAMILLES.get(e["nature"] or "", "salle-associative") for e in d["espaces"]}
    for s in d["sites"]:
        sites[s["cle"]] = Site.objects.create(
            code=f"demo-{s['cle']}",
            nom=s["name"],
            adresse=s["address"],
            code_postal=s["postalCode"],
            commune=s["city"],
            latitude=Decimal(str(round(s["lat"], 6))),
            longitude=Decimal(str(round(s["lng"], 6))),
            acces=s["accessInfo"],
        )
        # CityResa ne distingue pas les bâtiments : un bâtiment par site, au nom du site.
        batiments[s["cle"]] = Batiment.objects.create(
            site=sites[s["cle"]],
            nom=s["name"],
            erp_type="X" if natures.get(s["cle"]) in SPORTIVES else "L",
            erp_categorie="3",
        )
    espaces: dict[str, Espace] = {}
    for e in d["espaces"]:
        famille = FAMILLES.get(e["nature"] or "", "salle-associative")
        description = e["description"]
        if e.get("rules"):
            description += f"\n\nRèglement : {e['rules']}"
        if e.get("instructions"):
            description += f"\n\nConsignes : {e['instructions']}"
        profils = e.get("allowedProfiles") or []
        espaces[e["cle"]] = Espace.objects.create(
            batiment=batiments[e["site"]],
            code=e["cle"],
            nom=e["name"],
            famille=familles[famille],
            capacite=max(e.get("standing") or 0, e.get("seated") or 0),
            surface_m2=e.get("surface") or 0,
            accessible_pmr="Accès PMR" in e["equipements"],
            equipements=", ".join(e["equipements"]),
            gardiennage_requis=famille in SPORTIVES | {"salle-fetes", "salle-spectacle"},
            temps_ouverture_min=e.get("bufferBeforeMin") or 0,
            temps_fermeture_min=e.get("bufferAfterMin") or 0,
            reservable_portail=not profils or any(p != "service_interne" for p in profils),
            description=description,
        )
        for jour, plages in e["horaires"].items():
            for debut, fin in plages:
                HoraireOuverture.objects.create(
                    espace=espaces[e["cle"]], jour_semaine=int(jour) - 1, debut=_heure(debut), fin=_heure(fin)
                )
    bilan.ajouter("sites", len(sites))
    bilan.ajouter("espaces", len(espaces))
    return espaces


# --- Usagers -----------------------------------------------------------------------------------------------------


def usagers(
    d: dict[str, Any], bilan: Any, faux: Any, contact_fictif: Any, pieces_valides: Any
) -> tuple[dict[str, list[Usager]], dict[str, Usager]]:
    par_type: dict[str, list[Usager]] = {
        t: [] for t in ("association", "ecole", "entreprise", "particulier", "service_municipal")
    }
    par_cle: dict[str, Usager] = {}
    for o in d["usagers"]:
        type_usager = TYPES_USAGER.get(o["type"], o["type"])
        observations = o.get("notes", "")
        if o.get("siteWeb"):
            observations = f"Site web : {o['siteWeb']}" + (f"\n{observations}" if observations else "")
        usager = Usager.objects.create(
            type=type_usager,
            nom=o["nom"],
            siret=o.get("siret", ""),
            rna=o.get("rna", ""),
            adresse=o.get("adresse") or (faux.street_address() if type_usager != "service_municipal" else ""),
            code_postal=o.get("codePostal", ""),
            commune=o.get("commune", ""),
            local=type_usager == "association" and o.get("commune") == "Châtillon",
            statut="valide" if o.get("valide", True) else "en_attente",
            observations=observations,
        )
        if o["contactFictif"]:
            contact = contact_fictif(faux, "exemple.test")
        else:
            c = o["contact"]
            contact = Contact.objects.create(prenom=c["prenom"], nom=c["nom"], courriel=c["courriel"], telephone=c["telephone"])
        Rattachement.objects.create(
            usager=usager,
            contact=contact,
            role="president" if type_usager == "association" else "responsable",
            principal=True,
            peut_signer=True,
        )
        if type_usager == "association":
            Rattachement.objects.create(usager=usager, contact=contact_fictif(faux, "exemple.test"), role="tresorier")
        if type_usager != "service_municipal" and usager.statut == "valide":
            pieces_valides(usager)
        par_type.setdefault(type_usager, []).append(usager)
        par_cle[o["cle"]] = usager
        bilan.ajouter(f"usagers_{type_usager}")
    return par_type, par_cle


# --- Réservations ------------------------------------------------------------------------------------------------


def _type_reservation(usager: Usager, recurrente: bool) -> str:
    if usager.type == "particulier":
        return "location"
    if usager.type == "service_municipal":
        return "municipal"
    if usager.type == "association" and recurrente:
        return "creneau_annuel"
    return "ponctuelle"


def _statut(reservation: Reservation, statut: str, motif: str) -> None:
    """Statuts de CityResa → statuts de la plateforme (chemins de transition autorisés, verrous des créneaux fermes)."""
    if statut == "en_traitement":
        services._changer_statut(reservation, "en_instruction", SYSTEME)
    elif statut == "refusee":
        services._changer_statut(reservation, "refusee", SYSTEME, motif_refus=motif or "Demande déclinée.")
    elif statut in {"acceptee", "signee", "confirmee", "terminee", "archivee", "annulee"}:
        services._changer_statut(reservation, "validee", SYSTEME, valide_le=timezone.now())
        if statut in {"acceptee", "signee", "confirmee"}:
            feuilles = reservation.espace.feuilles()
            for occurrence in reservation.occurrences.filter(statut="validee"):
                services.poser_verrous(occurrence, feuilles)
        if statut == "confirmee":
            services._changer_statut(reservation, "confirmee", SYSTEME, confirme_le=timezone.now())
        elif statut in {"terminee", "archivee"}:
            services._changer_statut(reservation, "realisee", SYSTEME)
            reservation.occurrences.update(statut="realisee")
            if statut == "archivee":
                services._changer_statut(reservation, "cloturee", SYSTEME)
                reservation.occurrences.update(statut="cloturee")
        elif statut == "annulee":
            services._changer_statut(reservation, "annulee", SYSTEME, motif_annulation=motif or "Annulée par l'usager.")
            reservation.occurrences.update(statut="annulee")


def _regle(recurrence: dict[str, Any], jour: date, decalage: timedelta) -> tuple[str, date]:
    """Récurrence de CityResa (hebdomadaire jusqu'à une date, quotidienne ou mensuelle sur N séances) → règle RFC 5545
    et dernière date."""
    frequence = {"daily": "DAILY", "weekly": "WEEKLY", "monthly": "MONTHLY"}[recurrence["freq"]]
    intervalle = recurrence.get("interval") or 1
    regle = f"FREQ={frequence};INTERVAL={intervalle}"
    if frequence == "WEEKLY":
        jours = recurrence.get("byWeekday") or [jour.isoweekday()]
        regle += ";BYDAY=" + ",".join(JOURS_RRULE[j] for j in jours)
    if recurrence.get("until"):
        return regle, date.fromisoformat(recurrence["until"]) + decalage
    nombre = recurrence.get("count") or 1
    regle += f";COUNT={nombre}"
    pas = (nombre - 1) * intervalle
    if frequence == "DAILY":
        return regle, jour + timedelta(days=pas)
    if frequence == "WEEKLY":
        return regle, jour + timedelta(weeks=pas)
    return regle, jour + relativedelta(months=pas)


def reservations(
    d: dict[str, Any], bilan: Any, espaces: dict[str, Espace], par_cle: dict[str, Usager], saison: Saison
) -> list[tuple[Reservation, list[list[Any]]]]:
    """Les réservations de CityResa, à leurs dates (décalées de semaines entières) ; renvoie le matériel demandé."""
    decalage = _decalage(d["reference"])
    materiels: list[tuple[Reservation, list[list[Any]]]] = []
    ecartees = 0
    for r in d["reservations"]:
        usager, espace = par_cle[r["org"]], espaces[r["espace"]]
        recurrence = r.get("recurrence")
        jour = date.fromisoformat(r["ymd"]) + decalage
        type_code = _type_reservation(usager, bool(recurrence))
        rattachement = usager.rattachements.filter(principal=True).first()
        dossier = services.creer_dossier(
            acteur=SYSTEME,
            usager=usager,
            type_reservation=TypeReservation.objects.get(code=type_code),
            objet=r["titre"],
            saison=saison if type_code == "creneau_annuel" else None,
            contact=rattachement.contact if rattachement else None,
        )
        Dossier.objects.filter(pk=dossier.pk).update(
            activite=r.get("nature") or "",
            effectif=r.get("participants") or 0,
            observations=r.get("description") or "",
            origine="portail" if r.get("source") == "portail" else ("ville" if usager.type == "service_municipal" else "guichet"),
        )
        regle, date_fin, exdates = "", jour, []
        if recurrence:
            regle, date_fin = _regle(recurrence, jour, decalage)
            exdates = [date.fromisoformat(x) + decalage for x in recurrence.get("except", [])]
        try:
            reservation = services.ajouter_reservation(
                dossier,
                acteur=SYSTEME,
                espace=espace,
                date_debut=jour,
                date_fin=date_fin,
                heure_debut=_heure(r["de"]),
                heure_fin=_heure(r["a"]),
                recurrence=regle,
                # CityResa n'écarte ni les vacances ni les jours fériés : mêmes séances des deux côtés.
                exclure_vacances=False,
                exclure_feries=False,
                exdates=exdates,
                forcer_horaires=True,
                motif_forcage="Reprise des données d'exemple de CityResa",
            )
            _statut(reservation, r["statut"], r.get("motif") or "")
        except ErreurMetier:
            Dossier.objects.filter(pk=dossier.pk).delete()
            ecartees += 1
            continue
        bilan.ajouter(f"reservations_{type_code}")
        if r.get("materiels"):
            materiels.append((reservation, r["materiels"]))
    if ecartees:
        bilan.ajouter("reservations_ecartees", ecartees)
    return materiels
