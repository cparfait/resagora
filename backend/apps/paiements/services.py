"""Paiement en ligne PayFiP (lot 7, TAR-07, POR-07), selon le guide de mise en œuvre PayFiP, le skill
`finances-ciril` et l'ADR 0008 :

1. la tentative est enregistrée avant toute redirection ; l'opération PayFiP est créée par le worker (seul conteneur
   qui sort vers la DGFiP, par le proxy de la Ville) ; le portail redirige l'usager dès qu'elle existe ;
2. le retour du navigateur n'est jamais une preuve de paiement : il ne fait que demander une relecture du résultat
   auprès de PayFiP (`recupererDetailPaiementSecurise`), au plus toutes les 30 secondes ;
3. la notification de PayFiP, filtrée par la façade (adresses) et signée par l'API dans l'adresse de notification,
   déclenche la même relecture ; le traitement est idempotent (un seul encaissement par tentative, sous verrou) ;
4. une tentative n'est jamais close sans résultat de PayFiP : remplacée par une autre ou restée sans réponse, elle
   reste relue ; un paiement qui arrive tard est encaissé ou signalé, jamais perdu ;
5. un rapprochement, chaque heure, relit les tentatives en suspens et signale au service financier tout ce qui
   demande une action (résultat incohérent ou inconnu, trop-perçu, paiement peut-être déjà encaissé).
"""

from __future__ import annotations

import hashlib
import hmac
import logging
import re
import unicodedata
from datetime import datetime, timedelta
from typing import Any
from urllib.parse import urlencode
from uuid import UUID

from django.conf import settings
from django.db import IntegrityError, transaction
from django.db.models import F, Q
from django.utils import timezone

from apps.audit.services import journaliser
from apps.finances.facturation import enregistrer_encaissement
from apps.finances.models import Encaissement, PieceComptable
from apps.finances.payfip import ClientPayFiP, DetailPaiement
from apps.noyau.exceptions import ErreurMetier, ErreurValidation
from apps.noyau.montants import euros
from apps.noyau.parametres import parametre
from apps.reservations.recurrence import PARIS

from .models import STATUTS_A_RELIRE, STATUTS_EN_COURS, TentativePaiement

journal = logging.getLogger(__name__)
journal_securite = logging.getLogger("securite")
SYSTEME = "système"
DELAI_REPRISE = timedelta(minutes=20)
DELAI_RELECTURE = timedelta(seconds=30)
DELAI_EXPIRATION = timedelta(hours=24)
DELAI_RELECTURE_EXPIREES = timedelta(days=7)
REFDET = re.compile(r"[A-Za-z0-9]{1,30}")
SIGNATURE = re.compile(r"[0-9a-f]{32}")


# --- Configuration et règles de paiement -----------------------------------------------------------------------


def actif() -> bool:
    return bool(settings.PAYFIP_ACTIF and settings.PAYFIP_NUMCLI and settings.PAYFIP_URL_SERVICE)


def _ascii(texte: str) -> str:
    return unicodedata.normalize("NFKD", texte).encode("ascii", "ignore").decode("ascii")


def references(piece: PieceComptable) -> tuple[str, str]:
    """(exercice, référence de la dette) transmis à PayFiP : numéro de titre de l'exercice de la pièce (Titres et
    Rôles) ou référence de virement de la facture, sans séparateur (Régie)."""
    annee = str(piece.exercice or (piece.emise_le.year if piece.emise_le else timezone.localdate().year))
    if settings.PAYFIP_MODE == "titres":
        return annee, piece.titre_numero
    return annee, piece.reference_virement or (piece.numero or "").replace("-", "")


def motif_non_payable(piece: PieceComptable) -> str:
    """Raison pour laquelle la facture ne se paie pas en ligne ('' si elle se paie) — POR-07, ADR 0008."""
    if not actif():
        return "Le paiement en ligne n'est pas ouvert."
    if piece.nature not in {"facture", "acompte"} or not piece.numero:
        return "Seules les factures émises se paient en ligne."
    if piece.reste_du <= 0:
        return "Cette facture est réglée."
    if piece.reste_du < settings.PAYFIP_MONTANT_MINIMUM:
        return f"Le paiement en ligne commence à {euros(settings.PAYFIP_MONTANT_MINIMUM)} : réglez cette somme par virement."
    if piece.tentatives_paiement.filter(statut="a_controler").exists():
        return "Un paiement en ligne de cette facture est en cours de vérification par le service financier."
    if settings.PAYFIP_MODE == "titres":
        if not piece.titre_numero or piece.statut not in {"titre_emis", "solde_partiel"}:
            return "Le titre de recettes n'est pas encore émis : réglez par virement ou attendez l'avis du comptable public."
    else:
        if piece.titre_numero or piece.statut not in {"a_titrer", "solde_partiel"}:
            return "Cette facture est prise en charge par le comptable public : réglez-la selon l'avis des sommes à payer."
        if piece.lots_titres.filter(annule_le__isnull=True).exists():
            return "Cette facture est transmise au comptable public : réglez-la selon l'avis des sommes à payer."
    if not REFDET.fullmatch(references(piece)[1]):
        return "Référence de facture incompatible avec le paiement en ligne : réglez par virement."
    return ""


def payable(piece: PieceComptable) -> bool:
    return motif_non_payable(piece) == ""


def signature(identifiant: str) -> str:
    """Signature de l'adresse de notification (secret « payfip_secret », sans repli sur une autre clé)."""
    if len(settings.PAYFIP_SECRET) < 24:
        raise ErreurMetier("Clé de signature PayFiP absente (secret payfip_secret).", code="payfip_non_configure")
    cle = settings.PAYFIP_SECRET.encode("utf-8")
    return hmac.new(cle, f"payfip:{identifiant}".encode(), hashlib.sha256).hexdigest()[:32]


def _url_notification(tentative: TentativePaiement) -> str:
    requete = urlencode({"ref": str(tentative.uuid), "sig": signature(str(tentative.uuid))})
    return f"{settings.PAYFIP_URL_NOTIFICATION}?{requete}"


def _url_retour(tentative: TentativePaiement) -> str:
    return f"{settings.PORTAIL_URL.rstrip('/')}/espace/paiement/{tentative.uuid}"


def _programmer(tache: str, tentative_id: int, **options: Any) -> None:
    from . import tasks

    fonction = getattr(tasks, tache)
    transaction.on_commit(lambda: fonction.delay(tentative_id, **options))


# --- 1. Initier : tentative enregistrée, opération créée par le worker --------------------------------------------


def initier(piece: PieceComptable, *, contact: Any) -> TentativePaiement:
    """POR-07 : la tentative en cours du même contact depuis moins de 20 minutes est reprise ; toute autre tentative
    en cours est « remplacée » (elle reste relue). La nouvelle porte sur le reste dû de la facture."""
    with transaction.atomic():
        piece = PieceComptable.objects.select_for_update().get(pk=piece.pk)
        motif = motif_non_payable(piece)
        if motif:
            raise ErreurMetier(motif, code="non_payable")
        for en_cours in TentativePaiement.objects.select_for_update().filter(piece=piece, statut__in=STATUTS_EN_COURS):
            meme_contact = getattr(contact, "pk", None) == en_cours.contact_id
            if meme_contact and timezone.now() - en_cours.cree_le < DELAI_REPRISE and en_cours.montant == piece.reste_du:
                return en_cours
            if en_cours.id_op:
                TentativePaiement.objects.filter(pk=en_cours.pk, statut__in=STATUTS_EN_COURS).update(statut="remplacee")
                _programmer("verifier", en_cours.pk, source="remplacement")
            else:
                # Opération jamais créée chez PayFiP : rien n'a pu être payé.
                TentativePaiement.objects.filter(pk=en_cours.pk, statut="creee", id_op__isnull=True).update(
                    statut="erreur", erreur="Remplacée avant la création de l'opération PayFiP."
                )
        exer, refdet = references(piece)
        try:
            with transaction.atomic():
                tentative = TentativePaiement.objects.create(
                    piece=piece,
                    contact=contact,
                    mode=settings.PAYFIP_MODE,
                    numcli=settings.PAYFIP_NUMCLI,
                    exer=exer,
                    refdet=refdet,
                    objet=_ascii(f"Facture {piece.numero} - Ville de Chatillon")[:100],
                    montant=piece.reste_du,
                    mel=getattr(contact, "courriel", "") or "",
                    saisie=settings.PAYFIP_SAISIE,
                )
        except IntegrityError:
            # Double clic ou deux onglets : la tentative créée par l'autre requête est reprise.
            existante = TentativePaiement.objects.filter(piece=piece, statut__in=STATUTS_EN_COURS).first()
            if existante is None:
                raise
            return existante
        journaliser(
            "initier_paiement_en_ligne",
            piece,
            apres={"tentative": str(tentative.uuid), "montant": tentative.montant},
            acteur=contact if contact is not None else SYSTEME,
        )
        _programmer("creer_operation", tentative.pk)
    return tentative


def creer_operation(tentative_id: int, client: ClientPayFiP | None = None) -> TentativePaiement | None:
    """Worker : crée l'opération chez PayFiP ; une faute de PayFiP ferme la tentative (rien n'a pu être payé)."""
    tentative = TentativePaiement.objects.filter(pk=tentative_id, statut="creee", id_op__isnull=True).first()
    if tentative is None:
        return None
    try:
        id_op = (client or ClientPayFiP()).creer(
            exer=tentative.exer,
            refdet=tentative.refdet,
            objet=tentative.objet,
            montant=tentative.montant,
            mel=tentative.mel,
            urlnotif=_url_notification(tentative),
            urlredirect=_url_retour(tentative),
        )
    except ErreurMetier as erreur:
        if erreur.code == "payfip_indisponible":
            raise  # nouvelle tentative de la tâche (Celery), puis expiration par le rapprochement
        TentativePaiement.objects.filter(pk=tentative.pk, statut="creee", id_op__isnull=True).update(
            statut="erreur", erreur=erreur.message[:300]
        )
        journal.warning("PayFiP a refusé la création de l'opération %s : %s", tentative.uuid, erreur.message)
        return TentativePaiement.objects.get(pk=tentative.pk)
    # Remplacée entre-temps, la tentative garde son opération pour être relue.
    TentativePaiement.objects.filter(pk=tentative.pk, id_op__isnull=True).update(id_op=id_op)
    TentativePaiement.objects.filter(pk=tentative.pk, statut="creee").update(statut="redirigee")
    return TentativePaiement.objects.get(pk=tentative.pk)


# --- 2 et 3. Relire le résultat chez PayFiP --------------------------------------------------------------------------


def demander_relecture(tentative: TentativePaiement, *, source: str) -> bool:
    """Retour du navigateur : programme une relecture au plus toutes les 30 secondes (réservation atomique)."""
    if tentative.statut not in STATUTS_A_RELIRE or not tentative.id_op:
        return False
    limite = timezone.now() - DELAI_RELECTURE
    reservee = (
        TentativePaiement.objects.filter(pk=tentative.pk)
        .filter(Q(verifiee_le__isnull=True) | Q(verifiee_le__lt=limite))
        .update(verifiee_le=timezone.now())
    )
    if reservee:
        _programmer("verifier", tentative.pk, source=source)
    return bool(reservee)


def _incoherence(tentative: TentativePaiement, detail: DetailPaiement) -> str:
    attendu = {
        "idOp": (detail.id_op, tentative.id_op),
        "numcli": (detail.numcli, tentative.numcli),
        "refdet": (detail.refdet, tentative.refdet),
        "exer": (detail.exer, tentative.exer),
        "montant": (str(detail.montant), str(tentative.montant)),
        "saisie": (detail.saisie or tentative.saisie, tentative.saisie),
    }
    ecarts = [cle for cle, (recu, prevu) in attendu.items() if recu != prevu]
    return f"Résultat PayFiP incohérent ({', '.join(ecarts)})" if ecarts else ""


def _a_controler(tentative: TentativePaiement, controle: str, detail: str) -> None:
    from apps.communication.services import notifier

    tentative.statut, tentative.controle, tentative.erreur = "a_controler", controle, detail[:300]
    journal_securite.warning("PayFiP : tentative %s à contrôler (%s)", tentative.uuid, detail[:200])
    notifier(
        "paiement_en_ligne_a_controler",
        {"piece": tentative.piece, "montant": euros(tentative.montant), "motif": detail[:200]},
        courriels=[str(parametre("portail.service_courriel"))],
        objet=tentative.piece,
    )


def verifier(tentative: TentativePaiement, *, source: str, client: ClientPayFiP | None = None) -> TentativePaiement:
    """Lit le résultat auprès de PayFiP et l'applique, sous verrou ; idempotent (un résultat définitif ne change plus)."""
    if tentative.statut not in STATUTS_A_RELIRE or not tentative.id_op:
        return tentative
    detail = (client or ClientPayFiP()).detail(tentative.id_op)
    with transaction.atomic():
        tentative = TentativePaiement.objects.select_for_update().select_related("piece__usager").get(pk=tentative.pk)
        maintenant = timezone.now()
        if tentative.statut not in STATUTS_A_RELIRE:
            return tentative
        champs = ["verifiee_le", "statut", "erreur", "controle"]
        tentative.verifiee_le = maintenant
        if detail is None:
            if tentative.statut != "expiree" and maintenant - tentative.cree_le > DELAI_EXPIRATION:
                tentative.statut = "expiree"
            tentative.save(update_fields=champs)
            return tentative
        ecart = _incoherence(tentative, detail)
        tentative.resultrans, tentative.numauto = detail.resultrans[:1], detail.numauto
        tentative.paye_le = detail.horodatage() or maintenant
        champs += ["resultrans", "numauto", "paye_le"]
        if ecart:
            _a_controler(tentative, "incoherent", ecart)
        elif detail.statut is None:
            _a_controler(tentative, "resultat_inconnu", f"Résultat PayFiP inconnu (resultrans « {detail.resultrans[:5]} »)")
        elif detail.statut == "payee" and tentative.saisie == "T" and not settings.RECETTE:
            _a_controler(tentative, "saisie_test", "Paiement de test (saisie T) reçu hors recette : rien n'est encaissé.")
        else:
            tentative.statut = detail.statut
            if tentative.statut == "payee":
                _encaisser(tentative)
                champs += ["encaissement", "trop_percu"]
        tentative.save(update_fields=champs)
        journaliser(
            "resultat_paiement_en_ligne",
            tentative.piece,
            apres={"tentative": str(tentative.uuid), "statut": tentative.statut, "source": source, "numauto": tentative.numauto},
            acteur=SYSTEME,
        )
    return tentative


def _encaisser(tentative: TentativePaiement) -> None:
    """Un seul encaissement par tentative (relation un-à-un) ; un excédent est un trop-perçu, ou un paiement
    peut-être déjà enregistré par l'import Ciril ou un pointage (même montant à 7 jours) : « à vérifier »."""
    from apps.communication.services import notifier

    piece = PieceComptable.objects.select_for_update().get(pk=tentative.piece_id)
    jour = timezone.localtime(tentative.paye_le or timezone.now(), PARIS).date()
    a_encaisser = min(tentative.montant, max(0, piece.reste_du))
    if a_encaisser > 0:
        piece = enregistrer_encaissement(
            piece,
            montant=a_encaisser,
            jour=jour,
            reference=f"PayFiP {tentative.numauto or tentative.id_op}"[:100],
            origine="payfip",
        )
        tentative.encaissement = piece.encaissements.filter(origine="payfip").order_by("-pk").first()
    tentative.trop_percu = tentative.montant - a_encaisser
    contexte = {"piece": piece, "montant": euros(tentative.montant), "numauto": tentative.numauto}
    notifier("paiement_en_ligne_recu", contexte, usager=piece.usager, objet=piece)
    if tentative.trop_percu:
        deja = Encaissement.objects.filter(
            piece=piece,
            montant=tentative.trop_percu,
            date__gte=jour - timedelta(days=7),
            date__lte=jour + timedelta(days=7),
        ).exclude(origine="payfip")
        tentative.controle = "doublon_probable" if deja.exists() else "trop_percu"
        notifier(
            "paiement_en_ligne_trop_percu",
            {
                **contexte,
                "trop_percu": euros(tentative.trop_percu),
                "verification": "Un règlement de même montant est déjà enregistré : vérifiez avant tout remboursement."
                if tentative.controle == "doublon_probable"
                else "Montant à rembourser à l'usager.",
            },
            courriels=[str(parametre("portail.service_courriel"))],
            objet=piece,
        )


def notification(reference: str, sig: str, id_op: str) -> bool:
    """Notification relayée par la façade : formats et signature contrôlés, puis relecture confiée au worker."""
    if not SIGNATURE.fullmatch(sig or "") or not re.fullmatch(r"[A-Za-z0-9_-]{8,64}", id_op or ""):
        journal_securite.warning("Notification PayFiP mal formée écartée")
        return False
    try:
        UUID(reference)
    except ValueError, TypeError:
        journal_securite.warning("Notification PayFiP mal formée écartée")
        return False
    if not hmac.compare_digest(signature(reference), sig):
        journal_securite.warning("Notification PayFiP à la signature invalide (référence %s)", reference)
        return False
    tentative = TentativePaiement.objects.filter(uuid=reference, id_op=id_op).first()
    if tentative is None:
        journal_securite.warning("Notification PayFiP sans tentative correspondante (référence %s)", reference)
        return False
    TentativePaiement.objects.filter(pk=tentative.pk).update(notifications=F("notifications") + 1)
    _programmer("verifier", tentative.pk, source="notification")
    return True


# --- Back-office : clôture après contrôle et remboursement ------------------------------------------------------


@transaction.atomic
def clore_apres_controle(tentative: TentativePaiement, *, acteur: Any, motif: str) -> TentativePaiement:
    """Une tentative « à contrôler » est close par le service financier, après vérification auprès de la DGFiP
    (un paiement réel se pointe alors comme tout règlement, TAR-13)."""
    if len(motif.strip()) < 10:
        raise ErreurValidation("Indiquez le résultat de la vérification (une phrase).", code="motif_requis")
    tentative = TentativePaiement.objects.select_for_update().get(pk=tentative.pk)
    if tentative.statut != "a_controler":
        raise ErreurMetier("Seule une tentative à contrôler se clôt ainsi.", code="statut_tentative")
    tentative.statut, tentative.motif_cloture, tentative.close_par = "erreur", motif.strip()[:300], acteur
    tentative.save(update_fields=["statut", "motif_cloture", "close_par"])
    journaliser(
        "clore_paiement_en_ligne", tentative.piece, apres={"tentative": str(tentative.uuid), "motif": motif[:200]}, acteur=acteur
    )
    return tentative


@transaction.atomic
def enregistrer_remboursement(
    tentative: TentativePaiement, *, acteur: Any, date: Any, reference: str, par: str
) -> TentativePaiement:
    from .models import RemboursementTropPercu

    tentative = TentativePaiement.objects.select_for_update().get(pk=tentative.pk)
    if not tentative.trop_percu or RemboursementTropPercu.objects.filter(tentative=tentative).exists():
        raise ErreurMetier("Pas de trop-perçu à rembourser sur ce paiement.", code="sans_trop_percu")
    if len(reference.strip()) < 3 or par not in {"ville", "comptable"}:
        raise ErreurValidation("Indiquez la référence du remboursement et qui l'a effectué.", code="reference_requise")
    RemboursementTropPercu.objects.create(
        tentative=tentative, montant=tentative.trop_percu, date=date, reference=reference.strip()[:100], par=par, agent=acteur
    )
    journaliser("rembourser_trop_percu", tentative.piece, apres={"tentative": str(tentative.uuid), "par": par}, acteur=acteur)
    return tentative


# --- 4. Rapprochement -------------------------------------------------------------------------------------------


def rapprocher(maintenant: datetime | None = None, client: ClientPayFiP | None = None) -> dict[str, int]:
    """TAR-07 : relit les tentatives en suspens (notification perdue, tentative remplacée, sans résultat depuis moins
    de 7 jours), contrôle chaque paiement accepté (encaissement + trop-perçu = montant payé) et prévient le service
    financier de ce qui demande une action depuis le précédent passage."""
    from apps.communication.services import notifier

    maintenant = maintenant or timezone.now()
    client = client or ClientPayFiP()
    bilan = {"relues": 0, "payees": 0, "expirees": 0, "injoignable": 0, "a_controler": 0, "trop_percus": 0, "ecarts": 0}
    a_relire = TentativePaiement.objects.filter(statut__in=STATUTS_A_RELIRE, id_op__isnull=False).filter(
        Q(statut__in=["creee", "redirigee"], cree_le__lt=maintenant - DELAI_REPRISE)
        | Q(statut="remplacee")
        | Q(statut="expiree", cree_le__gte=maintenant - DELAI_RELECTURE_EXPIREES)
    )
    for tentative in a_relire:
        avant = tentative.statut
        try:
            resultat = verifier(tentative, source="rapprochement", client=client)
        except ErreurMetier as erreur:
            journal.warning("Rapprochement PayFiP : %s (%s)", erreur.message, tentative.uuid)
            bilan["injoignable"] += 1
            continue
        bilan["relues"] += 1
        bilan["payees"] += resultat.statut == "payee"
        bilan["expirees"] += resultat.statut == "expiree" and avant != "expiree"
    sans_operation = TentativePaiement.objects.filter(
        statut="creee", id_op__isnull=True, cree_le__lt=maintenant - DELAI_EXPIRATION
    )
    bilan["expirees"] += sans_operation.update(statut="expiree", erreur="Opération jamais créée chez PayFiP.")
    depuis = maintenant - timedelta(hours=1, minutes=5)
    bilan["a_controler"] = TentativePaiement.objects.filter(statut="a_controler").count()
    bilan["trop_percus"] = TentativePaiement.objects.filter(trop_percu__gt=0, remboursement__isnull=True).count()
    ecarts = [
        str(t.uuid)
        for t in TentativePaiement.objects.filter(statut="payee", paye_le__gte=maintenant - timedelta(days=31)).select_related(
            "encaissement"
        )
        if (t.encaissement.montant if t.encaissement else 0) + t.trop_percu != t.montant
    ]
    bilan["ecarts"] = len(ecarts)
    nouveaux = (
        TentativePaiement.objects.filter(verifiee_le__gte=depuis).filter(Q(statut="a_controler") | Q(trop_percu__gt=0)).count()
    )
    if ecarts or nouveaux:
        notifier(
            "paiements_en_ligne_rapprochement",
            {
                "a_controler": bilan["a_controler"],
                "trop_percus": bilan["trop_percus"],
                "ecarts": ", ".join(ecarts[:10]) or "aucun",
            },
            courriels=[str(parametre("portail.service_courriel"))],
        )
    journaliser("rapprocher_paiements_en_ligne", objet_type="paiements.rapprochement", apres=bilan, acteur=SYSTEME)
    return bilan


def anonymiser_usager(usager: Any) -> int:
    """USR-06 : l'adresse transmise à PayFiP s'efface avec l'usager (les montants et références restent, RG-13)."""
    return TentativePaiement.objects.filter(piece__usager=usager).exclude(mel="").update(mel="")
