"""Journal d'audit chaîné par empreintes SHA-256 et protégé contre la modification (SEC-08, ADM-05)."""

from __future__ import annotations

from django.conf import settings
from django.db import models


class JournalAudit(models.Model):
    horodatage = models.DateTimeField(db_index=True)
    acteur = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.PROTECT, related_name="+")
    acteur_libelle = models.CharField(max_length=200, blank=True, default="")
    canal = models.CharField(max_length=20, blank=True, default="")
    action = models.CharField(max_length=80, db_index=True)
    objet_type = models.CharField(max_length=80, db_index=True, blank=True, default="")
    objet_id = models.CharField(max_length=64, db_index=True, blank=True, default="")
    objet_libelle = models.CharField(max_length=300, blank=True, default="")
    avant = models.JSONField(null=True, blank=True)
    apres = models.JSONField(null=True, blank=True)
    adresse_ip = models.GenericIPAddressField(null=True, blank=True)
    identifiant_requete = models.CharField(max_length=64, blank=True, default="")
    empreinte_precedente = models.CharField(max_length=64)
    empreinte = models.CharField(max_length=64, unique=True)

    class Meta:
        ordering = ["-id"]
        verbose_name = "entrée du journal d'audit"
        indexes = [models.Index(fields=["objet_type", "objet_id"])]

    def __str__(self) -> str:
        return f"{self.horodatage:%Y-%m-%d %H:%M} {self.acteur_libelle} {self.action} {self.objet_type}#{self.objet_id}"


class PointControleJournal(models.Model):
    """Trace immuable d'une purge : dernière entrée purgée, son empreinte et l'archive produite (SEC-08)."""

    cree_le = models.DateTimeField(auto_now_add=True)
    dernier_id = models.BigIntegerField(unique=True)
    empreinte = models.CharField(max_length=64)
    nombre = models.PositiveIntegerField()
    archive = models.CharField(max_length=300)
    archive_sha256 = models.CharField(max_length=64)

    class Meta:
        ordering = ["-dernier_id"]

    def __str__(self) -> str:
        return f"Purge jusqu'à l'entrée {self.dernier_id}"


class AncrageJournal(models.Model):
    """Ancrage horaire de la dernière empreinte (aussi écrit dans les journaux techniques)."""

    cree_le = models.DateTimeField(auto_now_add=True)
    dernier_id = models.BigIntegerField()
    empreinte = models.CharField(max_length=64)
    nombre = models.PositiveIntegerField()

    class Meta:
        ordering = ["-dernier_id"]

    def __str__(self) -> str:
        return f"Ancrage {self.dernier_id}"
