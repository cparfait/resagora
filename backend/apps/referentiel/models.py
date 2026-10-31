"""Référentiel des sites, bâtiments, familles et espaces (REF-01, REF-02, REF-04, REF-05, REF-07)."""

from __future__ import annotations

from django.db import models


class Site(models.Model):
    code = models.SlugField(max_length=30, unique=True)
    nom = models.CharField(max_length=150)
    adresse = models.CharField(max_length=250, blank=True, default="")
    code_postal = models.CharField(max_length=5, blank=True, default="92320")
    commune = models.CharField(max_length=80, blank=True, default="Châtillon")
    telephone = models.CharField(max_length=20, blank=True, default="")
    actif = models.BooleanField(default=True)

    class Meta:
        ordering = ["nom"]

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

    def ancetres(self) -> list[Espace]:
        resultat: list[Espace] = []
        courant = self.parent
        while courant is not None and courant not in resultat:
            resultat.append(courant)
            courant = courant.parent
        return resultat

    def descendants(self) -> list[Espace]:
        resultat: list[Espace] = []
        a_visiter = list(self.sous_espaces.all())
        while a_visiter:
            espace = a_visiter.pop()
            if espace not in resultat:
                resultat.append(espace)
                a_visiter.extend(espace.sous_espaces.all())
        return resultat

    def ids_lies(self) -> set[int]:
        """Espace, ancêtres et descendants : l'ensemble bloqué par une occupation (REF-05, RG-01)."""
        return {self.pk, *(e.pk for e in self.ancetres()), *(e.pk for e in self.descendants())}
