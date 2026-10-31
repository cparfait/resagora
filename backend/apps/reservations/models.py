"""Dossiers, réservations, occurrences et verrous d'occupation (PLA-04, PLA-06, RG-01, RG-02, REF-05, REF-07).

- Un **dossier** regroupe la demande d'un usager ; il contient des **réservations** (espace +
  récurrence RRULE + période) dont les **occurrences** datées portent conflits, présence et facturation.
- Une occurrence bloquante (validée, confirmée, réalisée, clôturée) pose un **verrou** par espace
  *feuille* couvert : réserver le gymnase entier verrouille ses tiers, réserver un tiers ne verrouille
  que lui. La contrainte d'exclusion PostgreSQL interdit deux verrous exclusifs qui se chevauchent sur
  la même feuille (RG-01), même si deux agents valident en même temps. Les demandes et options ne
  posent aucun verrou (RG-02). Les espaces partageables (REF-07) posent des verrous « partagés »,
  comptés par le service dans la limite de leur capacité simultanée.
"""

from __future__ import annotations

from django.conf import settings
from django.contrib.postgres.constraints import ExclusionConstraint
from django.contrib.postgres.fields import ArrayField, DateTimeRangeField, RangeOperators
from django.db import models
from django.db.models import Q

STATUTS = [
    ("demande", "Demande"),
    ("en_instruction", "En instruction"),
    ("option", "Option"),
    ("validee", "Validée"),
    ("confirmee", "Confirmée"),
    ("realisee", "Réalisée"),
    ("cloturee", "Clôturée"),
    ("refusee", "Refusée"),
    ("annulee", "Annulée"),
]
STATUTS_BLOQUANTS = frozenset({"validee", "confirmee", "realisee", "cloturee"})
STATUTS_ACTIFS = frozenset({"demande", "en_instruction", "option", "validee", "confirmee"})
PRESENCES = [("present", "Présent"), ("absent_signale", "Absence signalée"), ("absent_non_signale", "Absence non signalée")]


class TypeReservation(models.Model):
    """Nature de la réservation et conditions de confirmation exigées (RG-06), paramétrables."""

    code = models.SlugField(max_length=40, unique=True)
    libelle = models.CharField(max_length=120)
    exige_pieces = models.BooleanField("pièces justificatives valides", default=True)
    exige_convention = models.BooleanField("convention ou contrat signé", default=False)
    exige_acompte = models.BooleanField("acompte payé", default=False)
    exige_caution = models.BooleanField("caution reçue", default=False)
    ouvert_portail = models.BooleanField("demandable sur le portail", default=True)
    types_usager = ArrayField(
        models.CharField(max_length=20), default=list, blank=True, help_text="Vide : tous les types d'usagers (portail)."
    )
    ordre = models.PositiveSmallIntegerField(default=0)

    ecriture_ville_entiere = True

    class Meta:
        ordering = ["ordre", "libelle"]

    def __str__(self) -> str:
        return self.libelle

    def sites_concernes(self) -> None:
        return None


class Campagne(models.Model):
    """Campagne annuelle d'attribution des créneaux (PLA-05)."""

    STATUTS = [
        ("preparation", "En préparation"),
        ("ouverte", "Ouverte aux demandes"),
        ("instruction", "En instruction"),
        ("commission", "En commission"),
        ("attribuee", "Attribuée"),
        ("close", "Close"),
    ]
    saison = models.ForeignKey("referentiel.Saison", on_delete=models.PROTECT, related_name="campagnes")
    nom = models.CharField(max_length=150)
    ouverture = models.DateField()
    cloture = models.DateField()
    date_commission = models.DateField(null=True, blank=True)
    statut = models.CharField(max_length=12, choices=STATUTS, default="preparation")
    sites = models.ManyToManyField("referentiel.Site", blank=True, related_name="campagnes", help_text="Vide : tous les sites.")

    class Meta:
        ordering = ["-ouverture"]
        constraints = [models.CheckConstraint(condition=Q(cloture__gte=models.F("ouverture")), name="campagne_dates")]

    def __str__(self) -> str:
        return self.nom

    def sites_concernes(self) -> set[int] | None:
        sites = {s.pk for s in self.sites.all()} if self.pk else set()
        return sites or None

    @property
    def ecriture_ville_entiere(self) -> bool:
        """Une campagne « tous sites » ne se gère qu'avec un périmètre ville entière (RG-14)."""
        return not self.pk or not self.sites.exists()


class Dossier(models.Model):
    ORIGINES = [("guichet", "Guichet"), ("portail", "Portail"), ("campagne", "Campagne annuelle"), ("ville", "Service municipal")]
    numero = models.CharField(max_length=20, unique=True)
    usager = models.ForeignKey("usagers.Usager", on_delete=models.PROTECT, related_name="dossiers")
    contact = models.ForeignKey("usagers.Contact", null=True, blank=True, on_delete=models.SET_NULL, related_name="dossiers")
    type_reservation = models.ForeignKey(TypeReservation, on_delete=models.PROTECT, related_name="dossiers")
    objet = models.CharField(max_length=250)
    activite = models.CharField(max_length=150, blank=True, default="")
    effectif = models.PositiveIntegerField(default=0)
    saison = models.ForeignKey("referentiel.Saison", null=True, blank=True, on_delete=models.PROTECT, related_name="dossiers")
    campagne = models.ForeignKey(Campagne, null=True, blank=True, on_delete=models.PROTECT, related_name="dossiers")
    origine = models.CharField(max_length=10, choices=ORIGINES, default="guichet")
    observations = models.TextField(blank=True, default="")
    brouillon = models.BooleanField(default=False, help_text="Demande du portail en cours de saisie (POR-04).")
    brouillon_creneaux = models.JSONField(
        default=list, blank=True, help_text="Créneaux saisis sur le portail, matérialisés à l'envoi de la demande (POR-04)."
    )
    brouillon_etape = models.PositiveSmallIntegerField(default=1)
    brouillon_materiel = models.JSONField(
        default=list, blank=True, help_text="Matériel demandé sur le portail (étape 2), prêts créés à l'envoi (MAT-02)."
    )
    conditions_attestees = models.JSONField(
        default=dict,
        blank=True,
        help_text="RG-06 : conditions constatées hors application (ex. caution remise au guichet), avec agent, date et motif.",
    )
    cree_par = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name="+")
    cree_le = models.DateTimeField(auto_now_add=True)
    depose_le = models.DateTimeField(null=True, blank=True)
    modifie_le = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-cree_le"]

    def __str__(self) -> str:
        return f"{self.numero} — {self.objet}"

    def sites_concernes(self) -> set[int] | None:
        """Sites de ses réservations ; un dossier encore vide est rattaché à son seul créateur (filtre des listes)."""
        sites = {s for s in self.reservations.values_list("espace__batiment__site_id", flat=True) if s is not None}
        return sites or None

    @property
    def statut(self) -> str:
        """Statut le plus avancé parmi les réservations actives (ou le statut commun s'il n'en reste pas)."""
        ordre = [s for s, _ in STATUTS]
        statuts = [r.statut for r in self.reservations.all()]
        if not statuts:
            return "demande"
        actifs = [s for s in statuts if s not in {"annulee", "refusee"}]
        return max(actifs or statuts, key=ordre.index)


class Reservation(models.Model):
    dossier = models.ForeignKey(Dossier, on_delete=models.CASCADE, related_name="reservations")
    espace = models.ForeignKey("referentiel.Espace", on_delete=models.PROTECT, related_name="reservations")
    statut = models.CharField(max_length=15, choices=STATUTS, default="demande")
    recurrence = models.CharField("règle de récurrence (RFC 5545)", max_length=200, blank=True, default="")
    date_debut = models.DateField()
    date_fin = models.DateField()
    heure_debut = models.TimeField()
    heure_fin = models.TimeField()
    exclure_vacances = models.BooleanField(default=True)
    exclure_feries = models.BooleanField(default=True)
    exdates = ArrayField(models.DateField(), default=list, blank=True)
    option_expire_le = models.DateTimeField(null=True, blank=True)
    option_relancee_le = models.DateTimeField(null=True, blank=True)
    motif_refus = models.CharField(max_length=300, blank=True, default="")
    motif_annulation = models.CharField(max_length=300, blank=True, default="")
    annulee_le = models.DateTimeField(null=True, blank=True)
    annulee_par_usager = models.BooleanField(default=False)
    valide_par = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name="+")
    valide_le = models.DateTimeField(null=True, blank=True)
    confirme_le = models.DateTimeField(null=True, blank=True)
    cree_le = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["date_debut", "heure_debut"]
        constraints = [
            models.CheckConstraint(condition=Q(date_fin__gte=models.F("date_debut")), name="reservation_dates"),
            models.CheckConstraint(condition=~Q(heure_fin=models.F("heure_debut")), name="reservation_heures"),
        ]

    def __str__(self) -> str:
        return f"{self.espace} — {self.description}"

    def sites_concernes(self) -> set[int]:
        return self.espace.sites_concernes()

    @property
    def description(self) -> str:
        """Récurrence lisible : « tous les mardis de 18 h à 20 h, hors vacances scolaires » (DOC-03)."""
        from .recurrence import decrire

        return decrire(self)


class Occurrence(models.Model):
    reservation = models.ForeignKey(Reservation, on_delete=models.CASCADE, related_name="occurrences")
    espace = models.ForeignKey("referentiel.Espace", on_delete=models.PROTECT, related_name="occurrences")
    debut = models.DateTimeField(db_index=True)
    fin = models.DateTimeField()
    statut = models.CharField(max_length=15, choices=STATUTS, default="demande")
    annulee_le = models.DateTimeField(null=True, blank=True)
    motif_annulation = models.CharField(max_length=300, blank=True, default="")
    annulation_tardive = models.BooleanField(default=False)
    annulee_par_usager = models.BooleanField(default=False)
    presence = models.CharField(max_length=20, choices=PRESENCES, blank=True, default="")
    debut_reel = models.DateTimeField(null=True, blank=True)
    fin_reel = models.DateTimeField(null=True, blank=True)
    signalement = models.CharField(max_length=300, blank=True, default="", help_text="Fermeture ou conflit à traiter (REF-06).")
    debut_origine = models.DateTimeField(null=True, blank=True, help_text="Avant déplacement.")
    espace_origine = models.ForeignKey("referentiel.Espace", null=True, blank=True, on_delete=models.SET_NULL, related_name="+")
    modifiee_individuellement = models.BooleanField(default=False)

    class Meta:
        ordering = ["debut"]
        indexes = [models.Index(fields=["espace", "debut"]), models.Index(fields=["statut", "debut"])]
        constraints = [models.CheckConstraint(condition=Q(fin__gt=models.F("debut")), name="occurrence_ordre")]

    def __str__(self) -> str:
        return f"{self.espace} {self.debut:%d/%m/%Y %H:%M}"

    def sites_concernes(self) -> set[int]:
        return self.espace.sites_concernes()

    @property
    def bloquante(self) -> bool:
        return self.statut in STATUTS_BLOQUANTS

    @property
    def duree_minutes(self) -> int:
        return int((self.fin - self.debut).total_seconds() // 60)


class Verrou(models.Model):
    """Occupation d'un espace feuille par une occurrence bloquante (RG-01)."""

    occurrence = models.ForeignKey(Occurrence, on_delete=models.CASCADE, related_name="verrous")
    feuille = models.ForeignKey("referentiel.Espace", on_delete=models.CASCADE, related_name="verrous")
    plage = DateTimeRangeField()
    partage = models.BooleanField(default=False)

    class Meta:
        constraints = [
            ExclusionConstraint(
                name="rg01_pas_de_chevauchement",
                expressions=[("feuille", RangeOperators.EQUAL), ("plage", RangeOperators.OVERLAPS)],
                condition=Q(partage=False),
            ),
            models.UniqueConstraint(fields=["occurrence", "feuille"], name="verrou_unique"),
        ]
        indexes = [models.Index(fields=["feuille"])]

    def __str__(self) -> str:
        return f"Verrou {self.feuille_id} {self.plage}"


class ListeAttente(models.Model):
    """Inscription en liste d'attente sur un créneau occupé (PLA-09)."""

    STATUTS = [
        ("attente", "En attente"),
        ("proposee", "Place proposée"),
        ("satisfaite", "Satisfaite"),
        ("abandonnee", "Abandonnée"),
    ]
    espace = models.ForeignKey("referentiel.Espace", on_delete=models.CASCADE, related_name="listes_attente")
    debut = models.DateTimeField()
    fin = models.DateTimeField()
    usager = models.ForeignKey("usagers.Usager", on_delete=models.CASCADE, related_name="listes_attente")
    contact = models.ForeignKey("usagers.Contact", null=True, blank=True, on_delete=models.SET_NULL, related_name="+")
    statut = models.CharField(max_length=12, choices=STATUTS, default="attente")
    cree_le = models.DateTimeField(auto_now_add=True)
    notifie_le = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["cree_le"]

    def __str__(self) -> str:
        return f"Attente {self.usager} — {self.espace} {self.debut:%d/%m %H:%M}"

    def sites_concernes(self) -> set[int]:
        return self.espace.sites_concernes()


class VueEnregistree(models.Model):
    """Vue du planning enregistrée par un agent : mode, filtres, coloration (PLA-03)."""

    MODES = [
        ("jour", "Jour"),
        ("semaine", "Semaine"),
        ("mois", "Mois"),
        ("chronologie", "Chronologie par espace"),
        ("multi_sites", "Occupation multi-sites"),
        ("liste", "Liste"),
    ]
    agent = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="vues_planning")
    nom = models.CharField(max_length=100)
    mode = models.CharField(max_length=15, choices=MODES, default="semaine")
    filtres = models.JSONField(default=dict, blank=True)
    coloration = models.CharField(
        max_length=15, choices=[("statut", "Par statut"), ("type_usager", "Par type d'usager")], default="statut"
    )
    par_defaut = models.BooleanField(default=False)

    class Meta:
        ordering = ["agent", "nom"]
        constraints = [models.UniqueConstraint(fields=["agent", "nom"], name="vue_unique_par_agent")]

    def __str__(self) -> str:
        return self.nom

    def sites_concernes(self) -> None:
        return None
