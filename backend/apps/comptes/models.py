"""Comptes des usagers sur le portail (POR-01, SEC-04).

Le compte appartient à un **contact** (personne physique) ; il donne accès aux usagers auxquels ce
contact est rattaché. Mot de passe haché en Argon2id ; jetons (session API, confirmation, réinitialisation,
défi de double authentification) conservés uniquement sous forme d'empreinte HMAC.
"""

from __future__ import annotations

from django.conf import settings
from django.db import models
from django.utils import timezone


class CompteUsager(models.Model):
    STATUTS = [
        ("a_confirmer", "Courriel à confirmer"),
        ("a_valider", "En attente de validation par la Ville"),
        ("actif", "Actif"),
        ("suspendu", "Suspendu"),
        ("ferme", "Fermé"),
    ]

    contact = models.OneToOneField("usagers.Contact", on_delete=models.PROTECT, related_name="compte")
    identifiant = models.EmailField("identifiant (adresse électronique)", unique=True)
    mot_de_passe = models.CharField(max_length=200)
    statut = models.CharField(max_length=12, choices=STATUTS, default="a_confirmer")
    courriel_confirme_le = models.DateTimeField(null=True, blank=True)
    valide_par = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name="+")
    valide_le = models.DateTimeField(null=True, blank=True)
    motif_suspension = models.CharField(max_length=250, blank=True, default="")
    totp_actif = models.BooleanField(default=False)
    totp_secret_chiffre = models.TextField(blank=True, default="")
    totp_en_attente_chiffre = models.TextField(blank=True, default="")
    echecs_connexion = models.PositiveSmallIntegerField(default=0)
    verrouille_jusqu_au = models.DateTimeField(null=True, blank=True)
    recidives = models.PositiveSmallIntegerField(default=0)
    derniere_connexion = models.DateTimeField(null=True, blank=True)
    mot_de_passe_modifie_le = models.DateTimeField(default=timezone.now)
    cree_le = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["identifiant"]
        verbose_name = "compte du portail"

    def __str__(self) -> str:
        return self.identifiant

    def sites_concernes(self) -> None:
        return None

    @property
    def is_authenticated(self) -> bool:
        return True

    @property
    def verrouille(self) -> bool:
        return self.verrouille_jusqu_au is not None and self.verrouille_jusqu_au > timezone.now()


class JetonPortail(models.Model):
    """Jeton de session API détenu par la façade (jamais par le navigateur)."""

    compte = models.ForeignKey(CompteUsager, on_delete=models.CASCADE, related_name="jetons")
    empreinte = models.CharField(max_length=64, unique=True)
    cree_le = models.DateTimeField(auto_now_add=True)
    expire_le = models.DateTimeField()
    derniere_utilisation = models.DateTimeField(null=True, blank=True)
    revoque_le = models.DateTimeField(null=True, blank=True)

    class Meta:
        indexes = [models.Index(fields=["compte", "revoque_le"])]

    def __str__(self) -> str:
        return f"Jeton {self.compte_id} jusqu'au {self.expire_le:%d/%m/%Y %H:%M}"


class JetonUnique(models.Model):
    """Lien ou défi à usage unique et de courte durée."""

    NATURES = [
        ("confirmation", "Confirmation de l'adresse électronique"),
        ("invitation", "Invitation d'un contact à créer son compte"),
        ("reinitialisation", "Réinitialisation du mot de passe"),
        ("defi_totp", "Défi de double authentification"),
        ("changement_courriel", "Confirmation d'une nouvelle adresse électronique"),
    ]
    compte = models.ForeignKey(CompteUsager, on_delete=models.CASCADE, related_name="jetons_uniques")
    nature = models.CharField(max_length=20, choices=NATURES)
    empreinte = models.CharField(max_length=64, unique=True)
    expire_le = models.DateTimeField()
    utilise_le = models.DateTimeField(null=True, blank=True)
    donnee = models.CharField(max_length=254, blank=True, default="", help_text="Nouvelle adresse à confirmer.")
    cree_le = models.DateTimeField(auto_now_add=True)

    class Meta:
        indexes = [models.Index(fields=["compte", "nature"])]

    def __str__(self) -> str:
        return f"{self.get_nature_display()} — {self.compte_id}"
