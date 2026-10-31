"""Contrôle des droits rôle × périmètre, côté serveur, objet par objet (RG-14)."""

from __future__ import annotations

from typing import Any, Protocol, TypeVar

from django.db.models import Model, QuerySet

from apps.audit.services import journaliser
from apps.noyau.exceptions import AccesRefuse, ErreurValidation

from .actions import ACTIONS
from .models import GroupeAD, Habilitation, Perimetre, Role, Utilisateur

M = TypeVar("M", bound=Model)


class ObjetSitue(Protocol):
    def sites_concernes(self) -> set[int] | None:
        """Identifiants des sites de l'objet, ou None pour un objet transversal (non rattaché à un site)."""
        ...


def _sites(objet: object) -> set[int] | None:
    methode = getattr(objet, "sites_concernes", None)
    if methode is None:
        return set()
    return methode()


def peut(utilisateur: Utilisateur | None, action: str, objet: object | None = None) -> bool:
    """Vrai si l'agent dispose de `action` sur un périmètre qui couvre `objet`.

    - sans objet : l'action est accordée sur au moins un périmètre ;
    - objet transversal (`sites_concernes()` renvoie None) : idem ;
    - objet situé : l'un de ses sites doit appartenir au périmètre (ou périmètre « tous sites ») ;
    - objet sans site ni méthode : seul un périmètre « tous sites » l'autorise.
    """
    if action not in ACTIONS:
        raise ValueError(f"Action inconnue : {action}")
    if utilisateur is None or not getattr(utilisateur, "is_authenticated", False) or not utilisateur.is_active:
        return False
    habilitations = [h for h in utilisateur.habilitations_actives() if action in h.role.actions]
    if not habilitations:
        return False
    if objet is None:
        return True
    sites = _sites(objet)
    if sites is None:
        return True
    for habilitation in habilitations:
        if habilitation.perimetre.tous_sites:
            return True
        if sites & {s.pk for s in habilitation.perimetre.sites.all()}:
            return True
    return False


def exiger(utilisateur: Utilisateur | None, action: str, objet: object | None = None) -> None:
    if not peut(utilisateur, action, objet):
        raise AccesRefuse("Vous n'avez pas les droits pour cette action.", code="droits_insuffisants")


def sites_autorises(utilisateur: Utilisateur, action: str) -> set[int] | None:
    """Sites sur lesquels l'agent peut exercer `action` ; None = tous les sites."""
    sites: set[int] = set()
    for habilitation in utilisateur.habilitations_actives():
        if action not in habilitation.role.actions:
            continue
        if habilitation.perimetre.tous_sites:
            return None
        sites |= {s.pk for s in habilitation.perimetre.sites.all()}
    return sites


def filtrer_par_perimetre(qs: QuerySet[M], utilisateur: Utilisateur, action: str, chemin_site: str) -> QuerySet[M]:
    """Restreint un QuerySet aux objets dont le site (atteint par `chemin_site`) est dans le périmètre."""
    if not peut(utilisateur, action):
        return qs.none()
    sites = sites_autorises(utilisateur, action)
    if sites is None:
        return qs
    return qs.filter(**{f"{chemin_site}__in": sites}).distinct()


def actions_par_perimetre(utilisateur: Utilisateur) -> list[dict[str, Any]]:
    """Ce que renvoie /api/gestion/moi : les actions autorisées par périmètre (l'UI masque, l'API refuse)."""
    resultat = []
    for h in utilisateur.habilitations_actives():
        resultat.append(
            {
                "role": h.role.code,
                "role_libelle": h.role.libelle,
                "perimetre": h.perimetre.nom,
                "tous_sites": h.perimetre.tous_sites,
                "sites": sorted(s.pk for s in h.perimetre.sites.all()),
                "actions": sorted(h.role.actions),
            }
        )
    return resultat


def verifier_actions(actions: list[str]) -> None:
    inconnues = sorted(set(actions) - set(ACTIONS))
    if inconnues:
        raise ErreurValidation("Actions inconnues : " + ", ".join(inconnues), code="actions_inconnues")


def attribuer(acteur: Utilisateur, utilisateur: Utilisateur, role: Role, perimetre: Perimetre, **dates: Any) -> Habilitation:
    """Attribution manuelle d'un rôle sur un périmètre (ADM-03)."""
    exiger(acteur, "administrer")
    habilitation, _ = Habilitation.objects.update_or_create(
        utilisateur=utilisateur, role=role, perimetre=perimetre, source="manuel", defaults=dates
    )
    journaliser(
        "attribuer_habilitation",
        habilitation,
        apres={"role": role.code, "perimetre": perimetre.nom, **{k: str(v) for k, v in dates.items()}},
    )
    utilisateur.vider_cache_habilitations()
    return habilitation


def retirer(acteur: Utilisateur, habilitation: Habilitation) -> None:
    exiger(acteur, "administrer")
    if habilitation.source == "ad":
        raise ErreurValidation(
            "Cette habilitation provient d'un groupe AD : retirez l'agent du groupe dans l'annuaire.",
            code="habilitation_ad",
        )
    journaliser(
        "retirer_habilitation", habilitation, avant={"role": habilitation.role.code, "perimetre": habilitation.perimetre.nom}
    )
    habilitation.delete()


def synchroniser_groupes_ad(utilisateur: Utilisateur, dns_groupes: list[str]) -> list[Habilitation]:
    """Aligne les habilitations « ad » de l'agent sur ses groupes AD correspondants (ADM-06)."""
    dns = {dn.strip().lower() for dn in dns_groupes}
    correspondances = [g for g in GroupeAD.objects.filter(actif=True).select_related("role", "perimetre") if g.dn.lower() in dns]
    attendues = {(g.role_id, g.perimetre_id): g for g in correspondances}
    existantes = {(h.role_id, h.perimetre_id): h for h in utilisateur.habilitations.filter(source="ad")}
    for cle, habilitation in existantes.items():
        if cle not in attendues:
            journaliser("retirer_habilitation_ad", habilitation, avant={"groupe": habilitation.groupe_ad_id})
            habilitation.delete()
    for cle, groupe in attendues.items():
        if cle not in existantes:
            habilitation = Habilitation.objects.create(
                utilisateur=utilisateur, role=groupe.role, perimetre=groupe.perimetre, source="ad", groupe_ad=groupe
            )
            journaliser("attribuer_habilitation_ad", habilitation, apres={"groupe": groupe.dn, "role": groupe.role.code})
    utilisateur.vider_cache_habilitations()
    return list(utilisateur.habilitations.filter(source="ad"))
