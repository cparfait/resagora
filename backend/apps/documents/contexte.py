"""Contexte typé de fusion des modèles (DOC-03) : uniquement des valeurs simples, jamais d'objet ORM.

Les variables disponibles dans Word (`{{ usager.nom }}`, `{% for r in reservations %}`…) sont décrites
par `VARIABLES` (affichées dans l'écran des modèles). Les montants sont des chaînes en euros formatées
à la française ; les dates sont en heure de Paris ; la récurrence est lisible (« tous les mardis de
18 h à 20 h, hors vacances scolaires »).
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from django.utils import timezone
from django.utils.formats import date_format

from apps.noyau.parametres import parametre
from apps.reservations.models import STATUTS_ACTIFS, Dossier, Occurrence
from apps.reservations.recurrence import PARIS

Contexte = dict[str, Any]
FOURNISSEURS: dict[str, Callable[[Any], Contexte]] = {}
VARIABLES: dict[str, list[str]] = {}


def fournisseur(*natures: str, variables: list[str]) -> Callable[[Callable[[Any], Contexte]], Callable[[Any], Contexte]]:
    """Enregistre la fonction qui construit le contexte d'une ou plusieurs natures de document."""

    def enregistrer(fonction: Callable[[Any], Contexte]) -> Callable[[Any], Contexte]:
        for nature in natures:
            FOURNISSEURS[nature] = fonction
            VARIABLES[nature] = ["ville.*", "date_edition", *variables]
        return fonction

    return enregistrer


def date_longue(valeur: Any) -> str:
    return date_format(valeur, "j F Y") if valeur else ""


def instant_lisible(valeur: Any) -> str:
    return date_format(timezone.localtime(valeur, PARIS), "l j F Y à H\\hi") if valeur else ""


def ville() -> Contexte:
    return {
        "nom": parametre("ville.nom"),
        "adresse": parametre("ville.adresse"),
        "service": parametre("ville.service"),
        "telephone": parametre("ville.telephone"),
        "courriel": parametre("ville.courriel"),
        "signataire_nom": parametre("signature.elu_nom"),
        "signataire_qualite": parametre("signature.elu_qualite"),
        "deliberation": parametre("documents.deliberation_reference"),
    }


def base() -> Contexte:
    return {"ville": ville(), "date_edition": date_longue(timezone.localdate())}


def contexte_usager(usager: Any) -> Contexte:
    signataire = usager.rattachements.select_related("contact").filter(peut_signer=True).order_by("-principal").first()
    principal = signataire or usager.rattachements.select_related("contact").order_by("-principal").first()
    return {
        "nom": usager.nom,
        "type": usager.get_type_display(),
        "sigle": usager.sigle,
        "siret": usager.siret,
        "rna": usager.rna,
        "adresse": ", ".join(filter(None, [usager.adresse, f"{usager.code_postal} {usager.commune}".strip()])),
        "telephone": usager.telephone,
        "courriel": usager.courriel,
        "resident": "oui" if usager.resident else "non",
        "representant": str(principal.contact) if principal else "",
        "representant_qualite": principal.get_role_display() if principal else "",
    }


def contexte_reservation(reservation: Any) -> Contexte:
    espace = reservation.espace
    seances = reservation.occurrences.exclude(statut__in=["annulee", "refusee"]).order_by("debut")
    return {
        "espace": espace.nom,
        "site": espace.batiment.site.nom,
        "adresse": ", ".join(filter(None, [espace.batiment.site.adresse, espace.batiment.site.commune])),
        "description": reservation.description,
        "date_debut": date_longue(reservation.date_debut),
        "date_fin": date_longue(reservation.date_fin),
        "heure_debut": reservation.heure_debut.strftime("%H:%M"),
        "heure_fin": reservation.heure_fin.strftime("%H:%M"),
        "nombre_seances": seances.count(),
        "capacite": espace.capacite,
        "gardiennage": "oui" if espace.gardiennage_requis else "non",
        "statut": reservation.get_statut_display(),
        "seances": [instant_lisible(o.debut) for o in seances[:60]],
    }


@fournisseur(
    "convention",
    "contrat_location",
    "avenant",
    variables=[
        "dossier.numero",
        "dossier.objet",
        "dossier.activite",
        "dossier.effectif",
        "dossier.type",
        "usager.nom",
        "usager.adresse",
        "usager.siret",
        "usager.rna",
        "usager.representant",
        "usager.representant_qualite",
        "reservations[].espace",
        "reservations[].site",
        "reservations[].description",
        "reservations[].nombre_seances",
        "reservations[].seances[]",
        "conditions[]",
        "saison",
        "avenant.numero_origine",
        "avenant.motif",
    ],
)
def contexte_dossier(dossier: Dossier) -> Contexte:
    reservations = dossier.reservations.select_related("espace__batiment__site").filter(statut__in=STATUTS_ACTIFS)
    type_reservation = dossier.type_reservation
    conditions = [
        libelle
        for libelle, exige in (
            ("pièces justificatives valides (assurance, statuts…)", type_reservation.exige_pieces),
            ("signature de la présente convention", type_reservation.exige_convention),
            ("versement de l'acompte", type_reservation.exige_acompte),
            ("dépôt de la caution", type_reservation.exige_caution),
        )
        if exige
    ]
    return {
        **base(),
        "dossier": {
            "numero": dossier.numero,
            "objet": dossier.objet,
            "activite": dossier.activite,
            "effectif": dossier.effectif or "",
            "type": type_reservation.libelle,
            "depose_le": date_longue(dossier.depose_le),
        },
        "usager": contexte_usager(dossier.usager),
        "reservations": [contexte_reservation(r) for r in reservations],
        "conditions": conditions,
        "saison": dossier.saison.nom if dossier.saison is not None else "",
        "avenant": {"numero_origine": "", "motif": ""},
    }


@fournisseur(
    "attribution",
    "refus",
    variables=["usager.*", "saison", "attribues[]", "refuses[].creneau", "refuses[].motif", "dossier.numero"],
)
def contexte_decision(dossier: Dossier) -> Contexte:
    reservations = list(dossier.reservations.select_related("espace__batiment__site"))
    return {
        **base(),
        "dossier": {"numero": dossier.numero, "objet": dossier.objet},
        "usager": contexte_usager(dossier.usager),
        "saison": dossier.saison.nom if dossier.saison is not None else "",
        "attribues": [f"{r.espace.nom} : {r.description}" for r in reservations if r.statut in {"validee", "confirmee"}],
        "refuses": [
            {"creneau": f"{r.espace.nom} : {r.description}", "motif": r.motif_refus}
            for r in reservations
            if r.statut == "refusee"
        ],
    }


@fournisseur(
    "fermeture",
    variables=["fermeture.lieu", "fermeture.debut", "fermeture.fin", "fermeture.motif", "seances[]", "usager.*"],
)
def contexte_fermeture(element: tuple[Any, Any]) -> Contexte:
    """Avis de fermeture pour un usager : `(fermeture, usager)`."""
    fermeture, usager = element
    lies: set[int] = set()
    for espace in fermeture.espaces_concernes():
        lies |= espace.ids_lies()
    seances = Occurrence.objects.filter(
        espace_id__in=lies, debut__lt=fermeture.fin, fin__gt=fermeture.debut, reservation__dossier__usager=usager
    ).select_related("espace")
    lieu = fermeture.espace.nom if fermeture.espace_id else fermeture.site.nom if fermeture.site_id else ""
    return {
        **base(),
        "usager": contexte_usager(usager),
        "fermeture": {
            "lieu": lieu,
            "debut": instant_lisible(fermeture.debut),
            "fin": instant_lisible(fermeture.fin),
            "motif": fermeture.motif,
        },
        "seances": [f"{o.espace.nom}, {instant_lisible(o.debut)}" for o in seances],
    }


@fournisseur(
    "etat_des_lieux",
    variables=["seance.espace", "seance.debut", "seance.fin", "usager.*", "dossier.numero", "gardien", "materiel[]"],
)
def contexte_etat_des_lieux(occurrence: Occurrence) -> Contexte:
    reservation = occurrence.reservation
    return {
        **base(),
        "dossier": {"numero": reservation.dossier.numero, "objet": reservation.dossier.objet},
        "usager": contexte_usager(reservation.dossier.usager),
        "seance": {
            "espace": occurrence.espace.nom,
            "site": occurrence.espace.batiment.site.nom,
            "debut": instant_lisible(occurrence.debut),
            "fin": instant_lisible(occurrence.fin),
        },
        "gardien": "",
        "materiel": [],
    }


def construire(nature: str, objet: Any) -> Contexte:
    fonction = FOURNISSEURS.get(nature)
    if fonction is None:
        from apps.noyau.exceptions import ErreurValidation

        raise ErreurValidation(f"Aucun contexte de fusion pour la nature « {nature} ».", code="nature_sans_contexte")
    return fonction(objet)
