"""Génération des documents (DOC-01 à DOC-07), circuits de signature (SIG-01 à SIG-05), immuabilité (RG-13)."""

from __future__ import annotations

import io
import logging
from collections.abc import Iterable
from datetime import timedelta
from typing import Any

from django.db import transaction
from django.db.models import QuerySet
from django.utils import timezone
from docxtpl import DocxTemplate
from jinja2 import TemplateError

from apps.audit.services import journaliser
from apps.communication.services import notifier
from apps.habilitations.models import Utilisateur
from apps.habilitations.services import exiger
from apps.noyau import fichiers
from apps.noyau.chiffrement import chiffrer, dechiffrer
from apps.noyau.exceptions import AccesRefuse, ErreurMetier, ErreurValidation
from apps.noyau.numerotation import numero
from apps.noyau.parametres import parametre
from apps.usagers.models import Contact

from . import contexte as contextes
from .docuseal import ClientDocuSeal
from .gotenberg import convertir_en_pdfa
from .models import (
    NATURES_COMPTABLES,
    STATUTS_SIGNES,
    CircuitSignature,
    Document,
    LotGeneration,
    ModeleDocument,
    Signataire,
    VersionModele,
)

journal = logging.getLogger(__name__)
TYPE_DOCX = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"


def _acteur(acteur: Any) -> str:
    return str(acteur)[:200]


# --- Modèles et versions (DOC-01) -------------------------------------------------------------------


def rendre_docx(modele_docx: bytes, contexte: dict[str, Any]) -> bytes:
    """Fusion docxtpl (syntaxe Jinja) ; une erreur de modèle est rapportée lisiblement à l'administrateur."""
    try:
        gabarit = DocxTemplate(io.BytesIO(modele_docx))
        gabarit.render(contexte, autoescape=True)
    except (TemplateError, KeyError, ValueError) as erreur:
        raise ErreurValidation(f"Le modèle contient une erreur de champ de fusion : {erreur}", code="modele_invalide") from erreur
    sortie = io.BytesIO()
    gabarit.save(sortie)
    return sortie.getvalue()


@transaction.atomic
def deposer_version(modele: ModeleDocument, nom: str, contenu: bytes, *, acteur: Any, commentaire: str = "") -> VersionModele:
    """Nouvelle version d'un modèle : contrôlée (type réel, antivirus), testée par une fusion d'essai, puis activée."""
    if isinstance(acteur, Utilisateur):
        exiger(acteur, "gerer_modele", modele)
    fichier = fichiers.enregistrer(nom, contenu, types_autorises=(TYPE_DOCX,), depose_par=_acteur(acteur))
    exemple = exemple_de_contexte(modele.nature)
    rendre_docx(contenu, exemple)
    modele = ModeleDocument.objects.select_for_update().get(pk=modele.pk)
    dernier = modele.versions.order_by("-numero").values_list("numero", flat=True).first() or 0
    version = VersionModele.objects.create(
        modele=modele, numero=dernier + 1, fichier=fichier, commentaire=commentaire[:250], deposee_par=_acteur(acteur)
    )
    modele.version_active = version
    modele.save(update_fields=["version_active"])
    journaliser("deposer_version_modele", modele, apres={"version": version.numero, "sha256": fichier.sha256}, acteur=acteur)
    return version


@transaction.atomic
def activer_version(version: VersionModele, *, acteur: Any) -> ModeleDocument:
    """Retour à une version antérieure (les documents déjà générés gardent la leur)."""
    exiger(acteur, "gerer_modele", version.modele)
    modele = ModeleDocument.objects.select_for_update().get(pk=version.modele_id)
    avant = modele.version_active.numero if modele.version_active else None
    modele.version_active = version
    modele.save(update_fields=["version_active"])
    journaliser("activer_version_modele", modele, avant={"version": avant}, apres={"version": version.numero}, acteur=acteur)
    return modele


def exemple_de_contexte(nature: str) -> dict[str, Any]:
    """Contexte fictif complet servant à tester une nouvelle version avant de l'activer."""
    reservation = {
        "espace": "Gymnase exemple",
        "site": "Complexe exemple",
        "adresse": "1 rue de l'Exemple, 92320 Châtillon",
        "description": "tous les mardis de 18 h à 20 h, hors vacances scolaires et jours fériés",
        "date_debut": "1 septembre 2026",
        "date_fin": "30 juin 2027",
        "heure_debut": "18:00",
        "heure_fin": "20:00",
        "nombre_seances": 32,
        "capacite": 200,
        "gardiennage": "oui",
        "statut": "Validée",
        "seances": ["mardi 8 septembre 2026 à 18h00"],
    }
    usager = {
        "nom": "Association exemple",
        "type": "Association",
        "sigle": "AE",
        "siret": "",
        "rna": "W000000000",
        "adresse": "1 rue de l'Exemple, 92320 Châtillon",
        "telephone": "",
        "courriel": "contact@exemple.test",
        "resident": "oui",
        "representant": "Camille Exemple",
        "representant_qualite": "Président(e)",
    }
    exemple: dict[str, Any] = {
        **contextes.base(),
        "dossier": {
            "numero": "D2026-00000",
            "objet": "Exemple",
            "activite": "Basket",
            "effectif": 20,
            "type": "Créneau annuel",
            "depose_le": "",
        },
        "usager": usager,
        "reservations": [reservation],
        "conditions": ["signature de la présente convention"],
        "saison": "2026-2027",
        "avenant": {"numero_origine": "DOC2026-00000", "motif": "Exemple"},
        "attribues": ["Gymnase exemple : tous les mardis de 18 h à 20 h"],
        "refuses": [{"creneau": "Dojo : tous les jeudis", "motif": "Créneau attribué à une priorité supérieure"}],
        "fermeture": {"lieu": "Gymnase exemple", "debut": "", "fin": "", "motif": "Travaux"},
        "seances": ["Gymnase exemple, mardi 10 novembre 2026 à 18h00"],
        "seance": {"espace": "Gymnase exemple", "site": "Complexe exemple", "debut": "", "fin": ""},
        "gardien": "",
        "materiel": [],
    }
    from .exemples import EXEMPLES_PAR_NATURE

    exemple.update(EXEMPLES_PAR_NATURE.get(nature, {}))
    return exemple


# --- Génération (DOC-02 à DOC-04, DOC-07) ------------------------------------------------------------


def _titre(modele: ModeleDocument, objet: Any) -> str:
    suffixe = getattr(objet, "numero", "") or (str(objet[1]) if isinstance(objet, tuple) else str(objet))
    return f"{modele.libelle} — {suffixe}"[:250]


def _rattachements(objet: Any) -> dict[str, Any]:
    from apps.reservations.models import Dossier, Occurrence

    if isinstance(objet, Dossier):
        return {"dossier": objet, "usager": objet.usager}
    if isinstance(objet, Occurrence):
        return {"dossier": objet.reservation.dossier, "usager": objet.reservation.dossier.usager}
    if isinstance(objet, tuple):
        return {"usager": objet[1]}
    dossier = getattr(objet, "dossier", None)
    usager = getattr(objet, "usager", None) or (dossier.usager if dossier is not None else None)
    return {"dossier": dossier, "usager": usager}


@transaction.atomic
def generer(
    modele: ModeleDocument | str,
    objet: Any,
    *,
    acteur: Any,
    parent: Document | None = None,
    complements: dict[str, Any] | None = None,
    lot: LotGeneration | None = None,
    controle_droits: bool = True,
) -> Document:
    """Fusion du modèle actif, conversion PDF/A-2b, empreinte SHA-256, rattachement au dossier."""
    if isinstance(modele, str):
        modele = ModeleDocument.objects.select_related("version_active__fichier").get(code=modele)
    if not modele.actif or modele.version_active is None:
        raise ErreurMetier(f"Le modèle « {modele.libelle} » n'a pas de version active.", code="modele_inactif")
    liens = _rattachements(objet)
    if controle_droits and isinstance(acteur, Utilisateur):
        exiger(acteur, "generer_document", liens.get("dossier") or modele)
    contexte = {**contextes.construire(modele.nature, objet), **(complements or {})}
    if parent is not None:
        contexte["avenant"] = {**contexte.get("avenant", {}), "numero_origine": parent.numero}
    docx = rendre_docx(fichiers.lire(modele.version_active.fichier), contexte)
    reference = numero("DOC", timezone.localdate().year)
    pdf = convertir_en_pdfa(reference, docx)
    fichier = fichiers.enregistrer_genere(f"{reference}.pdf", pdf, "application/pdf", depose_par=_acteur(acteur))
    document = Document.objects.create(
        numero=reference,
        modele=modele,
        version=modele.version_active,
        nature=modele.nature,
        titre=_titre(modele, objet),
        dossier=liens.get("dossier"),
        usager=liens.get("usager"),
        objet_type=objet._meta.label_lower if hasattr(objet, "_meta") else "",
        objet_id=str(getattr(objet, "pk", "")),
        parent=parent,
        contexte=contexte,
        fichier=fichier,
        sha256=fichier.sha256,
        lot=lot,
        cree_par=_acteur(acteur),
    )
    journaliser(
        "generer_document",
        document,
        apres={"modele": modele.code, "version": modele.version_active.numero, "sha256": fichier.sha256},
        acteur=acteur,
    )
    return document


@transaction.atomic
def generer_avenant(document: Document, *, acteur: Any, motif: str) -> Document:
    """DOC-05, RG-13 : un document signé ne se modifie pas ; la modification produit un avenant lié."""
    document = Document.objects.select_for_update().get(pk=document.pk)
    if not document.signe:
        raise ErreurMetier(
            "Ce document n'est pas signé : annulez-le et générez-en un nouveau plutôt qu'un avenant.", code="document_non_signe"
        )
    if len(motif.strip()) < 5:
        raise ErreurValidation("Indiquez l'objet de l'avenant.", code="motif_requis")
    objet = document.dossier if document.dossier_id else document.usager
    avenant = generer(
        "avenant",
        objet,
        acteur=acteur,
        parent=document,
        complements={"avenant": {"numero_origine": document.numero, "motif": motif.strip()}},
    )
    return avenant


@transaction.atomic
def annuler(document: Document, *, acteur: Any, motif: str) -> Document:
    """Un document non signé peut être annulé (il reste conservé, jamais supprimé)."""
    document = Document.objects.select_for_update().get(pk=document.pk)
    controler(acteur, "generer_document", document)
    if document.signe or document.nature in NATURES_COMPTABLES:
        raise ErreurMetier(
            "Un document signé, une facture ou un avoir ne s'annule pas : produisez un avenant ou un avoir.",
            code="document_immuable",
        )
    if not motif.strip():
        raise ErreurValidation("Indiquez le motif de l'annulation.", code="motif_requis")
    for circuit in document.circuits.filter(statut__in=["envoye", "preparation", "erreur"]):
        annuler_circuit(circuit, acteur=acteur, motif=motif)
    document.statut = "annule"
    document.motif_annulation = motif.strip()[:300]
    document.save(update_fields=["statut", "motif_annulation"])
    journaliser("annuler_document", document, apres={"motif": motif}, acteur=acteur)
    return document


def controler(acteur: Any, action: str, document: Document) -> None:
    if acteur == "système":
        return
    if isinstance(acteur, Utilisateur):
        exiger(acteur, action, document.dossier or document.modele)
        return
    raise AccesRefuse("Vous n'avez pas les droits pour cette action.", code="droits_insuffisants")


# --- Génération en lot (DOC-06) -----------------------------------------------------------------------


@transaction.atomic
def creer_lot(
    modele: ModeleDocument, dossiers: Iterable[Any], *, acteur: Any, libelle: str, envoyer_signature: bool = False
) -> LotGeneration:
    exiger(acteur, "generer_document", modele)
    identifiants = []
    for dossier in dossiers:
        exiger(acteur, "generer_document", dossier)
        identifiants.append(dossier.pk)
    if not identifiants:
        raise ErreurValidation("Aucun dossier sélectionné.", code="lot_vide")
    lot = LotGeneration.objects.create(
        modele=modele,
        libelle=libelle[:200],
        objets=identifiants,
        total=len(identifiants),
        envoyer_signature=envoyer_signature,
        cree_par=acteur,
    )
    journaliser("creer_lot_documents", lot, apres={"modele": modele.code, "total": len(identifiants)}, acteur=acteur)
    transaction.on_commit(lambda: _programmer_lot(lot.pk))
    return lot


def _programmer_lot(identifiant: int) -> None:
    from .tasks import executer_lot

    executer_lot.delay(identifiant)


def executer_lot(lot: LotGeneration) -> LotGeneration:
    """Idempotent : un dossier qui a déjà son document dans ce lot n'est pas retraité."""
    from apps.reservations.models import Dossier

    LotGeneration.objects.filter(pk=lot.pk).update(statut="en_cours")
    acteur = lot.cree_par or "système"
    deja = set(lot.documents.values_list("dossier_id", flat=True))
    erreurs = list(lot.erreurs)
    faits = len(deja)
    for identifiant in lot.objets:
        if identifiant in deja:
            continue
        dossier = Dossier.objects.select_related("usager", "type_reservation", "saison").filter(pk=identifiant).first()
        try:
            if dossier is None:
                raise ErreurMetier("Dossier introuvable.", code="dossier_introuvable")
            with transaction.atomic():
                document = generer(lot.modele, dossier, acteur=acteur, lot=lot, controle_droits=False)
                if lot.envoyer_signature and lot.modele.signature_requise:
                    envoyer_en_signature(document, acteur=acteur, controle_droits=False)
            faits += 1
        except ErreurMetier as erreur:
            erreurs.append({"dossier": dossier.numero if dossier else str(identifiant), "erreur": erreur.message})
        LotGeneration.objects.filter(pk=lot.pk).update(faits=faits, erreurs=erreurs)
    statut = "termine" if faits else "echec"
    LotGeneration.objects.filter(pk=lot.pk).update(statut=statut, faits=faits, erreurs=erreurs, termine_le=timezone.now())
    lot.refresh_from_db()
    return lot


# --- Signature (SIG-01 à SIG-05) ------------------------------------------------------------------------


def signataires_par_defaut(document: Document) -> list[dict[str, Any]]:
    """Ordre du modèle : représentant de l'usager habilité à signer, puis l'élu délégataire de la Ville."""
    liste: list[dict[str, Any]] = []
    for role in document.modele.signataires or ["usager", "elu"]:
        if role == "usager":
            if document.usager is None:
                raise ErreurValidation("Ce document n'est rattaché à aucun usager.", code="signataire_absent")
            lien = document.usager.rattachements.select_related("contact").filter(peut_signer=True).order_by("-principal").first()
            if lien is None:
                raise ErreurValidation(
                    "Aucun contact de l'usager n'est habilité à signer : cochez « peut signer » sur sa fiche.",
                    code="signataire_absent",
                )
            liste.append({"role": "usager", "nom": str(lien.contact), "courriel": lien.contact.courriel, "contact": lien.contact})
        elif role in {"elu", "agent"}:
            liste.append(
                {
                    "role": role,
                    "nom": str(parametre("signature.elu_nom")),
                    "courriel": str(parametre("signature.elu_courriel")),
                    "contact": None,
                }
            )
    return liste


@transaction.atomic
def envoyer_en_signature(
    document: Document, *, acteur: Any, mode: str | None = None, controle_droits: bool = True
) -> CircuitSignature:
    from django.conf import settings

    document = Document.objects.select_for_update(of=("self",)).select_related("modele", "usager", "fichier").get(pk=document.pk)
    if controle_droits:
        controler(acteur, "envoyer_signature", document)
    if document.statut != "genere":
        raise ErreurMetier(f"Un document « {document.get_statut_display()} » ne part pas en signature.", code="statut_document")
    mode = mode or settings.SIGNATURE_MODE
    signataires = signataires_par_defaut(document)
    expire = timezone.now() + timedelta(days=int(parametre("signature.expiration_jours")))
    circuit = CircuitSignature.objects.create(document=document, mode=mode, expire_le=expire, envoye_par=_acteur(acteur))
    for rang, s in enumerate(signataires):
        Signataire.objects.create(
            circuit=circuit, ordre=rang, role=s["role"], nom=s["nom"][:200], courriel=s["courriel"], contact=s["contact"]
        )
    document.statut = "en_signature"
    document.save(update_fields=["statut"])
    journaliser(
        "envoyer_signature", document, apres={"mode": mode, "signataires": [s["role"] for s in signataires]}, acteur=acteur
    )
    if mode == "docuseal":
        transaction.on_commit(lambda: _programmer_depot(circuit.pk))
    else:
        CircuitSignature.objects.filter(pk=circuit.pk).update(statut="envoye")
        circuit.statut = "envoye"
        if document.usager_id:
            notifier(
                "document_disponible", {"document": document, "dossier": document.dossier}, usager=document.usager, objet=document
            )
    return circuit


def _programmer_depot(identifiant: int) -> None:
    from .tasks import deposer_signature

    deposer_signature.delay(identifiant)


def deposer_aupres_de_docuseal(circuit: CircuitSignature, client: ClientDocuSeal | None = None) -> CircuitSignature:
    """Tâche du worker (seul conteneur qui sort vers la DMZ) : dépôt du PDF et des signataires ordonnés."""
    with transaction.atomic():
        circuit = CircuitSignature.objects.select_for_update(of=("self",)).select_related("document__fichier").get(pk=circuit.pk)
        if circuit.statut != "preparation":
            return circuit
        document = circuit.document
        signataires = [{"role": s.role, "nom": s.nom, "courriel": s.courriel} for s in circuit.signataires.order_by("ordre")]
        echeance = circuit.expire_le or timezone.now() + timedelta(days=int(parametre("signature.expiration_jours")))
        etat = (client or ClientDocuSeal()).creer(
            document.titre, fichiers.lire(document.fichier), signataires, echeance, document.numero
        )
        circuit.soumission, circuit.statut, circuit.erreur = etat.identifiant, "envoye", ""
        circuit.save(update_fields=["soumission", "statut", "erreur"])
        for signataire, distant in zip(circuit.signataires.order_by("ordre"), etat.signataires, strict=False):
            signataire.identifiant_externe = distant.identifiant
            signataire.lien_chiffre = chiffrer(distant.lien) if distant.lien else ""
            signataire.save(update_fields=["identifiant_externe", "lien_chiffre"])
        premier = circuit.signataires.order_by("ordre").first()
        if premier is not None and premier.contact is not None:
            notifier(
                "signature_demandee",
                {"document": document, "dossier": document.dossier, "expire_le": contextes.instant_lisible(circuit.expire_le)},
                contacts=[premier.contact],
                usager=document.usager,
                objet=document,
            )
        journaliser("deposer_signature", document, apres={"soumission": etat.identifiant}, acteur="système")
    return circuit


def signaler_echec_depot(circuit_id: int, message: str) -> None:
    CircuitSignature.objects.filter(pk=circuit_id, statut="preparation").update(statut="erreur", erreur=message[:300])
    Document.objects.filter(circuits__pk=circuit_id, statut="en_signature").update(statut="genere")


def lien_de_signature(document: Document, contact: Contact) -> str:
    """Lien personnel du contact, s'il est le signataire attendu (tour de signature respecté)."""
    circuit = document.circuits.filter(statut="envoye", mode="docuseal").first()
    if circuit is None:
        raise ErreurMetier("Ce document n'est pas en attente de signature électronique.", code="pas_de_signature")
    for signataire in circuit.signataires.order_by("ordre"):
        if signataire.statut == "signe":
            continue
        if signataire.contact_id != contact.pk or not signataire.lien_chiffre:
            raise ErreurMetier("Ce document attend la signature d'une autre personne.", code="pas_votre_tour")
        return dechiffrer(signataire.lien_chiffre)
    raise ErreurMetier("Toutes les signatures sont recueillies.", code="deja_signe")


STATUTS_SIGNATAIRE = {
    "completed": "signe",
    "opened": "ouvert",
    "declined": "refuse",
    "awaiting": "en_attente",
    "sent": "en_attente",
}


@transaction.atomic
def synchroniser(circuit: CircuitSignature, client: ClientDocuSeal | None = None) -> CircuitSignature:
    """SIG-02, SIG-03 : l'état est relu auprès de DocuSeal (jamais déduit du seul webhook), puis appliqué.

    Signature complète : PDF signé et journal de preuve rapatriés (contrôle antivirus), document
    « signé », soumission purgée côté DocuSeal. Idempotent.
    """
    circuit = CircuitSignature.objects.select_for_update(of=("self",)).select_related("document").get(pk=circuit.pk)
    if circuit.statut != "envoye" or circuit.mode != "docuseal":
        return circuit
    client = client or ClientDocuSeal()
    etat = client.lire(circuit.soumission)
    par_identifiant = {s.identifiant: s for s in etat.signataires}
    for signataire in circuit.signataires.all():
        distant = par_identifiant.get(signataire.identifiant_externe)
        if distant is None:
            continue
        nouveau = STATUTS_SIGNATAIRE.get(distant.statut, signataire.statut)
        if nouveau != signataire.statut:
            signataire.statut = nouveau
            signataire.signe_le = timezone.now() if nouveau == "signe" else signataire.signe_le
            signataire.save(update_fields=["statut", "signe_le"])
    document = Document.objects.select_for_update().get(pk=circuit.document_id)
    if etat.statut == "completed":
        if not etat.documents:
            raise ErreurMetier(
                "Signature terminée mais document signé indisponible : nouvelle tentative plus tard.",
                code="docuseal_document_absent",
            )
        signe = fichiers.enregistrer(f"{document.numero}-signe.pdf", client.telecharger(etat.documents[0]), depose_par="DocuSeal")
        preuve = (
            fichiers.enregistrer(f"{document.numero}-preuve.pdf", client.telecharger(etat.preuve), depose_par="DocuSeal")
            if etat.preuve
            else None
        )
        document.statut, document.fichier_signe, document.preuve = "signe", signe, preuve
        document.signe_le = timezone.now()
        document.signe_par = ", ".join(s.nom for s in circuit.signataires.order_by("ordre"))[:250]
        document.save(update_fields=["statut", "fichier_signe", "preuve", "signe_le", "signe_par"])
        circuit.statut, circuit.termine_le = "signe", timezone.now()
        circuit.save(update_fields=["statut", "termine_le"])
        journaliser("document_signe", document, apres={"sha256_signe": signe.sha256}, acteur="DocuSeal")
        _purger(circuit, client)
        if document.usager_id:
            notifier(
                "signature_terminee", {"document": document, "dossier": document.dossier}, usager=document.usager, objet=document
            )
    elif etat.statut in {"expired", "declined"}:
        circuit.statut = "expire" if etat.statut == "expired" else "refuse"
        circuit.termine_le = timezone.now()
        circuit.save(update_fields=["statut", "termine_le"])
        document.statut = "genere"
        document.save(update_fields=["statut"])
        journaliser(f"signature_{circuit.statut}", document, acteur="DocuSeal")
        _purger(circuit, client)
        if document.usager_id:
            notifier(
                "signature_expiree", {"document": document, "dossier": document.dossier}, usager=document.usager, objet=document
            )
    return circuit


def _purger(circuit: CircuitSignature, client: ClientDocuSeal) -> None:
    """SIG-03 : la DMZ ne conserve pas les documents ; un échec de purge est retenté par la tâche planifiée."""
    try:
        with transaction.atomic():
            client.archiver(circuit.soumission)
            CircuitSignature.objects.filter(pk=circuit.pk).update(purge_le=timezone.now())
    except ErreurMetier as erreur:
        journal.warning("Purge DocuSeal reportée pour le circuit %s : %s", circuit.pk, erreur.message)


def traiter_webhook(corps: dict[str, Any]) -> CircuitSignature | None:
    """Webhook relayé par la façade : on n'en retient que l'identifiant de soumission ; la relecture de
    l'état auprès de DocuSeal est faite par le worker (l'API portail ne sort pas vers la DMZ)."""
    donnees = corps.get("data") if isinstance(corps, dict) else None
    if not isinstance(donnees, dict):
        raise ErreurValidation("Notification de signature illisible.", code="webhook_invalide")
    soumission = donnees.get("submission", {}).get("id") if isinstance(donnees.get("submission"), dict) else None
    identifiant = str(soumission or donnees.get("submission_id") or donnees.get("id") or "")
    if not identifiant.isdigit():
        raise ErreurValidation("Notification de signature sans soumission.", code="webhook_invalide")
    circuit = CircuitSignature.objects.filter(soumission=identifiant, mode="docuseal").first()
    if circuit is None:
        journal.warning("Webhook DocuSeal pour une soumission inconnue (%s) ignoré", identifiant)
        return None
    from .tasks import synchroniser_signature

    transaction.on_commit(lambda: synchroniser_signature.delay(circuit.pk))
    return circuit


@transaction.atomic
def annuler_circuit(circuit: CircuitSignature, *, acteur: Any, motif: str) -> CircuitSignature:
    """SIG-04 : l'agent annule une signature en cours (la soumission DocuSeal est archivée)."""
    circuit = CircuitSignature.objects.select_for_update(of=("self",)).select_related("document").get(pk=circuit.pk)
    controler(acteur, "envoyer_signature", circuit.document)
    if circuit.statut not in {"envoye", "preparation", "erreur"}:
        raise ErreurMetier("Cette signature n'est plus en cours.", code="statut_signature")
    circuit.statut, circuit.termine_le, circuit.erreur = "annule", timezone.now(), motif[:300]
    circuit.save(update_fields=["statut", "termine_le", "erreur"])
    Document.objects.filter(pk=circuit.document_id, statut="en_signature").update(statut="genere")
    journaliser("annuler_signature", circuit.document, apres={"motif": motif}, acteur=acteur)
    transaction.on_commit(_programmer_purges)
    return circuit


def _programmer_purges() -> None:
    from .tasks import synchroniser_signatures

    synchroniser_signatures.delay()


def relancer_signatures(maintenant: Any = None) -> int:
    """SIG-04 : relance automatique `signature.relance_jours_avant` jours avant l'échéance (une fois)."""
    maintenant = maintenant or timezone.now()
    limite = maintenant + timedelta(days=int(parametre("signature.relance_jours_avant")))
    nombre = 0
    for circuit in CircuitSignature.objects.filter(
        statut="envoye", relance_le__isnull=True, expire_le__lte=limite
    ).select_related("document"):
        with transaction.atomic():
            attendu = circuit.signataires.exclude(statut="signe").order_by("ordre").first()
            if attendu is None:
                continue
            if circuit.mode == "docuseal" and attendu.identifiant_externe:
                try:
                    ClientDocuSeal().relancer(attendu.identifiant_externe)
                except ErreurMetier as erreur:
                    journal.warning("Relance DocuSeal impossible (%s) : %s", circuit.pk, erreur.message)
            if attendu.contact is not None:
                notifier(
                    "signature_relance",
                    {
                        "document": circuit.document,
                        "dossier": circuit.document.dossier,
                        "expire_le": contextes.instant_lisible(circuit.expire_le),
                    },
                    contacts=[attendu.contact],
                    usager=circuit.document.usager,
                    objet=circuit.document,
                )
            CircuitSignature.objects.filter(pk=circuit.pk).update(relance_le=maintenant)
            nombre += 1
    return nombre


def synchroniser_en_cours() -> int:
    """Filet de sécurité si un webhook est perdu : relecture périodique des signatures en cours."""
    nombre = 0
    for circuit in CircuitSignature.objects.filter(statut="envoye", mode="docuseal").exclude(soumission=""):
        try:
            synchroniser(circuit)
            nombre += 1
        except ErreurMetier as erreur:
            journal.warning("Synchronisation DocuSeal impossible (%s) : %s", circuit.pk, erreur.message)
    for circuit in CircuitSignature.objects.filter(
        statut__in=["signe", "expire", "refuse", "annule"], purge_le__isnull=True, mode="docuseal"
    ).exclude(soumission=""):
        _purger(circuit, ClientDocuSeal())
    return nombre


@transaction.atomic
def deposer_scan_signe(
    document: Document, nom: str, contenu: bytes, *, acteur: Any, portail: bool = False, **controle: str
) -> Document:
    """SIG-05 : circuit manuel — scan du document signé déposé par l'agent ou l'usager."""
    document = Document.objects.select_for_update().get(pk=document.pk)
    if not portail:
        controler(acteur, "envoyer_signature", document)
    if document.statut not in {"genere", "en_signature"} or not document.modele.signature_requise:
        raise ErreurMetier("Ce document n'attend pas de signature.", code="statut_document")
    scan = fichiers.enregistrer(nom, contenu, types_autorises=("application/pdf",), depose_par=_acteur(acteur), **controle)
    for circuit in document.circuits.filter(statut__in=["envoye", "preparation", "erreur"]):
        circuit.statut, circuit.termine_le = "signe", timezone.now()
        circuit.save(update_fields=["statut", "termine_le"])
    transaction.on_commit(_programmer_purges)
    document.statut, document.fichier_signe = "signe_manuellement", scan
    document.signe_le, document.signe_par = timezone.now(), _acteur(acteur)
    document.save(update_fields=["statut", "fichier_signe", "signe_le", "signe_par"])
    journaliser("deposer_scan_signe", document, apres={"sha256": scan.sha256, "portail": portail}, acteur=acteur)
    return document


# --- Condition RG-06 « convention signée » ------------------------------------------------------------------


def convention_manquante(reservation: Any) -> str | None:
    signee = Document.objects.filter(
        dossier_id=reservation.dossier_id, nature__in=["convention", "contrat_location"], statut__in=STATUTS_SIGNES
    ).exists()
    if signee:
        return None
    en_cours = Document.objects.filter(
        dossier_id=reservation.dossier_id, nature__in=["convention", "contrat_location"], statut="en_signature"
    )
    return "convention en cours de signature" if en_cours.exists() else "faire signer la convention ou le contrat"


def documents_du_dossier(dossier: Any) -> QuerySet[Document]:
    return Document.objects.filter(dossier=dossier).select_related("modele", "version").order_by("-cree_le")
