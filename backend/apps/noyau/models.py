"""Modèles transverses : paramètres fonctionnels (ADM-02) et fichiers stockés (SEC-07, DOC-07)."""

from __future__ import annotations

from django.conf import settings
from django.db import models


class Parametre(models.Model):
    cle = models.CharField(max_length=80, unique=True)
    valeur = models.JSONField()
    modifie_par = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, on_delete=models.SET_NULL, related_name="+")
    modifie_le = models.DateTimeField(auto_now=True)

    ecriture_ville_entiere = True

    class Meta:
        ordering = ["cle"]

    def __str__(self) -> str:
        return self.cle

    def sites_concernes(self) -> None:
        return None


class Fichier(models.Model):
    """Fichier stocké hors racine web sous un nom aléatoire, avec empreinte SHA-256 (SEC-07)."""

    nom_origine = models.CharField(max_length=200)
    type_mime = models.CharField(max_length=100)
    taille = models.PositiveIntegerField()
    sha256 = models.CharField(max_length=64, db_index=True)
    chemin = models.CharField(max_length=200, unique=True)
    controle_antivirus = models.CharField(max_length=30, default="")
    depose_le = models.DateTimeField(auto_now_add=True)
    depose_par = models.CharField(max_length=200, blank=True, default="")

    class Meta:
        ordering = ["-depose_le"]

    def __str__(self) -> str:
        return self.nom_origine
