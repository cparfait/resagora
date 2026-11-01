"""Planning du personnel (PER-02 à PER-09, RG-09, RG-10) : besoins issus des séances gardiennées, vacations,
affectation conforme aux règles, absences et remplacements, trames, compteurs, iCal, incidents."""

from __future__ import annotations

import csv
import io
import secrets
from collections.abc import Iterable
from datetime import UTC, date, datetime, time, timedelta
from typing import Any

from django.conf import settings
from django.db import IntegrityError, transaction
from django.db.models import Q, QuerySet
from django.utils import timezone

from apps.audit.services import journaliser
from apps.communication.services import notifier
from apps.habilitations.models import Utilisateur
from apps.habilitations.services import exiger, peut
from apps.noyau import ical
from apps.noyau.chiffrement import empreinte_hmac
from apps.noyau.exceptions import AccesRefuse, ErreurMetier, ErreurValidation
from apps.noyau.parametres import parametre
from apps.noyau.tableur import cellule_sure
from apps.referentiel.models import Site
from apps.reservations.models import Occurrence
from apps.reservations.recurrence import PARIS

from . import regles
from .models import Absence, Agent, Besoin, HabilitationAgent, Incident, JetonIcal, Trame, TypeHabilitation, Vacation

SYSTEME = "système"
# Une séance réalisée ou clôturée a bien été gardiennée : son besoin et sa vacation restent (RG-09).
STATUTS_GARDIENNES = ("validee", "confirmee", "realisee", "cloturee")
STATUTS_ACTIFS_VACATION = ("planifiee", "a_pourvoir", "a_revoir")


def _controler(acteur: Any, action: str, objet: Any = None) -> None:
    if acteur == SYSTEME:
        return
    if isinstance(acteur, Utilisateur):
        exiger(acteur, action, objet)
        return
    raise AccesRefuse("Vous n'avez pas les droits pour cette action.", code="droits_insuffisants")


def _bornes_jour(jour: date) -> tuple[datetime, datetime]:
    debut = datetime.combine(jour, time.min, tzinfo=PARIS)
    return debut, debut + timedelta(days=1)


def _texte(instant: datetime) -> str:
    return timezone.localtime(instant, PARIS).strftime("%d/%m/%Y %H:%M")


# --- Besoins (PER-02, RG-09) --------------------------------------------------------------------------------


def _plages_du_jour(site_id: int, jour: date) -> list[tuple[datetime, datetime, list[Occurrence]]]:
    """Plages de présence du jour : séances gardiennées commençant ce jour-là, temps d'ouverture et de fermeture
    compris, fusionnées quand elles se touchent (tri sur le début de plage, propre à chaque espace). Une séance prise
    dans une fermeture exceptionnelle (REF-06) n'appelle pas de gardien : l'enregistrement de la fermeture recalcule
    les besoins et met les vacations concernées « à revoir » (scénario transverse 3)."""
    from apps.reservations.services import fermetures_touchant

    debut, fin = _bornes_jour(jour)
    seances = Occurrence.objects.filter(
        espace__batiment__site_id=site_id,
        espace__gardiennage_requis=True,
        statut__in=STATUTS_GARDIENNES,
        debut__gte=debut,
        debut__lt=fin,
    ).select_related("espace__batiment")
    brutes = []
    for occurrence in seances:
        if fermetures_touchant(occurrence.espace, occurrence.debut, occurrence.fin).exists():
            continue
        plage = occurrence.espace.plage_gardiennage(occurrence.debut, occurrence.fin)
        if plage is not None:
            brutes.append((plage[0], plage[1], occurrence))
    plages: list[tuple[datetime, datetime, list[Occurrence]]] = []
    for plage_debut, plage_fin, occurrence in sorted(brutes, key=lambda b: (b[0], b[1])):
        if plages and plage_debut <= plages[-1][1]:
            precedente = plages[-1]
            plages[-1] = (precedente[0], max(precedente[1], plage_fin), [*precedente[2], occurrence])
        else:
            plages.append((plage_debut, plage_fin, [occurrence]))
    return plages


def _mettre_a_revoir(vacations: Iterable[Vacation], motif: str) -> int:
    nombre = 0
    for vacation in vacations:
        if vacation.statut not in {"planifiee", "a_pourvoir"}:
            continue
        vacation.statut, vacation.signalement = "a_revoir", motif[:300]
        vacation.save(update_fields=["statut", "signalement"])
        nombre += 1
        if vacation.agent and vacation.agent.courriel:
            notifier(
                "vacation_a_revoir",
                {
                    "agent": str(vacation.agent),
                    "site": vacation.site.nom,
                    "debut": _texte(vacation.debut),
                    "fin": _texte(vacation.fin),
                    "motif": motif,
                },
                courriels=[vacation.agent.courriel],
                objet=vacation,
            )
    return nombre


def mettre_a_jour_couverture(besoin: Besoin) -> Besoin:
    if besoin.statut == "supprime":
        return besoin
    vacations = sorted(
        besoin.site.vacations.filter(
            statut="planifiee", agent__isnull=False, debut__lt=besoin.fin, fin__gt=besoin.debut
        ).values_list("debut", "fin")
    )
    curseur = besoin.debut
    for debut, fin in vacations:
        if debut > curseur:
            break
        curseur = max(curseur, fin)
    statut = "couvert" if curseur >= besoin.fin else "a_couvrir"
    if statut != besoin.statut:
        besoin.statut = statut
        besoin.save(update_fields=["statut", "modifie_le"])
    return besoin


def _rattacher_vacations(besoin: Besoin) -> None:
    """Toute vacation du site qui chevauche le besoin le couvre, même créée avant lui (trame appliquée d'avance)."""
    for vacation in Vacation.objects.filter(site_id=besoin.site_id, debut__lt=besoin.fin, fin__gt=besoin.debut).exclude(
        statut="annulee"
    ):
        vacation.besoins.add(besoin)


@transaction.atomic
def recalculer_besoins(site_id: int, jour: date) -> dict[str, int]:
    """Recalcule les besoins d'un site pour une journée ; une plage modifiée ou supprimée met ses vacations « à revoir »
    et prévient l'agent (RG-09). Seuls les besoins rattachés à ce jour sont repris (une plage du soir qui déborde
    sur le lendemain, ou qui commence la veille, reste à son jour)."""
    debut, fin = _bornes_jour(jour)
    existants = list(
        Besoin.objects.select_for_update()
        .filter(site_id=site_id)
        .filter(Q(jour=jour) | Q(jour__isnull=True, debut__gte=debut, debut__lt=fin))
        .exclude(statut="supprime")
    )
    bilan = {"crees": 0, "modifies": 0, "supprimes": 0, "a_revoir": 0}
    utilises: set[int] = set()
    for plage_debut, plage_fin, seances in _plages_du_jour(site_id, jour):
        identique = next((b for b in existants if b.pk not in utilises and b.debut == plage_debut and b.fin == plage_fin), None)
        chevauchant = identique or next(
            (b for b in existants if b.pk not in utilises and b.debut < plage_fin and b.fin > plage_debut), None
        )
        if chevauchant is None:
            besoin = Besoin.objects.create(site_id=site_id, debut=plage_debut, fin=plage_fin, jour=jour)
            bilan["crees"] += 1
        else:
            besoin = chevauchant
            if besoin.jour is None:
                besoin.jour = jour
                besoin.save(update_fields=["jour"])
            if identique is None:
                ancien = f"{_texte(besoin.debut)}–{timezone.localtime(besoin.fin, PARIS):%H:%M}"
                besoin.debut, besoin.fin = plage_debut, plage_fin
                besoin.save(update_fields=["debut", "fin", "modifie_le"])
                bilan["modifies"] += 1
                bilan["a_revoir"] += _mettre_a_revoir(
                    besoin.vacations.select_related("agent", "site"),
                    f"Réservations modifiées : besoin {ancien} devenu {_texte(plage_debut)}–{timezone.localtime(plage_fin, PARIS):%H:%M}",
                )
        utilises.add(besoin.pk)
        besoin.occurrences.set(seances)
        _rattacher_vacations(besoin)
        mettre_a_jour_couverture(besoin)
    for besoin in existants:
        if besoin.pk in utilises:
            continue
        besoin.statut = "supprime"
        besoin.save(update_fields=["statut", "modifie_le"])
        besoin.occurrences.clear()
        bilan["supprimes"] += 1
        bilan["a_revoir"] += _mettre_a_revoir(
            besoin.vacations.select_related("agent", "site"), f"Séances annulées : besoin du {_texte(besoin.debut)} supprimé"
        )
    return bilan


def recalculer_pour_occurrence(occurrence_id: int) -> None:
    occurrence = Occurrence.objects.select_related("espace__batiment").filter(pk=occurrence_id).first()
    if occurrence is None or not occurrence.espace.gardiennage_requis:
        return
    recalculer_besoins(occurrence.espace.batiment.site_id, timezone.localtime(occurrence.debut, PARIS).date())


def creer_vacation_pour_besoin(besoin: Besoin, *, acteur: Any) -> Vacation:
    """Vacation à pourvoir couvrant exactement le besoin (le planificateur affecte ensuite un agent)."""
    _controler(acteur, "planifier_personnel", besoin)
    with transaction.atomic():
        vacation = Vacation.objects.create(site=besoin.site, debut=besoin.debut, fin=besoin.fin, statut="a_pourvoir")
        vacation.besoins.add(besoin)
        journaliser("creer_vacation", vacation, apres={"besoin": besoin.pk}, acteur=acteur)
    return vacation


# --- Affectation (PER-04, PER-05, RG-10) --------------------------------------------------------------------


def habilitations_manquantes(agent: Agent, jour: date) -> list[str]:
    exigees = TypeHabilitation.objects.filter(exigee_pour_gardiennage=True)
    valides = set(
        HabilitationAgent.objects.filter(agent=agent, obtenue_le__lte=jour)
        .filter(Q(valide_jusqu_au__isnull=True) | Q(valide_jusqu_au__gte=jour))
        .values_list("type_id", flat=True)
    )
    return [t.libelle for t in exigees if t.pk not in valides]


def _habilitations_manquantes_sur(agent: Agent, debut: datetime, fin: datetime) -> list[str]:
    """Habilitations exigées et valides du premier au dernier jour de la vacation (une vacation peut passer minuit)."""
    jour_debut, jour_fin = timezone.localtime(debut, PARIS).date(), timezone.localtime(fin, PARIS).date()
    return sorted({*habilitations_manquantes(agent, jour_debut), *habilitations_manquantes(agent, jour_fin)})


def _absent(agent: Agent, debut: datetime, fin: datetime) -> bool:
    return Absence.objects.filter(agent=agent, debut__lt=fin, fin__gt=debut).exists()


def _plages_agent(agent: Agent, debut: datetime, fin: datetime, exclure: int | None = None) -> list[regles.Plage]:
    qs = Vacation.objects.filter(agent=agent, statut__in=STATUTS_ACTIFS_VACATION, debut__lt=fin, fin__gt=debut).exclude(
        type="astreinte"
    )
    if exclure:
        qs = qs.exclude(pk=exclure)
    return list(qs.values_list("debut", "fin"))


def violations_pour(agent: Agent, debut: datetime, fin: datetime, exclure: int | None = None) -> list[regles.Violation]:
    """Règles évaluées sur 12 semaines autour de la vacation, en ne gardant que ce qu'elle touche."""
    fenetre = _plages_agent(agent, debut - timedelta(weeks=12), fin + timedelta(weeks=1), exclure)
    return regles.verifier([*fenetre, (debut, fin)], autour=(debut, fin))


def candidats(vacation: Vacation) -> list[dict[str, Any]]:
    """PER-04 : agents affectables (site, habilitations valides, non absents, sans chevauchement), triés par équilibre
    des heures de la semaine puis préférence de site ; les règles de temps de travail sont indiquées."""
    jour = timezone.localtime(vacation.debut, PARIS).date()
    lundi = datetime.combine(jour - timedelta(days=jour.weekday()), time.min, tzinfo=PARIS)
    resultat = []
    for agent in Agent.objects.filter(actif=True, sites=vacation.site).distinct():
        if agent.pk == vacation.agent_id:
            continue
        if _habilitations_manquantes_sur(agent, vacation.debut, vacation.fin) or _absent(agent, vacation.debut, vacation.fin):
            continue
        if (
            Vacation.objects.filter(
                agent=agent, statut__in=STATUTS_ACTIFS_VACATION, debut__lt=vacation.fin, fin__gt=vacation.debut
            )
            .exclude(pk=vacation.pk)
            .exists()
        ):
            continue
        semaine = sum(
            int((f - d).total_seconds() // 60) for d, f in _plages_agent(agent, lundi, lundi + timedelta(days=7), vacation.pk)
        )
        violations = [] if vacation.type == "astreinte" else violations_pour(agent, vacation.debut, vacation.fin, vacation.pk)
        resultat.append(
            {
                "agent": agent,
                "minutes_semaine": semaine,
                "prefere": agent.site_prefere_id == vacation.site_id,
                "violations": [v.en_dict() for v in violations],
                "conforme": not any(v.gravite == "bloquant" for v in violations),
            }
        )
    return sorted(resultat, key=lambda c: (not c["conforme"], c["minutes_semaine"], not c["prefere"], str(c["agent"])))


def _controler_affectation(
    vacation: Vacation, agent: Agent, debut: datetime, fin: datetime, *, acteur: Any, forcer: bool, motif: str
) -> tuple[list[regles.Violation], bool]:
    """Contrôles communs à l'affectation et à la modification des horaires (PER-01, PER-05, PER-06) : site, habilitations
    valides sur toute la vacation, absence, règles de temps de travail (forçage motivé, réservé à « forcer_regle »)."""
    if not agent.actif or not agent.sites.filter(pk=vacation.site_id).exists():
        raise ErreurMetier(f"{agent} n'est pas affectable à {vacation.site}.", code="site_non_affectable")
    manquantes = _habilitations_manquantes_sur(agent, debut, fin)
    if manquantes:
        jour = timezone.localtime(debut, PARIS).date()
        raise ErreurMetier(
            f"{agent} n'a pas d'habilitation valide le {jour:%d/%m/%Y} : {', '.join(manquantes)}.", code="habilitation_invalide"
        )
    if _absent(agent, debut, fin):
        raise ErreurMetier(f"{agent} est absent sur cette période.", code="agent_absent")
    if vacation.type == "astreinte":
        return [], False
    violations = violations_pour(agent, debut, fin, vacation.pk)
    bloquantes = [v for v in violations if v.gravite == "bloquant"]
    if bloquantes:
        if not forcer:
            raise ErreurMetier(
                "Règles de temps de travail non respectées : " + " ".join(v.message for v in bloquantes),
                code="regles_temps_de_travail",
                details={"violations": [v.en_dict() for v in violations]},
            )
        if acteur != SYSTEME and not (isinstance(acteur, Utilisateur) and peut(acteur, "forcer_regle", vacation)):
            raise AccesRefuse(
                "Le forçage des règles de temps de travail est réservé au planificateur habilité.", code="forcage_interdit"
            )
        if len(motif.strip()) < 10:
            raise ErreurValidation("Motivez le forçage (au moins quelques mots).", code="motif_requis")
    return violations, bool(bloquantes)


@transaction.atomic
def affecter(vacation: Vacation, agent: Agent | None, *, acteur: Any, forcer: bool = False, motif: str = "") -> Vacation:
    vacation = Vacation.objects.select_for_update().get(pk=vacation.pk)
    _controler(acteur, "planifier_personnel", vacation)
    if vacation.statut == "annulee":
        raise ErreurMetier("Cette vacation est annulée.", code="vacation_annulee")
    if agent is None:
        if vacation.arrivee_reelle:
            raise ErreurMetier(
                "L'agent a déjà pointé sur cette vacation : il ne peut plus en être retiré.", code="vacation_pointee"
            )
        vacation.agent, vacation.statut, vacation.violations, vacation.forcee, vacation.motif_forcage = (
            None,
            "a_pourvoir",
            [],
            False,
            "",
        )
        vacation.save()
        _recouvrir(vacation)
        journaliser("liberer_vacation", vacation, acteur=acteur)
        return vacation
    if vacation.arrivee_reelle and vacation.agent_id != agent.pk:
        raise ErreurMetier("Un autre agent a déjà pointé sur cette vacation.", code="vacation_pointee")
    violations, forcee = _controler_affectation(
        vacation, agent, vacation.debut, vacation.fin, acteur=acteur, forcer=forcer, motif=motif
    )
    ancien = vacation.agent
    vacation.agent, vacation.statut = agent, "planifiee"
    vacation.violations = [v.en_dict() for v in violations]
    vacation.forcee, vacation.motif_forcage = forcee, motif.strip()[:300] if forcee else ""
    vacation.signalement = ""
    try:
        with transaction.atomic():
            vacation.save()
    except IntegrityError as erreur:
        raise ErreurMetier(f"{agent} a déjà une vacation sur cette période (RG-10).", code="chevauchement_vacation") from erreur
    _recouvrir(vacation)
    journaliser(
        "affecter_vacation",
        vacation,
        avant={"agent": ancien.pk if ancien else None},
        apres={"agent": agent.pk, "forcee": vacation.forcee, "motif": vacation.motif_forcage, "violations": vacation.violations},
        acteur=acteur,
    )
    if agent.courriel:
        notifier(
            "vacation_affectee",
            {"agent": str(agent), "site": vacation.site.nom, "debut": _texte(vacation.debut), "fin": _texte(vacation.fin)},
            courriels=[agent.courriel],
            objet=vacation,
        )
    return vacation


def _recouvrir(vacation: Vacation) -> None:
    for besoin in Besoin.objects.filter(site=vacation.site, debut__lt=vacation.fin, fin__gt=vacation.debut).exclude(
        statut="supprime"
    ):
        vacation.besoins.add(besoin)
        mettre_a_jour_couverture(besoin)


@transaction.atomic
def modifier_vacation(
    vacation: Vacation,
    *,
    acteur: Any,
    debut: datetime,
    fin: datetime,
    type_vacation: str | None = None,
    forcer: bool = False,
    motif: str = "",
) -> Vacation:
    """Nouveaux horaires : mêmes contrôles qu'une affectation (PER-05) ; la modification par le planificateur vaut
    revue d'une vacation « à revoir » (D-051)."""
    vacation = Vacation.objects.select_for_update().get(pk=vacation.pk)
    _controler(acteur, "planifier_personnel", vacation)
    if vacation.statut == "annulee":
        raise ErreurMetier("Cette vacation est annulée.", code="vacation_annulee")
    if fin <= debut:
        raise ErreurValidation("La fin doit suivre le début.", code="horaires_invalides")
    avant = {"debut": vacation.debut.isoformat(), "fin": vacation.fin.isoformat(), "type": vacation.type}
    if type_vacation:
        vacation.type = type_vacation
    forcee = False
    if vacation.agent is not None:
        violations, forcee = _controler_affectation(
            vacation, vacation.agent, debut, fin, acteur=acteur, forcer=forcer, motif=motif
        )
        vacation.violations = [v.en_dict() for v in violations]
        vacation.forcee, vacation.motif_forcage = forcee, motif.strip()[:300] if forcee else ""
    vacation.debut, vacation.fin = debut, fin
    if vacation.statut == "a_revoir":
        vacation.statut = "planifiee" if vacation.agent_id else "a_pourvoir"
        vacation.signalement = ""
    try:
        with transaction.atomic():
            vacation.save()
    except IntegrityError as erreur:
        raise ErreurMetier("L'agent a déjà une vacation sur cette période (RG-10).", code="chevauchement_vacation") from erreur
    _recouvrir(vacation)
    journaliser(
        "modifier_vacation",
        vacation,
        avant=avant,
        apres={"debut": debut.isoformat(), "fin": fin.isoformat(), "type": vacation.type, "forcee": forcee},
        acteur=acteur,
    )
    return vacation


@transaction.atomic
def annuler_vacation(vacation: Vacation, *, acteur: Any, motif: str) -> Vacation:
    vacation = Vacation.objects.select_for_update().get(pk=vacation.pk)
    _controler(acteur, "planifier_personnel", vacation)
    vacation.statut, vacation.signalement = "annulee", motif[:300]
    vacation.save(update_fields=["statut", "signalement"])
    for besoin in vacation.besoins.all():
        mettre_a_jour_couverture(besoin)
    journaliser("annuler_vacation", vacation, apres={"motif": motif}, acteur=acteur)
    if vacation.agent and vacation.agent.courriel:
        notifier(
            "vacation_a_revoir",
            {
                "agent": str(vacation.agent),
                "site": vacation.site.nom,
                "debut": _texte(vacation.debut),
                "fin": _texte(vacation.fin),
                "motif": f"Vacation annulée : {motif}",
            },
            courriels=[vacation.agent.courriel],
            objet=vacation,
        )
    return vacation


# --- Absences et remplacements (PER-06) ---------------------------------------------------------------------


@transaction.atomic
def saisir_absence(
    agent: Agent, *, acteur: Any, debut: datetime, fin: datetime, nature: str, commentaire: str = ""
) -> tuple[Absence, list[Vacation]]:
    """L'absence libère les vacations de l'agent sur la période : elles deviennent « à pourvoir ». Une vacation déjà
    pointée reste à l'agent (heures réalisées) ; une vacation d'un site hors du périmètre du planificateur est mise
    « à revoir » pour le planificateur de ce site, sans être libérée par un tiers."""
    _controler(acteur, "planifier_personnel", agent)
    if fin <= debut:
        raise ErreurValidation("La fin de l'absence doit suivre son début.", code="dates_invalides")
    absence = Absence.objects.create(
        agent=agent,
        debut=debut,
        fin=fin,
        nature=nature,
        commentaire=commentaire[:250],
        cree_par=acteur if isinstance(acteur, Utilisateur) else None,
    )
    liberees, a_revoir, pointees = [], [], []
    motif = f"Absence de {agent} ({absence.get_nature_display().lower()}) : remplaçant à désigner"
    for vacation in Vacation.objects.select_for_update().filter(
        agent=agent, statut__in=STATUTS_ACTIFS_VACATION, debut__lt=fin, fin__gt=debut
    ):
        if vacation.arrivee_reelle:
            pointees.append(vacation.pk)
            continue
        if isinstance(acteur, Utilisateur) and not peut(acteur, "planifier_personnel", vacation):
            _mettre_a_revoir([vacation], motif)
            a_revoir.append(vacation.pk)
            continue
        vacation.agent, vacation.statut = None, "a_pourvoir"
        vacation.signalement = motif
        vacation.save()
        for besoin in vacation.besoins.all():
            mettre_a_jour_couverture(besoin)
        liberees.append(vacation)
    journaliser(
        "saisir_absence",
        absence,
        apres={"vacations_liberees": [v.pk for v in liberees], "a_revoir": a_revoir, "deja_pointees": pointees},
        acteur=acteur,
    )
    return absence, liberees


# --- Trames (PER-03) ---------------------------------------------------------------------------------------


def _motif_refus_trame(vacation: Vacation, agent: Agent) -> str:
    """Raison pour laquelle la trame ne peut pas affecter l'agent à cette date (vide si l'affectation est conforme)."""
    if not agent.actif or not agent.sites.filter(pk=vacation.site_id).exists():
        return f"{agent} n'est plus affectable à ce site"
    manquantes = _habilitations_manquantes_sur(agent, vacation.debut, vacation.fin)
    if manquantes:
        return f"{agent} sans habilitation valide ({', '.join(manquantes)})"
    if _absent(agent, vacation.debut, vacation.fin):
        return f"{agent} absent"
    if vacation.type != "astreinte":
        bloquantes = [v for v in violations_pour(agent, vacation.debut, vacation.fin, vacation.pk) if v.gravite == "bloquant"]
        if bloquantes:
            return f"{agent} hors règles de temps de travail ({bloquantes[0].message})"
    return ""


@transaction.atomic
def appliquer_trame(trame: Trame, *, acteur: Any, du: date | None = None, au: date | None = None) -> dict[str, Any]:
    """Génère les vacations de la semaine type sur la saison, à partir d'aujourd'hui, hors jours fériés (D-051).
    L'agent de la trame n'est affecté que si l'affectation est conforme (habilitations, absences, règles) ; sinon
    la vacation est créée « à pourvoir » et le motif est rapporté."""
    from apps.referentiel.calendrier import est_ferie

    _controler(acteur, "planifier_personnel", trame)
    trame = Trame.objects.select_related("saison", "site").get(pk=trame.pk)
    debut = max(du or trame.saison.debut, trame.saison.debut, timezone.localdate())
    fin = min(au or trame.saison.fin, trame.saison.fin)
    lignes = list(trame.lignes.select_related("agent"))
    creees, conflits = 0, []
    jour = debut
    while jour <= fin:
        if not est_ferie(jour):
            for ligne in (lg for lg in lignes if lg.jour == jour.weekday()):
                d = datetime.combine(jour, ligne.heure_debut, tzinfo=PARIS)
                f = datetime.combine(
                    jour + timedelta(days=1 if ligne.heure_fin <= ligne.heure_debut else 0), ligne.heure_fin, tzinfo=PARIS
                )
                if Vacation.objects.filter(trame=trame, debut=d, fin=f).exists():
                    continue
                vacation = Vacation.objects.create(
                    site=trame.site, debut=d, fin=f, type=ligne.type, trame=trame, statut="a_pourvoir"
                )
                if ligne.agent is not None:
                    refus = _motif_refus_trame(vacation, ligne.agent)
                    if not refus:
                        try:
                            with transaction.atomic():
                                Vacation.objects.filter(pk=vacation.pk).update(agent=ligne.agent, statut="planifiee")
                        except IntegrityError:
                            refus = f"{ligne.agent} déjà affecté"
                    if refus:
                        conflits.append(f"{jour:%d/%m/%Y} {ligne.heure_debut:%H:%M} : {refus}")
                        Vacation.objects.filter(pk=vacation.pk).update(signalement=f"Trame : {refus}"[:300])
                vacation.refresh_from_db()
                _recouvrir(vacation)
                creees += 1
        jour += timedelta(days=1)
    trame.appliquee_le = timezone.now()
    trame.save(update_fields=["appliquee_le"])
    journaliser("appliquer_trame", trame, apres={"creees": creees, "conflits": len(conflits)}, acteur=acteur)
    return {"creees": creees, "conflits": conflits}


# --- Compteurs (PER-07) -----------------------------------------------------------------------------------


def _intersection(a: tuple[datetime, datetime], b: tuple[datetime, datetime]) -> float:
    """Minutes communes, calculées en UTC (deux heures de Paris se soustraient sans tenir compte du changement d'heure)."""
    debut, fin = max(a[0], b[0]).astimezone(UTC), min(a[1], b[1]).astimezone(UTC)
    return max(0.0, (fin - debut).total_seconds() / 60)


def _minutes_nuit(debut: datetime, fin: datetime) -> float:
    nuit = parametre("personnel.nuit")
    h_debut, h_fin = (time.fromisoformat(nuit["debut"]), time.fromisoformat(nuit["fin"]))
    total = 0.0
    jour = timezone.localtime(debut, PARIS).date() - timedelta(days=1)
    while datetime.combine(jour, time.min, tzinfo=PARIS) < fin:
        fenetre_debut = datetime.combine(jour, h_debut, tzinfo=PARIS)
        fenetre_fin = datetime.combine(jour + timedelta(days=1 if h_fin <= h_debut else 0), h_fin, tzinfo=PARIS)
        total += _intersection((debut, fin), (fenetre_debut, fenetre_fin))
        jour += timedelta(days=1)
    return total


def _minutes_dimanche_ferie(debut: datetime, fin: datetime) -> float:
    from apps.referentiel.calendrier import est_ferie

    total = 0.0
    jour = timezone.localtime(debut, PARIS).date()
    while datetime.combine(jour, time.min, tzinfo=PARIS) < fin:
        if jour.weekday() == 6 or est_ferie(jour):
            total += _intersection((debut, fin), _bornes_jour(jour))
        jour += timedelta(days=1)
    return total


def _semaines_rattachees(du: date, au: date) -> list[date]:
    """Lundis des semaines dont le dimanche tombe dans la période : chaque semaine relève d'une seule période (D-051)."""
    lundi = du - timedelta(days=du.weekday())
    semaines = []
    while lundi <= au:
        if du <= lundi + timedelta(days=6) <= au:
            semaines.append(lundi)
        lundi += timedelta(days=7)
    return semaines


def compteurs(agents: Iterable[Agent], du: date, au: date) -> list[dict[str, Any]]:
    """PER-07 (minutes), sur la seule partie des vacations comprise dans la période :
    - planifiées : vacations de travail (hors astreintes) planifiées ou à revoir ;
    - réalisées : temps pointé, quel que soit le statut de la vacation (une vacation annulée après pointage compte) ;
    - supplémentaires : vacations de ce type, plus le dépassement de la durée hebdomadaire de référence ;
    - nuit, dimanches et fériés : sur les vacations de travail ; astreintes à part."""
    periode = (_bornes_jour(du)[0], _bornes_jour(au)[1])
    semaines = _semaines_rattachees(du, au)
    resultat = []
    for agent in agents:
        ligne: dict[str, Any] = {
            "agent": agent,
            "planifiees": 0,
            "realisees": 0,
            "supplementaires": 0,
            "nuit": 0,
            "dimanches_feries": 0,
            "astreintes": 0,
        }
        etendue = (
            min([periode[0], *(datetime.combine(s, time.min, tzinfo=PARIS) for s in semaines)]),
            max([periode[1], *(datetime.combine(s + timedelta(days=7), time.min, tzinfo=PARIS) for s in semaines)]),
        )
        vacations = list(Vacation.objects.filter(agent=agent, debut__lt=etendue[1], fin__gt=etendue[0]))
        for v in vacations:
            plage = (v.debut, v.fin)
            if v.arrivee_reelle and v.depart_reel and v.depart_reel > v.arrivee_reelle:
                ligne["realisees"] += _intersection((v.arrivee_reelle, v.depart_reel), periode)
            if v.statut not in ("planifiee", "a_revoir"):
                continue
            dans_periode = _intersection(plage, periode)
            if v.type == "astreinte":
                ligne["astreintes"] += dans_periode
                continue
            ligne["planifiees"] += dans_periode
            if v.type == "supplementaire":
                ligne["supplementaires"] += dans_periode
            if dans_periode:
                debut_p, fin_p = max(v.debut, periode[0]), min(v.fin, periode[1])
                ligne["nuit"] += _minutes_nuit(debut_p, fin_p)
                ligne["dimanches_feries"] += _minutes_dimanche_ferie(debut_p, fin_p)
        for lundi in semaines:
            semaine = (
                datetime.combine(lundi, time.min, tzinfo=PARIS),
                datetime.combine(lundi + timedelta(days=7), time.min, tzinfo=PARIS),
            )
            normales = sum(
                _intersection((v.debut, v.fin), semaine)
                for v in vacations
                if v.statut in ("planifiee", "a_revoir") and v.type == "normale"
            )
            ligne["supplementaires"] += max(0.0, normales - agent.duree_hebdo_minutes)
        for cle in ("planifiees", "realisees", "supplementaires", "nuit", "dimanches_feries", "astreintes"):
            ligne[cle] = round(ligne[cle])
        resultat.append(ligne)
    return resultat


def export_paie(lignes: list[dict[str, Any]], du: date, au: date) -> bytes:
    """Export CSV pour la paie (heures décimales, séparateur point-virgule) — format à confirmer avec la DRH."""
    sortie = io.StringIO()
    ecrivain = csv.writer(sortie, delimiter=";")
    ecrivain.writerow(
        [
            "Matricule",
            "Nom",
            "Prénom",
            "Du",
            "Au",
            "Planifiées",
            "Réalisées",
            "Supplémentaires",
            "Nuit",
            "Dimanches et fériés",
            "Astreintes",
        ]
    )
    for ligne in lignes:
        agent = ligne["agent"]
        ecrivain.writerow(
            [
                cellule_sure(agent.matricule),
                cellule_sure(agent.nom),
                cellule_sure(agent.prenom),
                f"{du:%d/%m/%Y}",
                f"{au:%d/%m/%Y}",
                *(
                    f"{ligne[c] / 60:.2f}".replace(".", ",")
                    for c in ("planifiees", "realisees", "supplementaires", "nuit", "dimanches_feries", "astreintes")
                ),
            ]
        )
    return ("\ufeff" + sortie.getvalue()).encode("utf-8")


# --- iCal (PER-08) -----------------------------------------------------------------------------------------


@transaction.atomic
def emettre_jeton_ical(agent: Agent, *, acteur: Any) -> str:
    """Un seul abonnement actif par agent : le précédent est révoqué ; le jeton n'est montré qu'une fois."""
    _controler(acteur, "planifier_personnel", agent)
    JetonIcal.objects.filter(agent=agent, revoque_le__isnull=True).update(revoque_le=timezone.now())
    valeur = secrets.token_urlsafe(32)
    JetonIcal.objects.create(agent=agent, empreinte=empreinte_hmac(valeur))
    journaliser("emettre_jeton_ical", agent, acteur=acteur)
    return valeur


@transaction.atomic
def revoquer_jetons_ical(agent: Agent, *, acteur: Any) -> int:
    _controler(acteur, "planifier_personnel", agent)
    nombre = JetonIcal.objects.filter(agent=agent, revoque_le__isnull=True).update(revoque_le=timezone.now())
    journaliser("revoquer_jeton_ical", agent, apres={"revoques": nombre}, acteur=acteur)
    return nombre


def flux_ical(jeton: str) -> bytes:
    entree = (
        JetonIcal.objects.select_related("agent")
        .filter(empreinte=empreinte_hmac(jeton or ""), revoque_le__isnull=True, agent__actif=True)
        .first()
    )
    if entree is None:
        raise ErreurMetier("Abonnement inconnu ou révoqué.", code="jeton_invalide")
    JetonIcal.objects.filter(pk=entree.pk).update(dernier_acces=timezone.now())
    maintenant = timezone.now()
    vacations = Vacation.objects.filter(
        agent=entree.agent, debut__gte=maintenant - timedelta(days=30), debut__lte=maintenant + timedelta(days=90)
    ).select_related("site")
    return ical.calendrier(
        f"Planning — {entree.agent}",
        [
            ical.Evenement(
                uid=f"vacation-{v.pk}@equipements.chatillon",
                debut=v.debut,
                fin=v.fin,
                resume=f"{v.get_type_display()} — {v.site.nom}",
                lieu=v.site.adresse or v.site.nom,
                annule=v.statut == "annulee",
            )
            for v in vacations
        ],
    )


# --- Planning imprimé (IMP-02) -----------------------------------------------------------------------------

JOURS = ["lundi", "mardi", "mercredi", "jeudi", "vendredi", "samedi", "dimanche"]


def planning_pdf(
    *,
    acteur: Any,
    du: date,
    au: date,
    agent: Agent | None = None,
    site: Site | None = None,
    format_papier: str = "A4",
    mise_en_page: str = "calendrier",
) -> bytes:
    """Planning des vacations d'un agent ou d'un site, en calendrier (une grille par semaine) ou en liste groupée par
    jour ; limité aux sites du périmètre du lecteur."""
    from django.conf import settings

    from apps.documents import impression
    from apps.habilitations.services import sites_autorises

    if (agent is None) == (site is None):
        raise ErreurValidation("Choisissez un agent ou un site.", code="cible_requise")
    if au < du or (au - du).days > 62:
        raise ErreurValidation("Période de 2 mois au plus.", code="periode_invalide")
    impression.verifier_mise_en_page(mise_en_page)
    _controler(acteur, "lire_personnel", agent or site)
    debut, _ = _bornes_jour(du)
    _, fin = _bornes_jour(au)
    vacations = Vacation.objects.filter(debut__lt=fin, fin__gt=debut).exclude(statut="annulee").select_related("site", "agent")
    if agent is not None:
        vacations = vacations.filter(agent=agent)
        if isinstance(acteur, Utilisateur):
            permis = sites_autorises(acteur, "lire_personnel")
            if permis is not None:
                vacations = vacations.filter(site__in=permis)
    else:
        vacations = vacations.filter(site=site)
    par_jour: dict[date, list[list[str]]] = {}
    blocs = []
    for v in vacations.order_by("debut"):
        debut, fin = timezone.localtime(v.debut, PARIS), timezone.localtime(v.fin, PARIS)
        ligne = [
            f"{debut:%H:%M} – {fin:%H:%M}",
            v.site.nom if agent is not None else (str(v.agent) if v.agent else "NON COUVERTE"),
            v.get_type_display(),
            f"{v.duree_minutes // 60} h {v.duree_minutes % 60:02d}",
        ]
        par_jour.setdefault(debut.date(), []).append(ligne)
        blocs.append((debut, fin, ligne[:3], v.agent_id is None))
    groupes = [(f"{JOURS[j.weekday()].capitalize()} {j:%d/%m/%Y}", lignes) for j, lignes in sorted(par_jour.items())]
    cible = f"{agent.prenom} {agent.nom} (matricule {agent.matricule})" if agent is not None else site.nom  # type: ignore[union-attr]
    edition = impression.Edition(
        titre=f"Planning des vacations — {cible}",
        sous_titre=f"Du {du:%d/%m/%Y} au {au:%d/%m/%Y}",
        entetes=["Horaires", "Site" if agent is not None else "Agent", "Type", "Durée"],
        lignes=[],
        groupes=groupes,
        lien=f"{settings.BACKOFFICE_URL.rstrip('/')}/personnel/vacations",
        format_papier=format_papier,
        paysage=False,
        mention_vide="Aucune vacation sur la période.",
        grilles=impression.grilles_datees(du, au, blocs) if mise_en_page == "calendrier" else [],
    )
    journaliser(
        "imprimer_planning_personnel",
        agent or site,
        apres={"du": str(du), "au": str(au)},
        acteur=acteur if isinstance(acteur, Utilisateur) else None,
    )
    return impression.imprimer(edition)


# --- Incidents (PER-09) ------------------------------------------------------------------------------------


@transaction.atomic
def signaler_incident(
    *,
    acteur: Any,
    source: str,
    site: Site,
    nature: str,
    gravite: str,
    description: str,
    constate_le: datetime,
    occurrence: Occurrence | None = None,
    photos: list[Any] | None = None,
    agent: Agent | None = None,
) -> Incident:
    if source == "backoffice":
        _controler(acteur, "planifier_personnel", site)
    if occurrence is not None and occurrence.espace.batiment.site_id != site.pk:
        raise ErreurValidation("Cette séance n'a pas lieu sur ce site.", code="seance_autre_site")
    if len(description.strip()) < 5:
        raise ErreurValidation("Décrivez l'incident.", code="description_requise")
    espace = occurrence.espace if occurrence else None
    usager = occurrence.reservation.dossier.usager if occurrence else None
    incident = Incident.objects.create(
        site=site,
        espace=espace,
        occurrence=occurrence,
        usager=usager,
        nature=nature,
        gravite=gravite,
        description=description.strip(),
        constate_le=constate_le,
        signale_par=agent,
        source=source,
    )
    if photos:
        incident.photos.set(photos)
    journaliser("signaler_incident", incident, apres={"nature": nature, "gravite": gravite, "source": source}, acteur=acteur)
    notifier(
        "incident_signale",
        {
            "site": site.nom,
            "nature": incident.get_nature_display(),
            "gravite": incident.get_gravite_display(),
            "description": incident.description[:500],
            "seance": f"{espace.nom}, {_texte(occurrence.debut)}" if occurrence and espace else "",
            "usager_nom": usager.nom if usager else "",
            "lien": f"{settings.BACKOFFICE_URL}/personnel/incidents",
        },
        courriels=[str(parametre("portail.service_courriel"))],
        objet=incident,
    )
    return incident


def vacations_lisibles(qs: QuerySet[Vacation]) -> QuerySet[Vacation]:
    return qs.select_related("site", "agent").prefetch_related("besoins")
