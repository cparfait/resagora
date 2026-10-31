"""Modèles de messages et notifications électroniques (COM-01, COM-04, ADM-04)."""

from __future__ import annotations

from django.db import models


class ModeleMessage(models.Model):
    """Modèle de courriel éditable par l'administration ; gabarit Django (`{{ usager.nom }}`)."""

    code = models.SlugField(max_length=60, unique=True)
    libelle = models.CharField(max_length=150)
    sujet = models.CharField(max_length=200)
    corps = models.TextField(help_text="Texte du message ; variables entre doubles accolades.")
    actif = models.BooleanField(default=True)
    modifie_le = models.DateTimeField(auto_now=True)

    ecriture_ville_entiere = True

    class Meta:
        ordering = ["libelle"]

    def __str__(self) -> str:
        return self.libelle

    def sites_concernes(self) -> None:
        return None


class Notification(models.Model):
    CANAUX = [("courriel", "Courriel"), ("sms", "SMS"), ("portail", "Portail")]
    STATUTS = [("a_envoyer", "À envoyer"), ("envoyee", "Envoyée"), ("echec", "Échec"), ("ignoree", "Ignorée (préférences)")]

    canal = models.CharField(max_length=10, choices=CANAUX, default="courriel")
    modele = models.ForeignKey(ModeleMessage, null=True, blank=True, on_delete=models.SET_NULL, related_name="notifications")
    destinataire = models.CharField(max_length=254)
    contact = models.ForeignKey("usagers.Contact", null=True, blank=True, on_delete=models.SET_NULL, related_name="notifications")
    usager = models.ForeignKey("usagers.Usager", null=True, blank=True, on_delete=models.SET_NULL, related_name="notifications")
    agent = models.ForeignKey("habilitations.Utilisateur", null=True, blank=True, on_delete=models.SET_NULL, related_name="notifications")
    sujet = models.CharField(max_length=250)
    corps = models.TextField()
    objet_type = models.CharField(max_length=80, blank=True, default="")
    objet_id = models.CharField(max_length=64, blank=True, default="")
    groupe = models.CharField(max_length=64, blank=True, default="", help_text="Identifiant d'un envoi groupé.")
    statut = models.CharField(max_length=10, choices=STATUTS, default="a_envoyer")
    tentatives = models.PositiveSmallIntegerField(default=0)
    erreur = models.CharField(max_length=300, blank=True, default="")
    cree_le = models.DateTimeField(auto_now_add=True)
    envoyee_le = models.DateTimeField(null=True, blank=True)
    lue_le = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["-cree_le"]
        indexes = [models.Index(fields=["statut", "cree_le"]), models.Index(fields=["objet_type", "objet_id"])]

    def __str__(self) -> str:
        return f"{self.sujet} → {self.destinataire}"

    def sites_concernes(self) -> None:
        return None
