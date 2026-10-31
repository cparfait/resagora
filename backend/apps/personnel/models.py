"""Personnel des équipements (PER-01 à PER-09, RG-09, RG-10) et application mobile des gardiens (MOB-01 à MOB-08).

- Un **besoin** naît des séances validées ou confirmées d'un espace gardienné, élargies des temps d'ouverture et
  de fermeture, et fusionnées par site (REF-04, PER-02).
- Une **vacation** affecte un agent (ou reste à pourvoir) ; deux vacations d'un même agent ne se chevauchent jamais :
  la base le garantit (RG-10, contrainte d'exclusion).
- Les **saisies mobiles** (pointage, état des lieux, incident) portent un identifiant généré sur l'appareil : une
  saisie reçue deux fois n'est enregistrée qu'une fois (MOB-05) ; une saisie sur une séance annulée entre-temps est
  conservée et signalée (MOB-06).
"""

from __future__ import annotations

from django.conf import settings
from django.contrib.postgres.constraints import ExclusionConstraint
from django.contrib.postgres.fields import DateTimeRangeField, RangeOperators
from django.db import models
from django.db.models import Q
from django.db.models.functions import Lower


class Agent(models.Model):
    """Fiche d'un agent d'équipement ou gardien (PER-01) ; le compte AD sert à l'application mobile."""

    utilisateur = models.OneToOneField(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name="agent_equipement"
    )
    matricule = models.CharField(max_length=20, unique=True)
    identifiant_ad = models.CharField(
        "identifiant de l'annuaire",
        max_length=150,
        blank=True,
        default="",
        help_text="Rattache la fiche au compte de l'annuaire à la première connexion (sAMAccountName).",
    )
    prenom = models.CharField(max_length=100)
    nom = models.CharField(max_length=100)
    courriel = models.EmailField(blank=True, default="")
    telephone = models.CharField(max_length=20, blank=True, default="")
    sites = models.ManyToManyField(
        "referentiel.Site", related_name="agents_affectables", help_text="Sites où l'agent peut être affecté."
    )
    site_prefere = models.ForeignKey("referentiel.Site", null=True, blank=True, on_delete=models.SET_NULL, related_name="+")
    duree_hebdo_minutes = models.PositiveIntegerField("durée hebdomadaire de référence (minutes)", default=35 * 60)
    actif = models.BooleanField(default=True)
    cree_le = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["nom", "prenom"]
        constraints = [
            models.UniqueConstraint(
                Lower("identifiant_ad"),
                condition=~models.Q(identifiant_ad=""),
                name="agent_identifiant_ad_unique",
            )
        ]

    def __str__(self) -> str:
        return f"{self.prenom} {self.nom}"

    def sites_concernes(self) -> set[int] | None:
        return set(self.sites.values_list("pk", flat=True)) or None


class TypeHabilitation(models.Model):
    """SSIAP 1, SSIAP 2, PSC1, habilitation électrique… ; certaines sont exigées pour garder un site."""

    code = models.SlugField(max_length=30, unique=True)
    libelle = models.CharField(max_length=120)
    exigee_pour_gardiennage = models.BooleanField(default=False, help_text="Un besoin de gardiennage exige cette habilitation.")

    class Meta:
        ordering = ["libelle"]

    def __str__(self) -> str:
        return self.libelle

    def sites_concernes(self) -> None:
        return None


class HabilitationAgent(models.Model):
    agent = models.ForeignKey(Agent, on_delete=models.CASCADE, related_name="habilitations")
    type = models.ForeignKey(TypeHabilitation, on_delete=models.PROTECT, related_name="+")
    obtenue_le = models.DateField()
    valide_jusqu_au = models.DateField(null=True, blank=True, help_text="Vide : sans limite de validité.")
    justificatif = models.ForeignKey("noyau.Fichier", null=True, blank=True, on_delete=models.PROTECT, related_name="+")

    class Meta:
        ordering = ["agent", "type"]

    def __str__(self) -> str:
        return f"{self.agent} — {self.type}"

    def sites_concernes(self) -> set[int] | None:
        return self.agent.sites_concernes()


class Besoin(models.Model):
    """Plage de présence exigée sur un site, issue des séances gardiennées (PER-02)."""

    STATUTS = [("a_couvrir", "À couvrir"), ("couvert", "Couvert"), ("supprime", "Supprimé (séances annulées)")]
    site = models.ForeignKey("referentiel.Site", on_delete=models.PROTECT, related_name="besoins_personnel")
    debut = models.DateTimeField()
    fin = models.DateTimeField()
    occurrences = models.ManyToManyField("reservations.Occurrence", related_name="besoins_personnel")
    statut = models.CharField(max_length=10, choices=STATUTS, default="a_couvrir")
    jour = models.DateField(
        null=True, help_text="Jour des séances qui fondent le besoin (Europe/Paris) : la plage peut déborder sur la veille."
    )
    modifie_le = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["debut"]
        indexes = [models.Index(fields=["site", "debut"]), models.Index(fields=["site", "jour"])]

    def __str__(self) -> str:
        return f"Besoin {self.site} {self.debut:%d/%m %H:%M}"

    def sites_concernes(self) -> set[int]:
        return {self.site_id}


class Trame(models.Model):
    """Semaine type d'un site pour une saison (PER-03)."""

    nom = models.CharField(max_length=120)
    saison = models.ForeignKey("referentiel.Saison", on_delete=models.PROTECT, related_name="trames")
    site = models.ForeignKey("referentiel.Site", on_delete=models.PROTECT, related_name="trames")
    appliquee_le = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["saison", "site", "nom"]

    def __str__(self) -> str:
        return self.nom

    def sites_concernes(self) -> set[int]:
        return {self.site_id}


TYPES_VACATION = [("normale", "Normale"), ("supplementaire", "Heures supplémentaires"), ("astreinte", "Astreinte")]


class LigneTrame(models.Model):
    JOURS = [(0, "Lundi"), (1, "Mardi"), (2, "Mercredi"), (3, "Jeudi"), (4, "Vendredi"), (5, "Samedi"), (6, "Dimanche")]
    trame = models.ForeignKey(Trame, on_delete=models.CASCADE, related_name="lignes")
    jour = models.PositiveSmallIntegerField(choices=JOURS)
    heure_debut = models.TimeField()
    heure_fin = models.TimeField()
    agent = models.ForeignKey(Agent, null=True, blank=True, on_delete=models.SET_NULL, related_name="+")
    type = models.CharField(max_length=15, choices=TYPES_VACATION, default="normale")

    class Meta:
        ordering = ["trame", "jour", "heure_debut"]

    def __str__(self) -> str:
        return f"{self.get_jour_display()} {self.heure_debut:%H:%M}-{self.heure_fin:%H:%M}"

    def sites_concernes(self) -> set[int]:
        return {self.trame.site_id}


class Vacation(models.Model):
    STATUTS = [
        ("planifiee", "Planifiée"),
        ("a_pourvoir", "À pourvoir"),
        ("a_revoir", "À revoir (réservations modifiées)"),
        ("annulee", "Annulée"),
    ]
    site = models.ForeignKey("referentiel.Site", on_delete=models.PROTECT, related_name="vacations")
    agent = models.ForeignKey(Agent, null=True, blank=True, on_delete=models.PROTECT, related_name="vacations")
    debut = models.DateTimeField()
    fin = models.DateTimeField()
    plage = DateTimeRangeField(editable=False)
    type = models.CharField(max_length=15, choices=TYPES_VACATION, default="normale")
    statut = models.CharField(max_length=12, choices=STATUTS, default="a_pourvoir")
    besoins = models.ManyToManyField(Besoin, blank=True, related_name="vacations")
    trame = models.ForeignKey(Trame, null=True, blank=True, on_delete=models.SET_NULL, related_name="vacations")
    violations = models.JSONField(default=list, blank=True, help_text="Règles de temps de travail non respectées (PER-05).")
    forcee = models.BooleanField(default=False)
    motif_forcage = models.CharField(max_length=300, blank=True, default="")
    arrivee_reelle = models.DateTimeField(null=True, blank=True, help_text="Pointage (MOB-02).")
    depart_reel = models.DateTimeField(null=True, blank=True)
    signalement = models.CharField(max_length=300, blank=True, default="")
    cree_le = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["debut"]
        constraints = [
            models.CheckConstraint(condition=Q(fin__gt=models.F("debut")), name="vacation_dates"),
            ExclusionConstraint(
                name="rg10_pas_de_chevauchement_agent",
                expressions=[("agent", RangeOperators.EQUAL), ("plage", RangeOperators.OVERLAPS)],
                condition=Q(agent__isnull=False) & ~Q(statut="annulee"),
            ),
        ]
        indexes = [models.Index(fields=["site", "debut"]), models.Index(fields=["agent", "debut"])]

    def __str__(self) -> str:
        return f"Vacation {self.site} {self.debut:%d/%m %H:%M}"

    def save(self, *args: object, **kwargs: object) -> None:
        from django.db.backends.postgresql.psycopg_any import DateTimeTZRange

        self.plage = DateTimeTZRange(self.debut, self.fin, "[)")
        if kwargs.get("update_fields") is not None:
            kwargs["update_fields"] = {*kwargs["update_fields"], "plage"}  # type: ignore[misc]
        super().save(*args, **kwargs)  # type: ignore[arg-type]

    def sites_concernes(self) -> set[int]:
        return {self.site_id}

    @property
    def duree_minutes(self) -> int:
        return int((self.fin - self.debut).total_seconds() // 60)


class Absence(models.Model):
    NATURES = [("conge", "Congé"), ("maladie", "Arrêt maladie"), ("formation", "Formation"), ("autre", "Autre absence")]
    agent = models.ForeignKey(Agent, on_delete=models.CASCADE, related_name="absences")
    debut = models.DateTimeField()
    fin = models.DateTimeField()
    nature = models.CharField(max_length=10, choices=NATURES)
    commentaire = models.CharField(max_length=250, blank=True, default="")
    cree_par = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, on_delete=models.SET_NULL, related_name="+")
    cree_le = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-debut"]
        constraints = [models.CheckConstraint(condition=Q(fin__gt=models.F("debut")), name="absence_dates")]

    def __str__(self) -> str:
        return f"{self.agent} absent du {self.debut:%d/%m}"

    def sites_concernes(self) -> set[int] | None:
        return self.agent.sites_concernes()


class Incident(models.Model):
    """PER-09, MOB-04 : incident rattaché à la séance et à l'usager, saisi au back-office ou sur le mobile."""

    GRAVITES = [("mineur", "Mineur"), ("majeur", "Majeur"), ("securite", "Sécurité des personnes")]
    NATURES = [
        ("degradation", "Dégradation"),
        ("comportement", "Comportement"),
        ("accident", "Accident ou blessure"),
        ("technique", "Problème technique"),
        ("absence_usager", "Usager absent"),
        ("autre", "Autre"),
    ]
    site = models.ForeignKey("referentiel.Site", on_delete=models.PROTECT, related_name="incidents")
    espace = models.ForeignKey("referentiel.Espace", null=True, blank=True, on_delete=models.PROTECT, related_name="incidents")
    occurrence = models.ForeignKey(
        "reservations.Occurrence", null=True, blank=True, on_delete=models.PROTECT, related_name="incidents"
    )
    usager = models.ForeignKey("usagers.Usager", null=True, blank=True, on_delete=models.PROTECT, related_name="incidents")
    nature = models.CharField(max_length=15, choices=NATURES)
    gravite = models.CharField(max_length=10, choices=GRAVITES, default="mineur")
    description = models.TextField(max_length=4000)
    photos = models.ManyToManyField("noyau.Fichier", blank=True, related_name="+")
    constate_le = models.DateTimeField()
    signale_par = models.ForeignKey(Agent, null=True, blank=True, on_delete=models.SET_NULL, related_name="incidents_signales")
    source = models.CharField(max_length=10, choices=[("mobile", "Application mobile"), ("backoffice", "Back-office")])
    traite = models.BooleanField(default=False)
    suite_donnee = models.TextField(blank=True, default="")
    cree_le = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-constate_le"]

    def __str__(self) -> str:
        return f"Incident {self.get_nature_display()} — {self.site}"

    def sites_concernes(self) -> set[int]:
        return {self.site_id}


class JetonIcal(models.Model):
    """PER-08 : abonnement iCal personnel, révocable ; seule l'empreinte du jeton est conservée."""

    agent = models.ForeignKey(Agent, on_delete=models.CASCADE, related_name="jetons_ical")
    empreinte = models.CharField(max_length=64, unique=True)
    cree_le = models.DateTimeField(auto_now_add=True)
    revoque_le = models.DateTimeField(null=True, blank=True)
    dernier_acces = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["-cree_le"]

    def __str__(self) -> str:
        return f"Abonnement iCal de {self.agent}"

    def sites_concernes(self) -> set[int] | None:
        return self.agent.sites_concernes()


class Appareil(models.Model):
    """Smartphone d'un gardien. Option B (SEC-10) : certificat d'appareil enregistré, vérifié à chaque appel."""

    agent = models.ForeignKey(Agent, on_delete=models.CASCADE, related_name="appareils")
    libelle = models.CharField(max_length=120)
    identifiant = models.UUIDField(
        null=True, blank=True, help_text="Identifiant aléatoire tiré par l'application à sa première connexion (option A)."
    )
    a_autoriser = models.BooleanField(
        default=False, help_text="Nouvel appareil d'un agent dont un appareil a été retiré : à autoriser par le planificateur."
    )
    empreinte_certificat = models.CharField(
        max_length=64, blank=True, default="", help_text="SHA-256 du certificat d'appareil (option B, accès par la DMZ)."
    )
    actif = models.BooleanField(default=True)
    enregistre_le = models.DateTimeField(auto_now_add=True)
    revoque_le = models.DateTimeField(null=True, blank=True)
    derniere_synchronisation = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["agent", "libelle"]
        constraints = [
            models.UniqueConstraint(
                fields=["empreinte_certificat"], condition=~Q(empreinte_certificat=""), name="certificat_appareil_unique"
            ),
            models.UniqueConstraint(
                fields=["agent", "identifiant"], condition=Q(identifiant__isnull=False), name="appareil_identifiant_unique"
            ),
        ]

    def __str__(self) -> str:
        return f"{self.libelle} ({self.agent})"

    def sites_concernes(self) -> set[int] | None:
        return self.agent.sites_concernes()


class JetonMobile(models.Model):
    """Session de l'application mobile (en-tête « Authorization: Appareil <jeton> ») ; empreinte seule conservée."""

    agent = models.ForeignKey(Agent, on_delete=models.CASCADE, related_name="jetons_mobiles")
    appareil = models.ForeignKey(Appareil, null=True, blank=True, on_delete=models.CASCADE, related_name="jetons")
    empreinte = models.CharField(max_length=64, unique=True)
    expire_le = models.DateTimeField()
    revoque_le = models.DateTimeField(null=True, blank=True)
    cree_le = models.DateTimeField(auto_now_add=True)
    dernier_usage = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["-cree_le"]

    def __str__(self) -> str:
        return f"Session mobile de {self.agent}"


class SaisieMobile(models.Model):
    """Journal des saisies reçues de l'application (MOB-05, MOB-06) : jamais écrasées, toujours ajoutées."""

    TYPES = [("pointage", "Pointage"), ("etat_des_lieux", "État des lieux"), ("incident", "Incident")]
    STATUTS = [("acceptee", "Acceptée"), ("conflit", "Conservée et signalée (conflit)"), ("rejetee", "Rejetée")]
    uuid = models.UUIDField(unique=True)
    agent = models.ForeignKey(Agent, on_delete=models.PROTECT, related_name="saisies_mobiles")
    appareil = models.CharField(max_length=120, blank=True, default="")
    type = models.CharField(max_length=15, choices=TYPES)
    horodatage_appareil = models.DateTimeField()
    donnees = models.JSONField(default=dict)
    statut = models.CharField(max_length=10, choices=STATUTS)
    message = models.CharField(max_length=300, blank=True, default="")
    recue_le = models.DateTimeField(auto_now_add=True)
    traitee_par = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name="+")

    class Meta:
        ordering = ["-recue_le"]

    def __str__(self) -> str:
        return f"Saisie {self.get_type_display()} {self.uuid}"

    def sites_concernes(self) -> set[int] | None:
        return self.agent.sites_concernes()


class PhotoMobile(models.Model):
    """Photo envoyée par l'application avant les saisies qui la citent (identifiant généré sur l'appareil)."""

    uuid = models.UUIDField(unique=True)
    agent = models.ForeignKey(Agent, on_delete=models.PROTECT, related_name="+")
    fichier = models.ForeignKey("noyau.Fichier", on_delete=models.PROTECT, related_name="+")
    recue_le = models.DateTimeField(auto_now_add=True)

    def __str__(self) -> str:
        return f"Photo {self.uuid}"
