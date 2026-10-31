"""Matériel des équipements (lot 5) : catalogue (MAT-01), stocks par site et espace, réservations rattachées à un
dossier avec contrôle de disponibilité (MAT-02), mouvements de stock immuables (MAT-03), contrôles périodiques et
maintenance (MAT-04), pannes qui rendent le matériel indisponible (MAT-05)."""

from __future__ import annotations

from django.conf import settings
from django.db import models
from django.db.models import F, Q

NATURES = [
    ("fixe", "Équipement fixe d'un espace"),
    ("mobile", "Matériel mobile, prêté"),
    ("consommable", "Consommable"),
]


class Materiel(models.Model):
    """Article du catalogue (MAT-01). Le tarif de référence d'une journée sert à la valorisation des prêts gratuits
    (VAL-02) ; un prêt facturé passe par la prestation de la grille tarifaire désignée par son code."""

    code = models.SlugField(max_length=40, unique=True)
    libelle = models.CharField(max_length=150)
    nature = models.CharField(max_length=12, choices=NATURES, default="mobile")
    description = models.TextField(blank=True, default="")
    unite = models.CharField(max_length=30, default="unité")
    valeur_journaliere_centimes = models.PositiveIntegerField("valeur de référence d'une journée de prêt (centimes)", default=0)
    prestation_code = models.SlugField(
        max_length=40, blank=True, default="", help_text="Code de la prestation facturée (grille tarifaire), vide si gratuit."
    )
    reservable = models.BooleanField(default=True)
    propose_portail = models.BooleanField("proposé aux usagers sur le portail", default=False)
    periodicite_controle_jours = models.PositiveSmallIntegerField(
        "périodicité du contrôle (jours)", null=True, blank=True, help_text="Contrôle réglementaire ou de sécurité (MAT-04)."
    )
    seuil_alerte = models.PositiveIntegerField(null=True, blank=True, help_text="Consommables : alerte sous ce stock.")
    actif = models.BooleanField(default=True)
    cree_le = models.DateTimeField(auto_now_add=True)

    #: Référentiel commun : seul un périmètre « tous sites » le modifie (RG-14).
    ecriture_ville_entiere = True

    class Meta:
        ordering = ["libelle"]
        verbose_name = "matériel"

    def __str__(self) -> str:
        return self.libelle

    def sites_concernes(self) -> None:
        return None


class Stock(models.Model):
    """Quantité d'un matériel en un lieu : un site, et un espace pour le matériel fixe. `hors_service` compte les
    unités en panne ou en réparation, retirées de la disponibilité (MAT-05)."""

    materiel = models.ForeignKey(Materiel, on_delete=models.PROTECT, related_name="stocks")
    site = models.ForeignKey("referentiel.Site", on_delete=models.PROTECT, related_name="stocks_materiel")
    espace = models.ForeignKey("referentiel.Espace", null=True, blank=True, on_delete=models.PROTECT, related_name="materiels")
    quantite = models.PositiveIntegerField(default=0)
    hors_service = models.PositiveIntegerField(default=0)
    dernier_controle = models.DateField(null=True, blank=True)

    class Meta:
        ordering = ["materiel__libelle", "site__nom"]
        constraints = [
            models.UniqueConstraint(fields=["materiel", "site", "espace"], nulls_distinct=False, name="stock_unique_par_lieu"),
            models.CheckConstraint(condition=Q(hors_service__lte=F("quantite")), name="stock_hors_service_borne"),
        ]

    def __str__(self) -> str:
        lieu = f"{self.site} — {self.espace.nom}" if self.espace_id and self.espace else str(self.site)
        return f"{self.materiel} ({lieu})"

    def sites_concernes(self) -> set[int]:
        return {self.site_id}

    @property
    def en_etat(self) -> int:
        return self.quantite - self.hors_service


class ReservationMateriel(models.Model):
    """Prêt de matériel rattaché à un dossier (et à une réservation d'espace) sur une période (MAT-02)."""

    STATUTS = [
        ("demandee", "Demandée"),
        ("validee", "Validée"),
        ("sortie", "Sortie (remise à l'usager)"),
        ("rendue", "Rendue"),
        ("refusee", "Refusée"),
        ("annulee", "Annulée"),
    ]
    ORIGINES = [("backoffice", "Back-office"), ("portail", "Portail")]
    dossier = models.ForeignKey("reservations.Dossier", on_delete=models.PROTECT, related_name="materiels")
    reservation = models.ForeignKey(
        "reservations.Reservation", null=True, blank=True, on_delete=models.PROTECT, related_name="materiels"
    )
    occurrence = models.ForeignKey(
        "reservations.Occurrence",
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="materiels",
        help_text="Séance du prêt : le matériel suit ses horaires, son annulation et sa facturation.",
    )
    stock = models.ForeignKey(Stock, on_delete=models.PROTECT, related_name="reservations")
    quantite = models.PositiveIntegerField()
    debut = models.DateTimeField()
    fin = models.DateTimeField()
    statut = models.CharField(max_length=10, choices=STATUTS, default="demandee")
    quantite_sortie = models.PositiveIntegerField(null=True, blank=True)
    quantite_rendue = models.PositiveIntegerField(null=True, blank=True)
    manquants = models.PositiveIntegerField(default=0)
    manquants_regles = models.BooleanField(
        default=False,
        help_text="Le service a statué sur les manquants (retenue proposée ou prise en charge) : la caution peut être restituée.",
    )
    valeur_journaliere_centimes = models.PositiveIntegerField(
        default=0, help_text="Valeur de référence d'une journée, figée à la création du prêt (valorisation, RG-05)."
    )
    prestation_code = models.SlugField(max_length=40, blank=True, default="", help_text="Prestation facturée, figée.")
    origine = models.CharField(max_length=10, choices=ORIGINES, default="backoffice")
    commentaire = models.CharField(max_length=300, blank=True, default="")
    motif = models.CharField(max_length=300, blank=True, default="", help_text="Motif d'un refus ou d'une annulation.")
    signalement = models.CharField(max_length=300, blank=True, default="")
    cree_le = models.DateTimeField(auto_now_add=True)
    cree_par = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.PROTECT, related_name="+")

    class Meta:
        ordering = ["debut"]
        indexes = [models.Index(fields=["stock", "debut"])]
        constraints = [
            models.CheckConstraint(condition=Q(quantite__gte=1), name="reservation_materiel_quantite_positive"),
            models.CheckConstraint(condition=Q(fin__gt=F("debut")), name="reservation_materiel_periode"),
        ]

    def __str__(self) -> str:
        return f"{self.quantite} × {self.stock.materiel} — {self.dossier}"

    def sites_concernes(self) -> set[int]:
        return {self.stock.site_id}


class Mouvement(models.Model):
    """Journal des mouvements de stock (MAT-03) : immuable en base, on corrige par un mouvement inverse."""

    TYPES = [
        ("entree", "Entrée (achat, don)"),
        ("sortie", "Sortie (prêt)"),
        ("retour", "Retour de prêt"),
        ("transfert", "Transfert entre lieux"),
        ("perte", "Perte ou vol"),
        ("panne", "Mise hors service"),
        ("reparation", "Remise en service"),
        ("rebut", "Mise au rebut"),
        ("consommation", "Consommation"),
        ("inventaire", "Ajustement d'inventaire"),
    ]
    type = models.CharField(max_length=12, choices=TYPES)
    stock = models.ForeignKey(Stock, on_delete=models.PROTECT, related_name="mouvements")
    stock_destination = models.ForeignKey(Stock, null=True, blank=True, on_delete=models.PROTECT, related_name="+")
    quantite = models.IntegerField(help_text="Positive ; négative seulement pour un ajustement d'inventaire à la baisse.")
    reservation = models.ForeignKey(
        ReservationMateriel, null=True, blank=True, on_delete=models.PROTECT, related_name="mouvements"
    )
    motif = models.CharField(max_length=300, blank=True, default="")
    agent = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.PROTECT, related_name="+")
    acteur_libelle = models.CharField(max_length=200, blank=True, default="")
    horodatage = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-horodatage", "-id"]

    def __str__(self) -> str:
        return f"{self.get_type_display()} {self.quantite} — {self.stock}"

    def sites_concernes(self) -> set[int]:
        return {self.stock.site_id}


class Controle(models.Model):
    """Contrôle périodique, maintenance ou réparation (MAT-04)."""

    NATURES = [("controle", "Contrôle périodique"), ("maintenance", "Maintenance"), ("reparation", "Réparation")]
    stock = models.ForeignKey(Stock, on_delete=models.PROTECT, related_name="controles")
    nature = models.CharField(max_length=12, choices=NATURES, default="controle")
    realise_le = models.DateField()
    conforme = models.BooleanField(default=True)
    observations = models.TextField(blank=True, default="")
    prestataire = models.CharField(max_length=150, blank=True, default="")
    prochain_le = models.DateField(null=True, blank=True)
    agent = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.PROTECT, related_name="+")
    cree_le = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-realise_le", "-id"]

    def __str__(self) -> str:
        return f"{self.get_nature_display()} {self.stock} du {self.realise_le:%d/%m/%Y}"

    def sites_concernes(self) -> set[int]:
        return {self.stock.site_id}


class Panne(models.Model):
    """Signalement de panne (MAT-05) : les unités concernées sont hors service jusqu'à la réparation ou au rebut."""

    STATUTS = [("ouverte", "En panne"), ("reparee", "Réparée"), ("rebut", "Mise au rebut")]
    SOURCES = [("backoffice", "Back-office"), ("controle", "Contrôle non conforme"), ("incident", "Incident signalé")]
    stock = models.ForeignKey(Stock, on_delete=models.PROTECT, related_name="pannes")
    quantite = models.PositiveIntegerField(default=1)
    description = models.TextField()
    source = models.CharField(max_length=10, choices=SOURCES, default="backoffice")
    incident = models.ForeignKey("personnel.Incident", null=True, blank=True, on_delete=models.PROTECT, related_name="pannes")
    statut = models.CharField(max_length=8, choices=STATUTS, default="ouverte")
    signalee_par = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.PROTECT, related_name="+")
    signalee_le = models.DateTimeField(auto_now_add=True)
    resolue_le = models.DateTimeField(null=True, blank=True)
    resolution = models.TextField(blank=True, default="")

    class Meta:
        ordering = ["-signalee_le"]
        constraints = [models.CheckConstraint(condition=Q(quantite__gte=1), name="panne_quantite_positive")]

    def __str__(self) -> str:
        return f"Panne {self.stock} ({self.quantite})"

    def sites_concernes(self) -> set[int]:
        return {self.stock.site_id}
