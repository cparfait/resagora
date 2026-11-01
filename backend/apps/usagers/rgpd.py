"""Protection des données des usagers (USR-06, RGPD) : export, anonymisation, durées de conservation.

- Export : toutes les données d'un contact et des structures qu'il représente, au format JSON.
- Anonymisation : les personnes physiques (contacts, particuliers) perdent nom, coordonnées,
  messages et pièces justificatives ; les dossiers, réservations et pièces comptables restent pour les
  statistiques, la valorisation et la comptabilité publique, rattachés à un libellé neutre. Le journal
  d'audit, immuable, est purgé selon sa propre durée (SEC-08).
- Durées : anonymisation après `rgpd.conservation_mois_inactivite` mois sans activité, et pas avant
  `rgpd.conservation_mois_dossiers_clos` mois après la fin du dernier dossier ; suppression des pièces
  expirées depuis `rgpd.conservation_mois_pieces_expirees` mois.
- Archives (ADR 0006) : documents signés, factures et avoirs sont des archives publiques, conservés
  intacts pendant leur durée d'utilité administrative (`rgpd.conservation_annees_documents`, par nature) ;
  à son terme, les documents d'un usager anonymisé perdent leur contexte de fusion et leurs fichiers.
"""

from __future__ import annotations

import logging
from datetime import timedelta
from pathlib import Path
from typing import Any

from django.conf import settings
from django.db import transaction
from django.utils import timezone

from apps.audit.services import journaliser
from apps.habilitations.services import exiger
from apps.noyau.exceptions import ErreurMetier
from apps.noyau.parametres import parametre

from .models import Contact, PieceJustificative, Usager

journal = logging.getLogger(__name__)
STATUTS_EN_COURS = ["demande", "en_instruction", "option", "validee", "confirmee"]


def _date(valeur: Any) -> str | None:
    return valeur.isoformat() if valeur else None


def exporter_contact(contact: Contact) -> dict[str, Any]:
    """Article 15 et 20 du RGPD : données du contact, de son compte et des structures qu'il représente."""
    from apps.communication.models import Message, Notification, PreferenceNotification
    from apps.documents.models import Signataire

    compte = getattr(contact, "compte", None)
    preferences = PreferenceNotification.objects.filter(contact=contact).first()
    structures = []
    for rattachement in contact.rattachements.select_related("usager").exclude(usager__statut="anonymise"):
        usager = rattachement.usager
        structures.append(
            {
                "nom": usager.nom,
                "type": usager.get_type_display(),
                "role": rattachement.get_role_display(),
                "adresse": " ".join(filter(None, [usager.adresse, usager.code_postal, usager.commune])),
                "telephone": usager.telephone,
                "courriel": usager.courriel,
                "siret": usager.siret,
                "rna": usager.rna,
                "dossiers": [
                    {
                        "numero": d.numero,
                        "objet": d.objet,
                        "statut": d.statut,
                        "depose_le": _date(d.depose_le),
                        "reservations": [f"{r.espace.nom} : {r.description}" for r in d.reservations.select_related("espace")],
                    }
                    for d in usager.dossiers.prefetch_related("reservations").order_by("-cree_le")
                ],
                "documents": [
                    {"numero": d.numero, "titre": d.titre, "statut": d.get_statut_display(), "cree_le": _date(d.cree_le)}
                    for d in usager.documents.filter(visible_portail=True).exclude(statut="annule").order_by("-cree_le")
                ],
                "messages_de_la_ville": [
                    {"dossier": m.dossier.numero, "le": _date(m.cree_le), "texte": m.corps}
                    for m in Message.objects.filter(dossier__usager=usager, auteur_agent__isnull=False).select_related("dossier")
                ],
                "pieces": [
                    {
                        "type": p.type_piece.libelle,
                        "statut": p.get_statut_display(),
                        "valide_jusqu_au": _date(p.valide_jusqu_au),
                        "deposee_le": _date(p.depose_le),
                    }
                    for p in usager.pieces.select_related("type_piece")
                ],
            }
        )
    return {
        "export_le": timezone.now().isoformat(),
        "responsable_du_traitement": "Ville de Châtillon — service des équipements sportifs et associatifs",
        "contact": {
            "civilite": contact.civilite,
            "prenom": contact.prenom,
            "nom": contact.nom,
            "courriel": contact.courriel,
            "telephone": contact.telephone,
            "cree_le": _date(contact.cree_le),
        },
        "abonnements_agenda": [
            {
                "structure": a.usager.nom,
                "cree_le": _date(a.cree_le),
                "expire_le": _date(a.expire_le),
                "revoque_le": _date(a.revoque_le),
                "dernier_acces": _date(a.dernier_acces),
            }
            for a in contact.abonnements_agenda.select_related("usager").exclude(usager__statut="anonymise")
        ],
        "compte": {
            "identifiant": compte.identifiant,
            "statut": compte.get_statut_display(),
            "cree_le": _date(compte.cree_le),
            "derniere_connexion": _date(compte.derniere_connexion),
            "double_authentification": compte.totp_actif,
        }
        if compte is not None
        else None,
        "preferences": {
            "sms": preferences.sms,
            "telephone_sms": preferences.telephone_sms,
            "rappels": preferences.rappels,
            "informations": preferences.informations,
        }
        if preferences is not None
        else None,
        "structures": structures,
        "messages": [
            {"dossier": m.dossier.numero, "le": _date(m.cree_le), "texte": m.corps}
            for m in Message.objects.filter(auteur_contact=contact).select_related("dossier")
        ],
        "signatures": [
            {
                "document": s.circuit.document.numero,
                "role": s.get_role_display(),
                "statut": s.get_statut_display(),
                "signe_le": _date(s.signe_le),
            }
            for s in Signataire.objects.filter(contact=contact).select_related("circuit__document")
        ],
        "notifications": [
            {"le": _date(n.cree_le), "sujet": n.sujet, "canal": n.get_canal_display(), "statut": n.get_statut_display()}
            for n in Notification.objects.filter(contact=contact).order_by("-cree_le")[:1000]
        ],
    }


def exporter_usager(usager: Usager) -> dict[str, Any]:
    """Export pour une demande d'accès adressée à la Ville : la structure et chacun de ses contacts."""
    contacts = [exporter_contact(r.contact) for r in usager.rattachements.select_related("contact")]
    return {
        "export_le": timezone.now().isoformat(),
        "usager": {"nom": usager.nom, "type": usager.get_type_display(), "statut": usager.get_statut_display()},
        "contacts": contacts,
    }


def _supprimer_piece(piece: PieceJustificative) -> None:
    fichier = piece.fichier
    piece.delete()
    if not PieceJustificative.objects.filter(fichier=fichier).exists():
        chemin = Path(settings.MEDIA_ROOT) / fichier.chemin
        chemin.unlink(missing_ok=True)
        fichier.delete()


def _anonymiser_contact(contact: Contact) -> None:
    from apps.communication.models import Message, Notification, PreferenceNotification
    from apps.comptes.models import CompteUsager
    from apps.comptes.services import fermer_sessions
    from apps.documents.models import Signataire

    contact.civilite, contact.prenom, contact.nom = "", "—", f"Contact anonymisé {contact.pk}"
    contact.courriel, contact.telephone = f"anonyme-{contact.pk}@invalide.test", ""
    contact.anonymise_le = timezone.now()
    contact.save()
    compte = CompteUsager.objects.filter(contact=contact).first()
    if compte is not None:
        fermer_sessions(compte)
        compte.identifiant = f"anonyme-{contact.pk}@invalide.test"
        compte.statut, compte.totp_actif, compte.totp_secret_chiffre, compte.totp_en_attente_chiffre = "ferme", False, "", ""
        compte.mot_de_passe = "!"
        compte.save()
        compte.jetons_uniques.all().delete()
    PreferenceNotification.objects.filter(contact=contact).delete()
    Message.objects.filter(auteur_contact=contact).update(corps="[message effacé : données personnelles anonymisées]")
    Notification.objects.filter(contact=contact).update(
        destinataire=f"anonyme-{contact.pk}@invalide.test", sujet="[sujet effacé]", corps="[contenu effacé]", corps_secret=""
    )
    Signataire.objects.filter(contact=contact).update(
        nom=f"Contact anonymisé {contact.pk}", courriel=f"anonyme-{contact.pk}@invalide.test", lien_chiffre=""
    )


def _neutraliser_notifications_du_service(usager: Usager) -> None:
    from django.db.models import Q

    from apps.communication.models import Message, Notification
    from apps.comptes.models import CompteUsager
    from apps.reservations.models import Dossier, Occurrence, Reservation

    objets = {
        "reservations.dossier": Dossier.objects.filter(usager=usager),
        "reservations.reservation": Reservation.objects.filter(dossier__usager=usager),
        "reservations.occurrence": Occurrence.objects.filter(reservation__dossier__usager=usager),
        "communication.message": Message.objects.filter(dossier__usager=usager),
        "comptes.compteusager": CompteUsager.objects.filter(contact__rattachements__usager=usager),
    }
    filtre = Q()
    for libelle, qs in objets.items():
        filtre |= Q(objet_type=libelle, objet_id__in=[str(i) for i in qs.values_list("pk", flat=True)])
    Notification.objects.filter(filtre).update(sujet="[sujet effacé]", corps="[contenu effacé]", corps_secret="")


@transaction.atomic
def anonymiser_usager(usager: Usager, *, acteur: Any, motif: str) -> Usager:
    """Anonymise un usager et les contacts qui ne représentent que lui (droit à l'effacement, durée échue)."""
    from apps.reservations.models import Reservation

    if acteur != "système":
        exiger(acteur, "anonymiser_usager")
    usager = Usager.objects.select_for_update().get(pk=usager.pk)
    if usager.statut == "anonymise":
        return usager
    if Reservation.objects.filter(
        dossier__usager=usager, statut__in=STATUTS_EN_COURS, date_fin__gte=timezone.localdate()
    ).exists():
        raise ErreurMetier(
            "Cet usager a des réservations en cours : annulez-les ou attendez leur terme avant l'anonymisation.",
            code="reservations_en_cours",
        )
    for piece in list(usager.pieces.select_related("fichier")):
        _supprimer_piece(piece)
    from .agenda import revoquer_abonnements

    revoquer_abonnements(usager=usager, acteur=acteur, motif="structure anonymisée")
    for rattachement in usager.rattachements.select_related("contact"):
        contact = rattachement.contact
        if not contact.rattachements.exclude(usager=usager).exclude(usager__statut="anonymise").exists():
            _anonymiser_contact(contact)
    personne = usager.type == "particulier"
    if personne:
        from apps.communication.models import Message, Notification

        usager.nom = f"Particulier anonymisé {usager.pk}"
        usager.adresse = ""
        Message.objects.filter(dossier__usager=usager).update(corps="[message effacé : données personnelles anonymisées]")
        Notification.objects.filter(usager=usager).update(
            destinataire=f"anonyme-usager-{usager.pk}@invalide.test",
            sujet="[sujet effacé]",
            corps="[contenu effacé]",
            corps_secret="",
        )
        # Messages adressés au service à propos de cet usager (nouveau message, compte à valider, annulation) :
        # ils citent le nom et des extraits ; on les retrouve par l'objet auquel ils se rapportent.
        _neutraliser_notifications_du_service(usager)
        from apps.reservations.models import Dossier

        Dossier.objects.filter(usager=usager).update(objet="Réservation d'un particulier", observations="")
    usager.telephone, usager.courriel, usager.observations = "", "", ""
    from apps.paiements.services import anonymiser_usager as anonymiser_paiements

    anonymiser_paiements(usager)  # adresse transmise à PayFiP (lot 7) ; montants et références restent (RG-13)
    usager.statut, usager.anonymise_le = "anonymise", timezone.now()
    usager.save()
    journaliser("anonymiser_usager", usager, apres={"motif": motif, "personne_physique": personne}, acteur=acteur)
    return usager


def anonymiser_inactifs(maintenant: Any = None) -> int:
    """Tâche planifiée : usagers sans activité depuis la durée paramétrée et sans dossier en cours."""
    from apps.reservations.models import Reservation

    maintenant = maintenant or timezone.now()
    limite = maintenant - timedelta(days=30 * int(parametre("rgpd.conservation_mois_inactivite")))
    fin_conservation = (maintenant - timedelta(days=30 * int(parametre("rgpd.conservation_mois_dossiers_clos")))).date()
    candidats = Usager.objects.filter(derniere_activite__lt=limite).exclude(statut="anonymise").exclude(type="service_municipal")
    nombre = 0
    for usager in candidats:
        # Le dernier dossier clos reste rattaché à ses contacts pendant `rgpd.conservation_mois_dossiers_clos` mois.
        recents = Reservation.objects.filter(dossier__usager=usager, date_fin__gte=min(limite.date(), fin_conservation))
        if recents.exists():
            continue
        try:
            anonymiser_usager(usager, acteur="système", motif="Durée de conservation échue (inactivité)")
            nombre += 1
        except ErreurMetier as erreur:
            journal.warning("Anonymisation reportée pour l'usager %s : %s", usager.pk, erreur.message)
    return nombre


def purger_pieces_expirees(maintenant: Any = None) -> int:
    maintenant = maintenant or timezone.now()
    limite = (maintenant - timedelta(days=30 * int(parametre("rgpd.conservation_mois_pieces_expirees")))).date()
    nombre = 0
    for piece in PieceJustificative.objects.filter(valide_jusqu_au__lt=limite).select_related("fichier"):
        with transaction.atomic():
            journaliser("purger_piece", piece, apres={"expiree_le": str(piece.valide_jusqu_au)}, acteur="système")
            _supprimer_piece(piece)
            nombre += 1
    return nombre


def purger_archives_echues(maintenant: Any = None) -> int:
    """ADR 0006 : au terme de la durée d'utilité administrative, les documents d'un usager anonymisé
    perdent leurs données personnelles (contexte, fichiers, signataires). Seule cette procédure lève la
    protection RG-13, par un réglage de session que le déclencheur reconnaît."""
    from django.db import connection

    from apps.documents.models import Document

    maintenant = maintenant or timezone.now()
    durees: dict[str, int] = parametre("rgpd.conservation_annees_documents")
    nombre = 0
    candidats = Document.objects.filter(usager__statut="anonymise").exclude(contexte__has_key="purge").select_related("fichier")
    for document in candidats:
        annees = int(durees.get(document.nature, durees.get("autres", 10)))
        if document.cree_le > maintenant - timedelta(days=365 * annees + annees // 4):
            continue
        with transaction.atomic():
            with connection.cursor() as curseur:
                curseur.execute("SET LOCAL equipements.purge_archives = 'oui'")
            fichiers_a_effacer = [f for f in (document.fichier, document.fichier_signe, document.preuve) if f is not None]
            Document.objects.filter(pk=document.pk).update(
                contexte={"purge": {"le": maintenant.date().isoformat(), "duree_annees": annees}}, signe_par="[anonymisé]"
            )
            with connection.cursor() as curseur:
                curseur.execute("SET LOCAL equipements.purge_archives = 'non'")
            for fichier in fichiers_a_effacer:
                (Path(settings.MEDIA_ROOT) / fichier.chemin).unlink(missing_ok=True)
            journaliser("purger_archive", document, apres={"nature": document.nature, "duree_annees": annees}, acteur="système")
            nombre += 1
    return nombre
