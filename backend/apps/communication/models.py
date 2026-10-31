"""Modèles de messages, notifications, messagerie par dossier et préférences (COM-01 à COM-05, ADM-04)."""

from __future__ import annotations

from django.db import models


class ModeleMessage(models.Model):
    """Modèle de courriel éditable par l'administration ; gabarit Django (`{{ usager.nom }}`)."""

    code = models.SlugField(max_length=60, unique=True)
    libelle = models.CharField(max_length=150)
    sujet = models.CharField(max_length=200)
    corps = models.TextField(help_text="Texte du message ; variables entre doubles accolades.")
    sms = models.CharField(
        "texte du SMS", max_length=320, blank=True, default="", help_text="Vide : pas de SMS pour ce message (COM-05)."
    )
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
    agent = models.ForeignKey(
        "habilitations.Utilisateur", null=True, blank=True, on_delete=models.SET_NULL, related_name="notifications"
    )
    sujet = models.CharField(max_length=250)
    corps = models.TextField(help_text="Texte conservé ; les liens à usage unique y sont masqués.")
    corps_secret = models.TextField(
        blank=True, default="", help_text="Texte complet chiffré, effacé dès l'envoi (liens de confirmation, réinitialisation)."
    )
    objet_type = models.CharField(max_length=80, blank=True, default="")
    objet_id = models.CharField(max_length=64, blank=True, default="")
    groupe = models.CharField(max_length=64, blank=True, default="", help_text="Identifiant d'un envoi groupé.")
    piece_jointe = models.ForeignKey(
        "noyau.Fichier",
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name="+",
        help_text="Planning programmé (IMP-04).",
    )
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


class Message(models.Model):
    """Message échangé entre la Ville et un usager, rattaché à un dossier (COM-02, POR-08)."""

    dossier = models.ForeignKey("reservations.Dossier", on_delete=models.CASCADE, related_name="messages")
    auteur_agent = models.ForeignKey(
        "habilitations.Utilisateur", null=True, blank=True, on_delete=models.SET_NULL, related_name="messages"
    )
    auteur_contact = models.ForeignKey(
        "usagers.Contact", null=True, blank=True, on_delete=models.SET_NULL, related_name="messages"
    )
    corps = models.TextField(max_length=5000)
    piece_jointe = models.ForeignKey("noyau.Fichier", null=True, blank=True, on_delete=models.PROTECT, related_name="+")
    cree_le = models.DateTimeField(auto_now_add=True)
    lu_par_ville_le = models.DateTimeField(null=True, blank=True)
    lu_par_usager_le = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["cree_le"]
        constraints = [
            models.CheckConstraint(
                condition=models.Q(auteur_agent__isnull=True) | models.Q(auteur_contact__isnull=True),
                name="message_un_seul_auteur",
            )
        ]

    def __str__(self) -> str:
        return f"Message {self.pk} — dossier {self.dossier_id}"

    def sites_concernes(self) -> set[int] | None:
        return self.dossier.sites_concernes()

    @property
    def de_la_ville(self) -> bool:
        return self.auteur_contact_id is None


class PreferenceNotification(models.Model):
    """Préférences d'un contact (COM-04) ; les messages transactionnels partent toujours par courriel."""

    contact = models.OneToOneField("usagers.Contact", on_delete=models.CASCADE, related_name="preferences")
    sms = models.BooleanField("recevoir aussi les SMS (rappels, fermetures)", default=False)
    telephone_sms = models.CharField(max_length=20, blank=True, default="")
    telephone_verifie = models.CharField(
        max_length=20, blank=True, default="", help_text="Numéro confirmé par le code reçu par SMS : seul destinataire possible."
    )
    rappels = models.BooleanField("rappel la veille des séances", default=False)
    informations = models.BooleanField("informations générales de la Ville", default=True)
    modifie_le = models.DateTimeField(auto_now=True)

    def __str__(self) -> str:
        return f"Préférences de {self.contact}"

    @property
    def sms_possible(self) -> bool:
        """COM-05 : accord du contact et numéro vérifié par un code (personne ne reçoit de SMS sans l'avoir confirmé)."""
        return self.sms and bool(self.telephone_sms) and self.telephone_sms == self.telephone_verifie

    def sites_concernes(self) -> None:
        return None
