"""Éditions du planning (IMP-01, IMP-03) et envoi programmé (IMP-04) : planning hebdomadaire d'un espace ou d'un
site, A4 ou A3, noir et blanc, date d'édition et QR code vers la version en ligne ; feuille de salle à afficher, avec
QR code vers la page publique de l'équipement. Les éditions ne sont pas archivées (D-049)."""

from __future__ import annotations

import logging
from datetime import date, datetime, time, timedelta
from typing import Any

from django.conf import settings
from django.db import transaction
from django.utils import timezone

from apps.audit.services import journaliser
from apps.documents import impression
from apps.habilitations.models import Utilisateur
from apps.habilitations.services import exiger
from apps.noyau.exceptions import AccesRefuse, ErreurValidation
from apps.referentiel.models import Espace, Site
from apps.reservations.models import Occurrence
from apps.reservations.recurrence import PARIS

from .models import EnvoiProgramme

journal = logging.getLogger(__name__)
JOURS = ["Lundi", "Mardi", "Mercredi", "Jeudi", "Vendredi", "Samedi", "Dimanche"]
STATUTS_AFFICHES = ("validee", "confirmee", "realisee", "cloturee")


def _controler(acteur: Any, objet: Any) -> None:
    if acteur == "système":
        return
    if not isinstance(acteur, Utilisateur):
        raise AccesRefuse("Vous n'avez pas les droits pour cette action.", code="droits_insuffisants")
    exiger(acteur, "lire_reservation", objet)


def _seances(espaces: list[Espace], du: date, au: date) -> list[Occurrence]:
    """Séances des espaces et de tout ce qui les occupe : un gymnase réservé en entier occupe ses moitiés, une moitié
    réservée occupe une partie du gymnase (REF-05)."""
    debut = datetime.combine(du, time.min, tzinfo=PARIS)
    fin = datetime.combine(au + timedelta(days=1), time.min, tzinfo=PARIS)
    lies = set().union(*(e.ids_lies() for e in espaces)) if espaces else set()
    return list(
        Occurrence.objects.filter(espace_id__in=lies, statut__in=STATUTS_AFFICHES, debut__lt=fin, fin__gt=debut)
        .select_related("espace", "reservation__dossier__usager")
        .order_by("debut", "espace__nom")
    )


def nom_complet(espace: Espace) -> str:
    """« Espace — Site », sans répéter le site quand le nom de l'espace le contient déjà (données de CityResa :
    « Salle polyvalente - Espace Maison Blanche »)."""
    site = espace.batiment.site.nom
    return espace.nom if site.casefold() in espace.nom.casefold() else f"{espace.nom} — {site}"


def _cible(site: Site | None, espace: Espace | None) -> tuple[list[Espace], str, str]:
    if (site is None) == (espace is None):
        raise ErreurValidation("Choisissez un site ou un espace.", code="cible_requise")
    if espace is not None:
        return (
            [espace],
            nom_complet(espace),
            f"{settings.BACKOFFICE_URL.rstrip('/')}/reservations/planning?espace={espace.pk}",
        )
    assert site is not None
    espaces = list(Espace.objects.filter(batiment__site=site, actif=True).select_related("batiment__site"))
    return espaces, site.nom, f"{settings.BACKOFFICE_URL.rstrip('/')}/reservations/planning?site={site.pk}"


def _occupant(o: Occurrence) -> str:
    usager = o.reservation.dossier.usager
    return "Réservation privée" if usager.type == "particulier" else usager.nom


def edition_planning(
    *,
    site: Site | None = None,
    espace: Espace | None = None,
    du: date,
    au: date,
    format_papier: str = "A4",
    diffusion: bool = False,
    mise_en_page: str = "calendrier",
) -> impression.Edition:
    """Planning d'un espace ou d'un site. En diffusion (envoi programmé hors de l'application) : pas de nom de
    particulier, pas d'objet de demande, lien vers le portail public plutôt que vers le back-office."""
    if au < du or (au - du).days > 31:
        raise ErreurValidation("Période d'un mois au plus.", code="periode_invalide")
    espaces, intitule, lien = _cible(site, espace)
    if diffusion:
        portail = settings.PORTAIL_URL.rstrip("/")
        lien = f"{portail}/equipements/{espace.pk}" if espace is not None else f"{portail}/equipements"
    impression.verifier_mise_en_page(mise_en_page)
    par_jour: dict[date, list[list[str]]] = {}
    seances = []
    for o in _seances(espaces, du, au):
        local, fin = timezone.localtime(o.debut, PARIS), timezone.localtime(o.fin, PARIS)
        horaires = f"{local:%H:%M} – {fin:%H:%M}"
        occupant = _occupant(o) if diffusion else o.reservation.dossier.usager.nom
        if diffusion:
            ligne = [horaires, o.espace.nom, occupant]
        else:
            ligne = [horaires, o.espace.nom, occupant, o.reservation.dossier.objet[:80]]
        par_jour.setdefault(local.date(), []).append(ligne)
        seances.append((o, local, fin, [horaires, occupant]))
    groupes = [(f"{JOURS[j.weekday()]} {j:%d/%m/%Y}", lignes) for j, lignes in sorted(par_jour.items())]
    grilles = []
    if mise_en_page == "calendrier":
        # Une grille par espace (et par semaine) : un site entier sur une seule grille serait illisible. Le nom de
        # l'espace n'apparaît dans un bloc que s'il diffère de la grille (gymnase entier vu de l'une de ses moitiés).
        for cible in sorted(espaces, key=lambda e: e.nom):
            lies = cible.ids_lies()
            blocs = [
                (local, fin, [*lignes, *([o.espace.nom] if o.espace_id != cible.pk else [])], False)
                for o, local, fin, lignes in seances
                if o.espace_id in lies
            ]
            if blocs or espace is not None:
                grilles += impression.grilles_datees(du, au, blocs, prefixe=cible.nom if site is not None else "")
    return impression.Edition(
        titre=f"Planning — {intitule}",
        sous_titre=f"Du {du:%d/%m/%Y} au {au:%d/%m/%Y}",
        entetes=["Horaires", "Espace", "Occupant"] if diffusion else ["Horaires", "Espace", "Usager", "Objet"],
        lignes=[],
        groupes=groupes,
        lien=lien,
        format_papier=format_papier,
        paysage=format_papier == "A3",
        mention_vide="Aucune séance sur la période.",
        grilles=grilles,
    )


def imprimer_planning(
    *,
    acteur: Any,
    site: Site | None = None,
    espace: Espace | None = None,
    du: date,
    au: date,
    format_papier: str = "A4",
    mise_en_page: str = "calendrier",
) -> bytes:
    """IMP-01 : planning imprimé d'un espace ou d'un site, en calendrier (grille de la semaine) ou en liste."""
    _controler(acteur, espace or site)
    edition = edition_planning(site=site, espace=espace, du=du, au=au, format_papier=format_papier, mise_en_page=mise_en_page)
    pdf = impression.imprimer(edition)
    journaliser(
        "imprimer_planning",
        espace or site,
        apres={"du": str(du), "au": str(au), "format": format_papier, "mise_en_page": mise_en_page},
        acteur=acteur if isinstance(acteur, Utilisateur) else None,
    )
    return pdf


def feuille_de_salle(*, acteur: Any, espace: Espace, jour: date) -> bytes:
    """IMP-03 : feuille à afficher à l'entrée de la salle pour la semaine, QR code vers la page publique de l'espace
    (disponibilités en ligne), sans nom de particulier."""
    _controler(acteur, espace)
    lundi = jour - timedelta(days=jour.weekday())
    lignes, blocs = [], []
    for o in _seances([espace], lundi, lundi + timedelta(days=6)):
        local, fin = timezone.localtime(o.debut, PARIS), timezone.localtime(o.fin, PARIS)
        horaires = f"{local:%H:%M} – {fin:%H:%M}"
        lignes.append([f"{JOURS[local.weekday()]} {local:%d/%m}", horaires, o.espace.nom, _occupant(o)])
        blocs.append((local, fin, [horaires, _occupant(o), *([o.espace.nom] if o.espace_id != espace.pk else [])], False))
    edition = impression.Edition(
        titre=f"{espace.nom} — semaine du {lundi:%d/%m/%Y}",
        sous_titre=f"{espace.batiment.site.nom}. Disponibilités et demandes en ligne : flashez le code.",
        entetes=["Jour", "Horaires", "Espace", "Occupant"],
        lignes=lignes,
        lien=f"{settings.PORTAIL_URL.rstrip('/')}/equipements/{espace.pk}",
        format_papier="A4",
        paysage=False,
        mention_vide="Aucune séance cette semaine.",
        grilles=impression.grilles_datees(lundi, lundi + timedelta(days=6), blocs),
    )
    pdf = impression.imprimer(edition)
    journaliser(
        "imprimer_feuille_de_salle",
        espace,
        apres={"semaine": str(lundi)},
        acteur=acteur if isinstance(acteur, Utilisateur) else None,
    )
    return pdf


# --- IMP-04 : envoi programmé ------------------------------------------------------------------------------------


def prochain_envoi(envoi: EnvoiProgramme, apres: datetime) -> datetime:
    """Prochaine échéance hebdomadaire (jour et heure de Paris) strictement après `apres`."""
    local = timezone.localtime(apres, PARIS)
    candidat = datetime.combine(
        local.date() + timedelta(days=(envoi.jour_semaine - local.weekday()) % 7), envoi.heure, tzinfo=PARIS
    )
    if candidat <= local:
        candidat += timedelta(days=7)
    return candidat


@transaction.atomic
def domaines_autorises() -> set[str]:
    from apps.noyau.parametres import parametre

    return {str(d).lower() for d in parametre("pilotage.domaines_destinataires")}


def programmer(envoi: EnvoiProgramme, *, acteur: Any) -> EnvoiProgramme:
    _controler(acteur, envoi.espace or envoi.site)
    if not envoi.destinataires:
        raise ErreurValidation("Indiquez au moins un destinataire.", code="destinataires_requis")
    domaines = domaines_autorises()
    if any(a.rsplit("@", 1)[-1].lower() not in domaines for a in envoi.destinataires):
        raise ErreurValidation("Destinataire hors des domaines de la Ville.", code="destinataire_externe")
    envoi.prochain_envoi_le = prochain_envoi(envoi, timezone.now())
    envoi.save()
    journaliser(
        "programmer_envoi_planning",
        envoi,
        apres={"destinataires": list(envoi.destinataires)},
        acteur=acteur if isinstance(acteur, Utilisateur) else None,
    )
    return envoi


ECHECS_MAX = 5
CONSERVATION_PIECES_JOURS = 30
DEPOSE_PAR = "envoi programmé"


def _motif_suspension(envoi: EnvoiProgramme) -> str:
    """Un envoi ne part que si son responsable (dernier à l'avoir créé ou modifié) est actif et voit encore le
    planning ciblé, et si ses adresses restent dans les domaines de la Ville (B1, revue sécurité du lot 6)."""
    from apps.habilitations.services import peut

    responsable = envoi.cree_par
    if responsable is None or not responsable.is_active or not peut(responsable, "lire_reservation", envoi.espace or envoi.site):
        return "Le responsable de l'envoi n'a plus accès à ce planning : faites-le reprendre par un agent habilité."
    domaines = domaines_autorises()
    if any(a.rsplit("@", 1)[-1].lower() not in domaines for a in envoi.destinataires):
        return "Une adresse n'appartient plus aux domaines autorisés."
    return ""


def purger_pieces_jointes(maintenant: datetime) -> int:
    """m6 : les plannings envoyés ne sont pas archivés (D-049) ; leur pièce jointe est effacée du disque après
    30 jours, une fois les courriels partis."""
    from pathlib import Path

    from apps.communication.models import Notification
    from apps.noyau.models import Fichier

    limite = maintenant - timedelta(days=CONSERVATION_PIECES_JOURS)
    effaces = 0
    for fichier in Fichier.objects.filter(depose_par=DEPOSE_PAR, depose_le__lt=limite):
        if Notification.objects.filter(piece_jointe=fichier, statut__in=["en_attente", "echec"]).exists():
            continue
        chemin = Path(settings.MEDIA_ROOT) / fichier.chemin
        if chemin.exists():
            chemin.unlink()
            effaces += 1
    return effaces


def envoyer_plannings_dus(maintenant: datetime | None = None) -> int:
    """Tâche horaire : chaque envoi dû part avec le planning de la semaine suivante en pièce jointe, puis l'échéance
    suivante est calculée. Idempotent : l'échéance avance dans la même transaction que la mise en file du courriel."""
    from apps.communication.services import notifier
    from apps.noyau import fichiers

    maintenant = maintenant or timezone.now()
    envoyes = 0
    for envoi in EnvoiProgramme.objects.filter(actif=True, prochain_envoi_le__lte=maintenant).order_by("prochain_envoi_le"):
        try:
            with transaction.atomic():
                verrou = (
                    EnvoiProgramme.objects.select_for_update(of=("self",))
                    .select_related("site", "espace__batiment__site", "cree_par")
                    .get(pk=envoi.pk)
                )
                if not verrou.actif or verrou.prochain_envoi_le is None or verrou.prochain_envoi_le > maintenant:
                    continue
                motif = _motif_suspension(verrou)
                if motif:
                    verrou.actif, verrou.suspendu_motif = False, motif
                    verrou.save(update_fields=["actif", "suspendu_motif"])
                    journaliser("suspendre_envoi_planning", verrou, apres={"motif": motif}, acteur="système")
                    continue
                # m10 : la semaine se déduit de l'échéance, pas de l'heure de traitement (un envoi du dimanche
                # 23 h 30 traité à 0 h 05 envoie bien la semaine qui commence).
                echeance = timezone.localtime(verrou.prochain_envoi_le, PARIS).date()
                lundi = echeance + timedelta(days=7 - echeance.weekday())
                edition = edition_planning(
                    site=verrou.site,
                    espace=verrou.espace,
                    du=lundi,
                    au=lundi + timedelta(days=6),
                    format_papier=verrou.format_papier,
                    diffusion=True,
                )
                pdf = impression.imprimer(edition)
                piece = fichiers.enregistrer_genere(f"planning-{lundi:%Y%m%d}.pdf", pdf, "application/pdf", depose_par=DEPOSE_PAR)
                notifier(
                    "planning_hebdomadaire",
                    {"cible": edition.titre, "semaine": f"{lundi:%d/%m/%Y}"},
                    courriels=verrou.destinataires,
                    objet=verrou,
                    piece_jointe=piece,
                )
                verrou.dernier_envoi_le, verrou.echecs = maintenant, 0
                verrou.prochain_envoi_le = prochain_envoi(verrou, maintenant)
                verrou.save(update_fields=["dernier_envoi_le", "prochain_envoi_le", "echecs"])
                envoyes += 1
        except Exception as erreur:  # un envoi en échec ne bloque pas les suivants (M5)
            journal.exception("Envoi programmé %s en échec", envoi.pk)
            echecs = envoi.echecs + 1
            EnvoiProgramme.objects.filter(pk=envoi.pk).update(
                echecs=echecs,
                actif=echecs < ECHECS_MAX,
                suspendu_motif=(f"Suspendu après {echecs} échecs : {type(erreur).__name__}." if echecs >= ECHECS_MAX else ""),
            )
    purger_pieces_jointes(maintenant)
    return envoyes
