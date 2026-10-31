"""Modèles de documents, documents générés et circuits de signature (DOC-01 à DOC-07, SIG-01 à SIG-05, RG-13).

- Un **modèle** (.docx éditable dans Word) a des **versions** immuables ; un document généré référence
  la version exacte utilisée et conserve son contexte de fusion.
- Un **document** est un PDF/A-2b dont l'empreinte SHA-256 est enregistrée. Une fois signé (ou pour une
  facture, un avoir), son contenu ne change plus : la base refuse la modification (RG-13). Toute
  correction passe par un avenant (document lié) ou un avoir.
- Un **circuit de signature** (DocuSeal ou manuel) porte les signataires ordonnés et l'échéance.
"""

from __future__ import annotations

from django.conf import settings
from django.db import models

NATURES = [
    ("convention", "Convention d'occupation"),
    ("contrat_location", "Contrat de location"),
    ("avenant", "Avenant"),
    ("devis", "Devis"),
    ("facture", "Facture"),
    ("avoir", "Avoir"),
    ("etat_des_lieux", "État des lieux"),
    ("attribution", "Courrier d'attribution de créneaux"),
    ("refus", "Courrier de refus motivé"),
    ("attestation_valorisation", "Attestation de valorisation des avantages en nature"),
    ("fermeture", "Avis de fermeture exceptionnelle"),
]
NATURES_COMPTABLES = frozenset({"devis", "facture", "avoir"})
STATUTS_SIGNES = frozenset({"signe", "signe_manuellement"})


class ModeleDocument(models.Model):
    code = models.SlugField(max_length=60, unique=True)
    libelle = models.CharField(max_length=150)
    nature = models.CharField(max_length=30, choices=NATURES)
    description = models.TextField(blank=True, default="")
    signature_requise = models.BooleanField(default=False)
    signataires = models.JSONField(
        default=list, blank=True, help_text="Rôles des signataires dans l'ordre : « usager », « elu », « agent »."
    )
    version_active = models.ForeignKey(
        "VersionModele", null=True, blank=True, on_delete=models.PROTECT, related_name="+", help_text="Version utilisée."
    )
    actif = models.BooleanField(default=True)

    ecriture_ville_entiere = True

    class Meta:
        ordering = ["nature", "libelle"]

    def __str__(self) -> str:
        return self.libelle

    def sites_concernes(self) -> None:
        return None


class VersionModele(models.Model):
    """Version déposée d'un modèle : jamais modifiée ni supprimée (ajout seul)."""

    immuable = True

    modele = models.ForeignKey(ModeleDocument, on_delete=models.PROTECT, related_name="versions")
    numero = models.PositiveIntegerField()
    fichier = models.ForeignKey("noyau.Fichier", on_delete=models.PROTECT, related_name="+")
    commentaire = models.CharField(max_length=250, blank=True, default="")
    deposee_par = models.CharField(max_length=200, blank=True, default="")
    deposee_le = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["modele", "-numero"]
        constraints = [models.UniqueConstraint(fields=["modele", "numero"], name="version_modele_unique")]

    def __str__(self) -> str:
        return f"{self.modele} v{self.numero}"

    def sites_concernes(self) -> None:
        return None


class LotGeneration(models.Model):
    """Génération en lot (DOC-06) : progression et rapport d'erreurs."""

    STATUTS = [("en_attente", "En attente"), ("en_cours", "En cours"), ("termine", "Terminé"), ("echec", "En échec")]
    modele = models.ForeignKey(ModeleDocument, on_delete=models.PROTECT, related_name="lots")
    libelle = models.CharField(max_length=200)
    objets = models.JSONField(default=list, help_text="Identifiants des dossiers à traiter.")
    statut = models.CharField(max_length=12, choices=STATUTS, default="en_attente")
    total = models.PositiveIntegerField(default=0)
    faits = models.PositiveIntegerField(default=0)
    erreurs = models.JSONField(default=list, blank=True)
    envoyer_signature = models.BooleanField(default=False)
    cree_par = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, on_delete=models.SET_NULL, related_name="+")
    cree_le = models.DateTimeField(auto_now_add=True)
    termine_le = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["-cree_le"]

    def __str__(self) -> str:
        return self.libelle

    def sites_concernes(self) -> None:
        return None


class Document(models.Model):
    STATUTS = [
        ("genere", "Généré"),
        ("en_signature", "En signature"),
        ("signe", "Signé électroniquement"),
        ("signe_manuellement", "Signé manuellement"),
        ("scan_a_controler", "Scan signé à contrôler"),
        ("annule", "Annulé"),
    ]
    numero = models.CharField(max_length=20, unique=True)
    modele = models.ForeignKey(ModeleDocument, on_delete=models.PROTECT, related_name="documents")
    version = models.ForeignKey(VersionModele, on_delete=models.PROTECT, related_name="documents")
    nature = models.CharField(max_length=30, choices=NATURES)
    titre = models.CharField(max_length=250)
    dossier = models.ForeignKey("reservations.Dossier", null=True, blank=True, on_delete=models.PROTECT, related_name="documents")
    usager = models.ForeignKey("usagers.Usager", null=True, blank=True, on_delete=models.PROTECT, related_name="documents")
    objet_type = models.CharField(max_length=80, blank=True, default="")
    objet_id = models.CharField(max_length=64, blank=True, default="")
    parent = models.ForeignKey(
        "self", null=True, blank=True, on_delete=models.PROTECT, related_name="avenants", help_text="Document modifié (avenant)."
    )
    contexte = models.JSONField(default=dict, help_text="Contexte de fusion figé à la génération.")
    fichier = models.ForeignKey("noyau.Fichier", on_delete=models.PROTECT, related_name="+")
    sha256 = models.CharField(max_length=64)
    statut = models.CharField(max_length=20, choices=STATUTS, default="genere")
    fichier_signe = models.ForeignKey("noyau.Fichier", null=True, blank=True, on_delete=models.PROTECT, related_name="+")
    preuve = models.ForeignKey("noyau.Fichier", null=True, blank=True, on_delete=models.PROTECT, related_name="+")
    scan_depose = models.ForeignKey(
        "noyau.Fichier", null=True, blank=True, on_delete=models.PROTECT, related_name="+", help_text="SIG-05 : scan à contrôler."
    )
    signe_le = models.DateTimeField(null=True, blank=True)
    signe_par = models.CharField(max_length=250, blank=True, default="", help_text="Signataires ou agent ayant constaté.")
    visible_portail = models.BooleanField(default=True)
    lot = models.ForeignKey(LotGeneration, null=True, blank=True, on_delete=models.SET_NULL, related_name="documents")
    motif_annulation = models.CharField(max_length=300, blank=True, default="")
    cree_par = models.CharField(max_length=200, blank=True, default="")
    cree_le = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-cree_le"]
        indexes = [models.Index(fields=["objet_type", "objet_id"]), models.Index(fields=["nature", "statut"])]

    def __str__(self) -> str:
        return f"{self.numero} — {self.titre}"

    def sites_concernes(self) -> set[int] | None:
        return self.dossier.sites_concernes() if self.dossier is not None else None

    @property
    def signe(self) -> bool:
        return self.statut in STATUTS_SIGNES

    @property
    def fichier_courant(self) -> object:
        return self.fichier_signe or self.fichier


class CircuitSignature(models.Model):
    MODES = [("docuseal", "Signature électronique (DocuSeal)"), ("manuel", "Signature manuscrite (scan déposé)")]
    STATUTS = [
        ("preparation", "Dépôt en cours auprès du service de signature"),
        ("envoye", "Envoyé"),
        ("signe", "Signé"),
        ("expire", "Expiré"),
        ("annule", "Annulé"),
        ("refuse", "Refusé par un signataire"),
        ("erreur", "Erreur d'envoi"),
    ]
    document = models.ForeignKey(Document, on_delete=models.PROTECT, related_name="circuits")
    mode = models.CharField(max_length=10, choices=MODES, default="docuseal")
    statut = models.CharField(max_length=12, choices=STATUTS, default="preparation")
    soumission = models.CharField(max_length=64, blank=True, default="", db_index=True)
    envoye_le = models.DateTimeField(auto_now_add=True)
    expire_le = models.DateTimeField(null=True, blank=True)
    relance_le = models.DateTimeField(null=True, blank=True)
    termine_le = models.DateTimeField(null=True, blank=True)
    purge_le = models.DateTimeField(null=True, blank=True, help_text="Soumission supprimée côté DocuSeal (SIG-03).")
    erreur = models.CharField(max_length=300, blank=True, default="")
    envoye_par = models.CharField(max_length=200, blank=True, default="")

    class Meta:
        ordering = ["-envoye_le"]

    def __str__(self) -> str:
        return f"Signature {self.document.numero} ({self.get_statut_display()})"

    def sites_concernes(self) -> set[int] | None:
        return self.document.sites_concernes()


class Signataire(models.Model):
    ROLES = [("usager", "Représentant de l'usager"), ("elu", "Élu ou agent délégataire"), ("agent", "Agent de la Ville")]
    STATUTS = [("en_attente", "En attente"), ("ouvert", "Document ouvert"), ("signe", "Signé"), ("refuse", "Refusé")]
    circuit = models.ForeignKey(CircuitSignature, on_delete=models.CASCADE, related_name="signataires")
    ordre = models.PositiveSmallIntegerField()
    role = models.CharField(max_length=10, choices=ROLES)
    nom = models.CharField(max_length=200)
    courriel = models.EmailField()
    contact = models.ForeignKey("usagers.Contact", null=True, blank=True, on_delete=models.SET_NULL, related_name="+")
    identifiant_externe = models.CharField(max_length=64, blank=True, default="")
    lien_chiffre = models.TextField(blank=True, default="", help_text="Lien personnel de signature, chiffré.")
    statut = models.CharField(max_length=12, choices=STATUTS, default="en_attente")
    invite_le = models.DateTimeField(null=True, blank=True, help_text="SIG-01 : invitation envoyée à son tour.")
    signe_le = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["circuit", "ordre"]

    def __str__(self) -> str:
        return f"{self.nom} ({self.get_role_display()})"
