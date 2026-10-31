"""Valorisation des avantages en nature (lot 6) : méthodes par famille d'espaces et par exercice (VAL-01), calcul par
bénéficiaire (VAL-02, VAL-03), subventions en numéraire importées et seuils légaux (VAL-06), versions figées à la
clôture et recalcul tracé (VAL-08), attestation déposée sur le portail (VAL-04)."""

from __future__ import annotations

from datetime import date

from django.conf import settings
from django.db import models
from django.db.models import Q

METHODES = [
    ("tarif_reference", "Tarif de référence voté"),
    ("cout_revient", "Coût de revient horaire"),
    ("valeur_locative", "Valeur locative"),
]


class Exercice(models.Model):
    """Exercice budgétaire (année civile) ; clos, ses valorisations et ses paramètres de calcul sont figés. Objet de la
    Ville entière : seul un périmètre « tous sites » le modifie (RG-14)."""

    ecriture_ville_entiere = True
    STATUTS = [("ouvert", "Ouvert"), ("cloture", "Clôturé")]
    annee = models.PositiveSmallIntegerField(unique=True)
    statut = models.CharField(max_length=8, choices=STATUTS, default="ouvert")
    date_limite_attestations = models.DateField(
        null=True, blank=True, help_text="Date avant laquelle les attestations sont déposées sur le portail (VAL-04)."
    )
    cloture_le = models.DateTimeField(null=True, blank=True)
    cloture_par = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.PROTECT, related_name="+")
    # Paramètres de calcul propres à l'exercice (VAL-01, VAL-08) : repris des paramètres généraux à la création,
    # modifiables tant que l'exercice est ouvert, figés ensuite (un recalcul tracé d'un exercice clos les réutilise).
    cout_horaire_personnel_centimes = models.PositiveIntegerField(
        null=True, blank=True, help_text="Coût chargé d'une heure de personnel dédié (centimes)."
    )
    absences_non_signalees_valorisees = models.BooleanField(null=True, blank=True)

    class Meta:
        ordering = ["-annee"]

    def __str__(self) -> str:
        return f"Exercice {self.annee}"

    @property
    def debut(self) -> date:
        return date(self.annee, 1, 1)

    @property
    def fin(self) -> date:
        return date(self.annee, 12, 31)

    def cout_personnel(self) -> int:
        from apps.noyau.parametres import parametre

        if self.cout_horaire_personnel_centimes is not None:
            return self.cout_horaire_personnel_centimes
        return int(parametre("valorisation.cout_horaire_personnel_centimes"))

    def absences_valorisees(self) -> bool:
        from apps.noyau.parametres import parametre

        if self.absences_non_signalees_valorisees is not None:
            return self.absences_non_signalees_valorisees
        return bool(parametre("valorisation.absences_non_signalees_valorisees"))

    def date_limite(self) -> date:
        """Date de dépôt des attestations : celle de l'exercice, sinon le paramètre JJ-MM de l'année suivante."""
        from apps.noyau.parametres import parametre

        if self.date_limite_attestations:
            return self.date_limite_attestations
        jour, mois = (int(x) for x in str(parametre("valorisation.date_depot_attestations")).split("-"))
        return date(self.annee + 1, mois, jour)

    def sites_concernes(self) -> None:
        return None


class MethodeValorisation(models.Model):
    """VAL-01 : méthode d'une famille d'espaces pour un exercice, fondée sur une délibération ; elle peut changer d'un
    exercice à l'autre sans modifier les exercices clos."""

    ecriture_ville_entiere = True
    exercice = models.ForeignKey(Exercice, on_delete=models.PROTECT, related_name="methodes")
    famille = models.ForeignKey("referentiel.FamilleEspace", on_delete=models.PROTECT, related_name="methodes_valorisation")
    methode = models.CharField(max_length=16, choices=METHODES, default="tarif_reference")
    cout_horaire_centimes = models.PositiveIntegerField(null=True, blank=True, help_text="Coût de revient d'une heure.")
    loyer_m2_annuel_centimes = models.PositiveIntegerField(null=True, blank=True, help_text="Valeur locative annuelle du m².")
    heures_annuelles_reference = models.PositiveIntegerField(
        default=2000, help_text="Heures d'ouverture annuelles servant à ramener la valeur locative à l'heure."
    )
    deliberation_reference = models.CharField(max_length=120, blank=True, default="")

    class Meta:
        ordering = ["famille__libelle"]
        constraints = [models.UniqueConstraint(fields=["exercice", "famille"], name="methode_unique_par_famille")]

    def __str__(self) -> str:
        return f"{self.famille} — {self.get_methode_display()} ({self.exercice.annee})"

    def sites_concernes(self) -> None:
        return None


class SubventionNumeraire(models.Model):
    """VAL-06 : subvention en numéraire versée au bénéficiaire (importée du logiciel financier ou saisie)."""

    ecriture_ville_entiere = True
    exercice = models.ForeignKey(Exercice, on_delete=models.PROTECT, related_name="subventions")
    usager = models.ForeignKey("usagers.Usager", on_delete=models.PROTECT, related_name="subventions_numeraire")
    montant_centimes = models.PositiveBigIntegerField()
    objet = models.CharField(max_length=250, blank=True, default="")
    deliberation_reference = models.CharField(max_length=120, blank=True, default="")
    reference_import = models.CharField(max_length=120, blank=True, default="", help_text="Ligne du fichier importé.")
    importe_le = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-montant_centimes"]

    def __str__(self) -> str:
        return f"{self.usager} — {self.montant_centimes} c ({self.exercice.annee})"

    def sites_concernes(self) -> None:
        return None


class Valorisation(models.Model):
    """Valorisation d'un bénéficiaire pour un exercice. Chaque calcul est une version ; seule la dernière est
    « actuelle ». Une version figée (exercice clos) ne change plus : un recalcul crée une nouvelle version (VAL-08)."""

    ecriture_ville_entiere = True
    exercice = models.ForeignKey(Exercice, on_delete=models.PROTECT, related_name="valorisations")
    usager = models.ForeignKey("usagers.Usager", on_delete=models.PROTECT, related_name="valorisations")
    version = models.PositiveSmallIntegerField(default=1)
    actuelle = models.BooleanField(default=True)
    figee = models.BooleanField(default=False)
    minutes = models.PositiveIntegerField(default=0)
    montant_espaces = models.BigIntegerField(default=0)
    montant_materiel = models.BigIntegerField(default=0)
    montant_personnel = models.BigIntegerField(default=0)
    total = models.BigIntegerField(default=0)
    calcule_le = models.DateTimeField(auto_now_add=True)
    calcule_par = models.CharField(max_length=200, blank=True, default="")
    motif_recalcul = models.TextField(blank=True, default="")
    document = models.ForeignKey(
        "documents.Document", null=True, blank=True, on_delete=models.PROTECT, related_name="+", help_text="Attestation."
    )
    deposee_le = models.DateTimeField(null=True, blank=True, help_text="Attestation mise à disposition sur le portail.")

    class Meta:
        ordering = ["exercice", "usager__nom", "-version"]
        constraints = [
            models.UniqueConstraint(fields=["exercice", "usager", "version"], name="valorisation_version_unique"),
            models.UniqueConstraint(
                fields=["exercice", "usager"], condition=Q(actuelle=True), name="valorisation_une_seule_actuelle"
            ),
        ]

    def __str__(self) -> str:
        return f"Valorisation {self.usager} {self.exercice.annee} v{self.version}"

    def sites_concernes(self) -> None:
        return None


class LigneValorisation(models.Model):
    NATURES = [("espace", "Mise à disposition d'espace"), ("materiel", "Prêt de matériel"), ("personnel", "Personnel dédié")]
    valorisation = models.ForeignKey(Valorisation, on_delete=models.CASCADE, related_name="lignes")
    nature = models.CharField(max_length=10, choices=NATURES)
    occurrence = models.ForeignKey("reservations.Occurrence", null=True, blank=True, on_delete=models.PROTECT, related_name="+")
    pret = models.ForeignKey("materiel.ReservationMateriel", null=True, blank=True, on_delete=models.PROTECT, related_name="+")
    espace = models.ForeignKey("referentiel.Espace", null=True, blank=True, on_delete=models.PROTECT, related_name="+")
    libelle = models.CharField(max_length=250)
    methode = models.CharField(max_length=16, choices=METHODES, default="tarif_reference")
    quantite = models.PositiveIntegerField(help_text="Minutes pour un espace ou du personnel, unités × jours pour le matériel.")
    part = models.PositiveIntegerField(default=10000, help_text="Part d'occupation en dix-millièmes (espace partagé).")
    montant_reference = models.BigIntegerField()
    montant_paye = models.BigIntegerField(default=0)
    montant_valorise = models.BigIntegerField()
    observation = models.CharField(max_length=250, blank=True, default="")

    class Meta:
        ordering = ["valorisation", "nature", "id"]

    def __str__(self) -> str:
        return self.libelle
