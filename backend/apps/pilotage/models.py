"""Pilotage : envoi programmé des plannings (IMP-04)."""

from __future__ import annotations

from datetime import time

from django.conf import settings
from django.contrib.postgres.fields import ArrayField
from django.db import models
from django.db.models import Q


class EnvoiProgramme(models.Model):
    """Planning de la semaine suivante envoyé chaque semaine (jour, heure de Paris) à une liste d'adresses."""

    JOURS = [(0, "lundi"), (1, "mardi"), (2, "mercredi"), (3, "jeudi"), (4, "vendredi"), (5, "samedi"), (6, "dimanche")]
    libelle = models.CharField(max_length=150)
    site = models.ForeignKey("referentiel.Site", null=True, blank=True, on_delete=models.CASCADE, related_name="envois_planning")
    espace = models.ForeignKey(
        "referentiel.Espace", null=True, blank=True, on_delete=models.CASCADE, related_name="envois_planning"
    )
    destinataires = ArrayField(models.EmailField(), size=30, help_text="Adresses professionnelles (30 au plus).")
    jour_semaine = models.PositiveSmallIntegerField(choices=JOURS, default=4)
    heure = models.TimeField(default=time(16, 0))
    format_papier = models.CharField(max_length=2, choices=[("A4", "A4"), ("A3", "A3")], default="A4")
    actif = models.BooleanField(default=True)
    prochain_envoi_le = models.DateTimeField(null=True, blank=True)
    dernier_envoi_le = models.DateTimeField(null=True, blank=True)
    echecs = models.PositiveSmallIntegerField(default=0, help_text="Échecs consécutifs ; l'envoi se suspend au 5e.")
    suspendu_motif = models.CharField(max_length=250, blank=True, default="")
    cree_par = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.PROTECT, related_name="+")
    cree_le = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["libelle"]
        constraints = [
            models.CheckConstraint(
                condition=(Q(site__isnull=False) & Q(espace__isnull=True)) | (Q(site__isnull=True) & Q(espace__isnull=False)),
                name="envoi_planning_site_ou_espace",
            )
        ]

    def __str__(self) -> str:
        return self.libelle

    def sites_concernes(self) -> set[int]:
        if self.espace_id and self.espace is not None:
            return {self.espace.batiment.site_id}
        return {self.site_id} if self.site_id else set()
