"""Référentiel des sites, bâtiments, familles et espaces (REF-01, REF-02, REF-04, REF-05, REF-07)."""

from __future__ import annotations

import re
from datetime import datetime, timedelta

from django.core.exceptions import ValidationError
from django.core.validators import MaxValueValidator, MinValueValidator
from django.db import models

CODE_D_ACCES = re.compile(
    r"digicode|code\s+(?:d'|d’|de\s+l'|de\s+la\s+|du\s+)?(?:accès|acces|porte|portail|entrée|entree|alarme)", re.I
)


def sans_code_d_acces(texte: str) -> None:
    """REF-01 : les consignes d'accès sont publiques (portail, agenda, rappel) : jamais de code d'accès."""
    if CODE_D_ACCES.search(texte):
        raise ValidationError(
            "Ces consignes sont publiées sur le portail : retirez le code d'accès. Transmettez-le à part, à l'usager concerné."
        )


class Site(models.Model):
    code = models.SlugField(max_length=30, unique=True)
    nom = models.CharField(max_length=150)
    adresse = models.CharField(max_length=250, blank=True, default="")
    code_postal = models.CharField(max_length=5, blank=True, default="92320")
    commune = models.CharField(max_length=80, blank=True, default="Châtillon")
    telephone = models.CharField(max_length=20, blank=True, default="")
    # REF-01, POR-03 : situation et accès publiés sur le portail et rappelés la veille des séances (COM-01).
    latitude = models.DecimalField(
        max_digits=8, decimal_places=6, null=True, blank=True, validators=[MinValueValidator(-90), MaxValueValidator(90)]
    )
    longitude = models.DecimalField(
        max_digits=9, decimal_places=6, null=True, blank=True, validators=[MinValueValidator(-180), MaxValueValidator(180)]
    )
    acces = models.TextField(
        "consignes d'accès",
        max_length=1000,
        blank=True,
        default="",
        help_text="Publiées sur le portail : entrée, stationnement, transports. Jamais de code d'accès ni de digicode.",
        validators=[sans_code_d_acces],
    )
    actif = models.BooleanField(default=True)

    class Meta:
        ordering = ["nom"]
        constraints = [
            models.CheckConstraint(
                name="site_coordonnees_completes",
                condition=models.Q(latitude__isnull=True, longitude__isnull=True)
                | models.Q(latitude__isnull=False, longitude__isnull=False),
            )
        ]

    def __str__(self) -> str:
        return self.nom

    def sites_concernes(self) -> set[int]:
        return {self.pk}


class Batiment(models.Model):
    site = models.ForeignKey(Site, on_delete=models.PROTECT, related_name="batiments")
    nom = models.CharField(max_length=150)
    erp_categorie = models.CharField("catégorie ERP", max_length=3, blank=True, default="")
    erp_type = models.CharField("type ERP", max_length=3, blank=True, default="")
    actif = models.BooleanField(default=True)

    class Meta:
        ordering = ["site", "nom"]
        constraints = [models.UniqueConstraint(fields=["site", "nom"], name="batiment_unique_par_site")]

    def __str__(self) -> str:
        return f"{self.site} — {self.nom}"

    def sites_concernes(self) -> set[int]:
        return {self.site_id}


class FamilleEspace(models.Model):
    """Famille d'espaces (REF-02) ; porte aussi la méthode de valorisation (VAL-01)."""

    code = models.SlugField(max_length=40, unique=True)
    libelle = models.CharField(max_length=120)
    ordre = models.PositiveSmallIntegerField(default=0)

    #: Référentiel commun : seul un agent habilité sur toute la Ville peut le modifier (RG-14, ADR 0005).
    ecriture_ville_entiere = True

    class Meta:
        ordering = ["ordre", "libelle"]
        verbose_name = "famille d'espaces"

    def __str__(self) -> str:
        return self.libelle

    def sites_concernes(self) -> None:
        return None


class Espace(models.Model):
    batiment = models.ForeignKey(Batiment, on_delete=models.PROTECT, related_name="espaces")
    parent = models.ForeignKey(
        "self",
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name="sous_espaces",
        help_text="Espace englobant : réserver l'un bloque l'autre (REF-05).",
    )
    famille = models.ForeignKey(FamilleEspace, on_delete=models.PROTECT, related_name="espaces")
    code = models.SlugField(max_length=40, unique=True)
    nom = models.CharField(max_length=150)
    description = models.TextField(blank=True, default="")
    capacite = models.PositiveIntegerField("capacité d'accueil (personnes)", default=0)
    surface_m2 = models.PositiveIntegerField("surface (m²)", default=0)
    accessible_pmr = models.BooleanField("accessible aux personnes à mobilité réduite", default=False)
    equipements = models.TextField("équipements fixes", blank=True, default="")
    activites = models.CharField("activités possibles", max_length=300, blank=True, default="")
    gardiennage_requis = models.BooleanField(default=False, help_text="Toute occupation génère un besoin de gardien (REF-04).")
    temps_ouverture_min = models.PositiveSmallIntegerField("temps d'ouverture (min)", default=15)
    temps_fermeture_min = models.PositiveSmallIntegerField("temps de fermeture (min)", default=15)
    partageable = models.BooleanField(default=False, help_text="Plusieurs réservations simultanées possibles (REF-07).")
    capacite_simultanee = models.PositiveSmallIntegerField("réservations simultanées maximum", default=1)
    reservable_portail = models.BooleanField("réservable depuis le portail", default=True)
    actif = models.BooleanField(default=True)

    class Meta:
        ordering = ["batiment__site__nom", "nom"]
        constraints = [
            models.CheckConstraint(condition=models.Q(capacite_simultanee__gte=1), name="espace_capacite_simultanee_min"),
            models.CheckConstraint(condition=~models.Q(parent=models.F("id")), name="espace_pas_son_propre_parent"),
        ]

    def __str__(self) -> str:
        return self.nom

    @property
    def site(self) -> Site:
        return self.batiment.site

    def sites_concernes(self) -> set[int]:
        return {self.batiment.site_id}

    @staticmethod
    def _liens() -> dict[int, int | None]:
        """Hiérarchie complète en une requête (30 à 50 espaces : volume modeste, pas de requête récursive)."""
        return dict(Espace.objects.values_list("pk", "parent_id"))

    def _ids_ancetres(self, liens: dict[int, int | None]) -> list[int]:
        resultat: list[int] = []
        courant = liens.get(self.pk) if self.pk in liens else self.parent_id
        while courant is not None and courant not in resultat and courant != self.pk:
            resultat.append(courant)
            courant = liens.get(courant)
        return resultat

    def _ids_descendants(self, liens: dict[int, int | None]) -> list[int]:
        enfants: dict[int, list[int]] = {}
        for identifiant, parent in liens.items():
            if parent is not None:
                enfants.setdefault(parent, []).append(identifiant)
        resultat: list[int] = []
        a_visiter = list(enfants.get(self.pk, []))
        while a_visiter:
            courant = a_visiter.pop()
            if courant not in resultat and courant != self.pk:
                resultat.append(courant)
                a_visiter.extend(enfants.get(courant, []))
        return resultat

    def ancetres(self) -> list[Espace]:
        identifiants = self._ids_ancetres(self._liens())
        par_id = {e.pk: e for e in Espace.objects.filter(pk__in=identifiants)}
        return [par_id[i] for i in identifiants if i in par_id]

    def descendants(self) -> list[Espace]:
        return list(Espace.objects.filter(pk__in=self._ids_descendants(self._liens())))

    def feuilles(self) -> list[Espace]:
        """Espaces sans sous-espace couverts par celui-ci (lui-même s'il n'en a pas) : base des verrous RG-01."""
        liens = self._liens()
        descendants = set(self._ids_descendants(liens))
        if not descendants:
            return [self]
        parents = {p for p in liens.values() if p is not None}
        return list(Espace.objects.filter(pk__in=[i for i in descendants if i not in parents]))

    def plage_gardiennage(self, debut: datetime, fin: datetime) -> tuple[datetime, datetime] | None:
        """REF-04 : présence de gardien exigée par une occupation, élargie des temps d'ouverture et de fermeture."""
        if not self.gardiennage_requis:
            return None
        return debut - timedelta(minutes=self.temps_ouverture_min), fin + timedelta(minutes=self.temps_fermeture_min)

    def ids_lies(self) -> set[int]:
        """Espace, ancêtres et descendants : l'ensemble bloqué par une occupation (REF-05, RG-01)."""
        liens = self._liens()
        return {self.pk, *self._ids_ancetres(liens), *self._ids_descendants(liens)}


class PhotoEspace(models.Model):
    """Photo d'un espace avec sa description (alternative textuelle, RGAA) — REF-01."""

    espace = models.ForeignKey(Espace, on_delete=models.CASCADE, related_name="photos")
    fichier = models.ForeignKey("noyau.Fichier", on_delete=models.PROTECT, related_name="+")
    description = models.CharField("description (texte alternatif)", max_length=250)
    ordre = models.PositiveSmallIntegerField(default=0)

    class Meta:
        ordering = ["espace", "ordre"]

    def __str__(self) -> str:
        return self.description

    def sites_concernes(self) -> set[int]:
        return self.espace.sites_concernes()


class DocumentEspace(models.Model):
    """Règlement intérieur, plan, consignes de sécurité rattachés à un espace (REF-08)."""

    NATURES = [
        ("reglement", "Règlement intérieur"),
        ("plan", "Plan d'accès"),
        ("securite", "Consignes de sécurité"),
        ("autre", "Autre"),
    ]
    espace = models.ForeignKey(Espace, on_delete=models.CASCADE, related_name="documents")
    nature = models.CharField(max_length=20, choices=NATURES, default="reglement")
    titre = models.CharField(max_length=200)
    fichier = models.ForeignKey("noyau.Fichier", on_delete=models.PROTECT, related_name="+")
    public = models.BooleanField(default=True, help_text="Téléchargeable depuis le portail.")

    class Meta:
        ordering = ["espace", "nature", "titre"]

    def __str__(self) -> str:
        return self.titre

    def sites_concernes(self) -> set[int]:
        return self.espace.sites_concernes()


class Saison(models.Model):
    """Saison sportive (ex. 2026-2027) : cadre des créneaux annuels et du calendrier (ADM-01)."""

    nom = models.CharField(max_length=40, unique=True)
    debut = models.DateField()
    fin = models.DateField()
    active = models.BooleanField(default=False)
    cloturee = models.BooleanField(
        "saison close", default=False, help_text="Plus aucune réservation ne peut y être créée ni modifiée (bilan arrêté)."
    )

    class Meta:
        ordering = ["-debut"]
        constraints = [models.CheckConstraint(condition=models.Q(fin__gt=models.F("debut")), name="saison_dates")]

    def __str__(self) -> str:
        return self.nom

    @property
    def annee_scolaire(self) -> str:
        return f"{self.debut.year}-{self.debut.year + 1}" if self.debut.month >= 8 else f"{self.debut.year - 1}-{self.debut.year}"

    def sites_concernes(self) -> None:
        return None

    ecriture_ville_entiere = True


class PeriodeCalendrier(models.Model):
    NATURES = [("vacances", "Vacances scolaires"), ("ferie", "Jour férié"), ("fermeture_ville", "Fermeture générale de la Ville")]
    SOURCES = [("import", "Open data Éducation nationale"), ("calcul", "Calcul des jours fériés"), ("saisie", "Saisie")]
    saison = models.ForeignKey(Saison, on_delete=models.CASCADE, related_name="periodes")
    nature = models.CharField(max_length=20, choices=NATURES)
    libelle = models.CharField(max_length=150)
    debut = models.DateField()
    fin = models.DateField(help_text="Incluse.")
    zone = models.CharField(max_length=20, blank=True, default="")
    source = models.CharField(max_length=10, choices=SOURCES, default="saisie")

    class Meta:
        ordering = ["debut"]
        constraints = [models.CheckConstraint(condition=models.Q(fin__gte=models.F("debut")), name="periode_dates")]

    def __str__(self) -> str:
        return f"{self.libelle} ({self.debut:%d/%m/%Y} – {self.fin:%d/%m/%Y})"

    def sites_concernes(self) -> None:
        return None

    ecriture_ville_entiere = True


class HoraireOuverture(models.Model):
    """Plage d'ouverture d'un espace pour un jour de la semaine, éventuellement propre à une saison (REF-03)."""

    JOURS = [(0, "lundi"), (1, "mardi"), (2, "mercredi"), (3, "jeudi"), (4, "vendredi"), (5, "samedi"), (6, "dimanche")]
    espace = models.ForeignKey(Espace, on_delete=models.CASCADE, related_name="horaires")
    saison = models.ForeignKey(Saison, null=True, blank=True, on_delete=models.CASCADE, related_name="horaires")
    jour_semaine = models.PositiveSmallIntegerField(choices=JOURS)
    debut = models.TimeField()
    fin = models.TimeField()
    pendant_vacances = models.BooleanField(default=True, help_text="Plage valable aussi pendant les vacances scolaires.")

    class Meta:
        ordering = ["espace", "jour_semaine", "debut"]
        constraints = [models.CheckConstraint(condition=models.Q(fin__gt=models.F("debut")), name="horaire_ordre")]

    def __str__(self) -> str:
        return f"{self.get_jour_semaine_display()} {self.debut:%H:%M}–{self.fin:%H:%M}"

    def sites_concernes(self) -> set[int]:
        return self.espace.sites_concernes()


class Fermeture(models.Model):
    """Fermeture exceptionnelle d'un espace ou d'un site entier (REF-06)."""

    site = models.ForeignKey(Site, null=True, blank=True, on_delete=models.CASCADE, related_name="fermetures")
    espace = models.ForeignKey(Espace, null=True, blank=True, on_delete=models.CASCADE, related_name="fermetures")
    debut = models.DateTimeField()
    fin = models.DateTimeField()
    motif = models.CharField(max_length=250)
    cree_par = models.ForeignKey("habilitations.Utilisateur", null=True, on_delete=models.SET_NULL, related_name="+")
    cree_le = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-debut"]
        constraints = [
            models.CheckConstraint(condition=models.Q(fin__gt=models.F("debut")), name="fermeture_dates"),
            models.CheckConstraint(
                condition=models.Q(site__isnull=False, espace__isnull=True) | models.Q(site__isnull=True, espace__isnull=False),
                name="fermeture_site_ou_espace",
            ),
        ]

    def __str__(self) -> str:
        return f"Fermeture {self.espace or self.site} : {self.motif}"

    def sites_concernes(self) -> set[int]:
        return {self.site_id} if self.site_id else (self.espace.sites_concernes() if self.espace else set())

    def espaces_concernes(self) -> list[Espace]:
        if self.espace is not None:
            return [self.espace, *self.espace.descendants()]
        return list(Espace.objects.filter(batiment__site_id=self.site_id or 0))
