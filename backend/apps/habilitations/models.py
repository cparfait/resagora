"""Agents, rôles, périmètres et habilitations (RG-14, ADM-03, ADM-06)."""

from __future__ import annotations

from django.contrib.auth.models import AbstractUser
from django.contrib.postgres.fields import ArrayField
from django.db import models
from django.db.models.functions import Lower
from django.utils import timezone


class Utilisateur(AbstractUser):
    """Agent de la Ville authentifié par l'Active Directory (SEC-02)."""

    SOURCES = [("ad", "Active Directory"), ("local", "Compte technique local")]
    source = models.CharField(max_length=8, choices=SOURCES, default="ad")
    totp_secret_chiffre = models.TextField(blank=True, default="")
    totp_actif = models.BooleanField(default=False)
    totp_reinitialise = models.BooleanField(default=False, help_text="Réenrôlement soumis au code remis par l'administrateur.")
    jeton_enrolement_empreinte = models.CharField(max_length=64, blank=True, default="")
    jeton_enrolement_expire = models.DateTimeField(null=True, blank=True)
    identifiant_annuaire = models.CharField(
        "identifiant immuable dans l'annuaire",
        max_length=64,
        unique=True,
        null=True,
        blank=True,
        help_text="objectGUID (Active Directory) ou entryUUID : l'agent n'est jamais apparié par son seul nom de compte.",
    )
    derniere_synchronisation_ad = models.DateTimeField(null=True, blank=True)

    class Meta:
        verbose_name = "agent"
        ordering = ["last_name", "first_name"]

    def __str__(self) -> str:
        return self.get_full_name() or self.username

    @property
    def nom_affiche(self) -> str:
        return self.get_full_name() or self.username

    def habilitations_actives(self) -> list[Habilitation]:
        cache = getattr(self, "_habilitations_cache", None)
        if cache is None:
            aujourd_hui = timezone.localdate()
            cache = list(
                self.habilitations.filter(models.Q(fin__isnull=True) | models.Q(fin__gte=aujourd_hui), debut__lte=aujourd_hui)
                .select_related("role", "perimetre")
                .prefetch_related("perimetre__sites")
            )
            self._habilitations_cache = cache
        return cache

    def vider_cache_habilitations(self) -> None:
        self.__dict__.pop("_habilitations_cache", None)

    def exige_double_authentification(self) -> bool:
        return any(h.role.double_authentification for h in self.habilitations_actives())


class Role(models.Model):
    code = models.SlugField(max_length=40, unique=True)
    libelle = models.CharField(max_length=120)
    actions = ArrayField(models.CharField(max_length=40), default=list)
    double_authentification = models.BooleanField(
        default=False, help_text="Double authentification obligatoire (administration, régie : SEC-03)."
    )

    class Meta:
        ordering = ["libelle"]

    def __str__(self) -> str:
        return self.libelle

    def save(self, *args: object, **kwargs: object) -> None:
        from .actions import ACTIONS_SENSIBLES

        # Un rôle qui porte une action sensible exige toujours la double authentification (SEC-03).
        if ACTIONS_SENSIBLES.intersection(self.actions):
            self.double_authentification = True
        super().save(*args, **kwargs)  # type: ignore[arg-type]


class Perimetre(models.Model):
    """Ensemble de sites sur lequel s'exerce une habilitation ; `tous_sites` couvre la Ville entière."""

    nom = models.CharField(max_length=120, unique=True)
    tous_sites = models.BooleanField(default=False)
    sites = models.ManyToManyField("referentiel.Site", blank=True, related_name="perimetres")

    class Meta:
        ordering = ["nom"]

    def __str__(self) -> str:
        return self.nom


class Habilitation(models.Model):
    SOURCES = [("ad", "Groupe AD"), ("manuel", "Attribution manuelle")]
    utilisateur = models.ForeignKey(Utilisateur, on_delete=models.CASCADE, related_name="habilitations")
    role = models.ForeignKey(Role, on_delete=models.PROTECT, related_name="habilitations")
    perimetre = models.ForeignKey(Perimetre, on_delete=models.PROTECT, related_name="habilitations")
    source = models.CharField(max_length=8, choices=SOURCES, default="manuel")
    groupe_ad = models.ForeignKey("GroupeAD", null=True, blank=True, on_delete=models.CASCADE, related_name="habilitations")
    debut = models.DateField(default=timezone.localdate)
    fin = models.DateField(null=True, blank=True)

    class Meta:
        ordering = ["utilisateur", "role"]
        constraints = [
            models.UniqueConstraint(fields=["utilisateur", "role", "perimetre", "source"], name="habilitation_unique_par_source"),
            models.CheckConstraint(
                condition=models.Q(fin__isnull=True) | models.Q(fin__gte=models.F("debut")), name="habilitation_dates"
            ),
        ]

    def __str__(self) -> str:
        return f"{self.utilisateur} — {self.role} — {self.perimetre}"


class GroupeAD(models.Model):
    """Correspondance configurable groupe AD → rôle × périmètre (ADM-06)."""

    dn = models.CharField("DN du groupe", max_length=500, unique=True)
    libelle = models.CharField(max_length=200, blank=True, default="")
    role = models.ForeignKey(Role, on_delete=models.PROTECT, related_name="groupes_ad")
    perimetre = models.ForeignKey(Perimetre, on_delete=models.PROTECT, related_name="groupes_ad")
    actif = models.BooleanField(default=True)

    class Meta:
        verbose_name = "groupe AD"
        ordering = ["dn"]
        constraints = [models.UniqueConstraint(Lower("dn"), name="groupe_ad_dn_unique_sans_casse")]

    def __str__(self) -> str:
        return self.libelle or self.dn

    def save(self, *args: object, **kwargs: object) -> None:
        from .services import propager_groupe_ad

        self.dn = self.dn.strip()
        super().save(*args, **kwargs)  # type: ignore[arg-type]
        propager_groupe_ad(self)

    def delete(self, *args: object, **kwargs: object) -> tuple[int, dict[str, int]]:
        from apps.audit.services import journaliser

        for habilitation in self.habilitations.all():
            journaliser("retirer_habilitation_ad", habilitation, avant={"groupe": self.dn}, apres={"motif": "groupe supprimé"})
        return super().delete(*args, **kwargs)  # type: ignore[arg-type]
