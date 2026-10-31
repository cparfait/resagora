"""Usagers, contacts et pièces justificatives (USR-01 à USR-05).

Un usager (association, école, entreprise ou CSE, particulier, service municipal) est transversal :
il réserve sur plusieurs sites (D-013). Les contacts sont les personnes physiques ; un contact peut
représenter plusieurs usagers (rattachements), et c'est lui qui détient le compte du portail (lot 2).
"""

from __future__ import annotations

import unicodedata
from datetime import date

from django.conf import settings
from django.contrib.postgres.fields import ArrayField
from django.db import models
from django.utils import timezone

TYPES_USAGER = [
    ("association", "Association"),
    ("ecole", "École ou établissement scolaire"),
    ("entreprise", "Entreprise ou comité social et économique"),
    ("particulier", "Particulier"),
    ("service_municipal", "Service municipal"),
    ("autre_collectivite", "Autre collectivité ou organisme public"),
]


def normaliser_commune(nom: str) -> str:
    texte = unicodedata.normalize("NFKD", nom).encode("ascii", "ignore").decode().lower()
    return "".join(c for c in texte if c.isalnum())


class Usager(models.Model):
    STATUTS = [
        ("en_attente", "En attente de validation"),
        ("valide", "Validé"),
        ("suspendu", "Suspendu"),
        ("anonymise", "Anonymisé"),
    ]

    type = models.CharField(max_length=20, choices=TYPES_USAGER)
    nom = models.CharField("nom ou raison sociale", max_length=200)
    sigle = models.CharField(max_length=40, blank=True, default="")
    siret = models.CharField("SIRET", max_length=14, blank=True, default="")
    rna = models.CharField("numéro RNA", max_length=10, blank=True, default="")
    adresse = models.CharField(max_length=250, blank=True, default="")
    code_postal = models.CharField(max_length=5, blank=True, default="")
    commune = models.CharField(max_length=80, blank=True, default="")
    telephone = models.CharField(max_length=20, blank=True, default="")
    courriel = models.EmailField(blank=True, default="")
    resident = models.BooleanField(default=False, help_text="Calculé : siège ou domicile sur la commune (tarif résident).")
    local = models.BooleanField("association locale", default=False, help_text="Siège sur la commune (priorité RG-03).")
    conventionne = models.BooleanField("conventionné(e) avec la Ville", default=False)
    convention_reference = models.CharField(max_length=100, blank=True, default="")
    convention_fin = models.DateField(null=True, blank=True)
    statut = models.CharField(max_length=12, choices=STATUTS, default="valide")
    observations = models.TextField(blank=True, default="")
    cree_le = models.DateTimeField(auto_now_add=True)
    derniere_activite = models.DateTimeField(default=timezone.now)
    anonymise_le = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["nom"]
        indexes = [models.Index(fields=["type", "statut"])]

    def __str__(self) -> str:
        return self.nom

    def sites_concernes(self) -> None:
        return None

    def save(self, *args: object, **kwargs: object) -> None:
        from apps.noyau.parametres import parametre

        commune = normaliser_commune(self.commune)
        self.resident = bool(commune) and commune == normaliser_commune(str(parametre("usagers.commune_residence")))
        super().save(*args, **kwargs)  # type: ignore[arg-type]

    def convention_active(self, jour: date | None = None) -> bool:
        """USR-04 : convention en cours à la date donnée (utilisée par la priorité RG-03)."""
        jour = jour or timezone.localdate()
        return self.conventionne and (self.convention_fin is None or self.convention_fin >= jour)


class Contact(models.Model):
    civilite = models.CharField(max_length=10, blank=True, default="")
    prenom = models.CharField(max_length=100)
    nom = models.CharField(max_length=100)
    courriel = models.EmailField(db_index=True)
    telephone = models.CharField(max_length=20, blank=True, default="")
    cree_le = models.DateTimeField(auto_now_add=True)
    anonymise_le = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["nom", "prenom"]

    def __str__(self) -> str:
        return f"{self.prenom} {self.nom}".strip()

    def sites_concernes(self) -> None:
        return None


class Rattachement(models.Model):
    ROLES = [
        ("president", "Président(e)"),
        ("tresorier", "Trésorier(ère)"),
        ("secretaire", "Secrétaire"),
        ("referent", "Référent(e)"),
        ("directeur", "Directeur(trice)"),
        ("responsable", "Responsable"),
        ("autre", "Autre"),
    ]
    usager = models.ForeignKey(Usager, on_delete=models.CASCADE, related_name="rattachements")
    contact = models.ForeignKey(Contact, on_delete=models.CASCADE, related_name="rattachements")
    role = models.CharField(max_length=20, choices=ROLES, default="referent")
    principal = models.BooleanField(default=False)
    peut_signer = models.BooleanField(default=False, help_text="Signe les conventions au nom de l'usager.")

    class Meta:
        ordering = ["usager", "-principal", "contact"]
        constraints = [models.UniqueConstraint(fields=["usager", "contact"], name="rattachement_unique")]

    def __str__(self) -> str:
        return f"{self.contact} — {self.get_role_display()} de {self.usager}"

    def sites_concernes(self) -> None:
        return None


class TypePiece(models.Model):
    code = models.SlugField(max_length=40, unique=True)
    libelle = models.CharField(max_length=150)
    description = models.TextField(blank=True, default="")
    types_usager = ArrayField(models.CharField(max_length=20, choices=TYPES_USAGER), default=list)
    obligatoire = models.BooleanField(default=True)
    validite_mois = models.PositiveSmallIntegerField(null=True, blank=True, help_text="Vide : pas d'expiration.")

    ecriture_ville_entiere = True

    class Meta:
        ordering = ["libelle"]

    def __str__(self) -> str:
        return self.libelle

    def sites_concernes(self) -> None:
        return None


class PieceJustificative(models.Model):
    STATUTS = [("a_verifier", "À vérifier"), ("valide", "Valide"), ("refuse", "Refusée")]
    usager = models.ForeignKey(Usager, on_delete=models.CASCADE, related_name="pieces")
    type_piece = models.ForeignKey(TypePiece, on_delete=models.PROTECT, related_name="pieces")
    fichier = models.ForeignKey("noyau.Fichier", on_delete=models.PROTECT, related_name="+")
    valide_du = models.DateField(null=True, blank=True)
    valide_jusqu_au = models.DateField(null=True, blank=True)
    statut = models.CharField(max_length=12, choices=STATUTS, default="a_verifier")
    motif_refus = models.CharField(max_length=250, blank=True, default="")
    verifie_par = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name="+")
    verifie_le = models.DateTimeField(null=True, blank=True)
    depose_le = models.DateTimeField(auto_now_add=True)
    depose_par_portail = models.BooleanField(default=False)
    deposee_par = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name="+")

    class Meta:
        ordering = ["usager", "type_piece", "-depose_le"]

    def __str__(self) -> str:
        return f"{self.type_piece} — {self.usager}"

    def sites_concernes(self) -> None:
        return None

    def valide_le(self, jour: date) -> bool:
        if self.statut != "valide":
            return False
        if self.valide_du and jour < self.valide_du:
            return False
        return self.valide_jusqu_au is None or jour <= self.valide_jusqu_au
