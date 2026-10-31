"""Tarifs, devis, factures, titres de recettes, encaissements et cautions (TAR-01 à TAR-13, CAU-01 à CAU-07).

Montants en centimes entiers, taux en dix-millièmes (10000 = 100 %). Chaque ligne conserve son montant de
référence et son montant dû (RG-05) : une gratuité est une réduction de 100 % sur un tarif de référence, ce
qui permet la valorisation des avantages en nature. Factures, avoirs et journal des cautions sont
immuables (RG-13) : la base refuse toute modification de leur contenu.
"""

from __future__ import annotations

from django.conf import settings
from django.db import models
from django.db.models import Q

CATEGORIES = [
    ("association_locale", "Association locale"),
    ("association", "Association extérieure"),
    ("ecole", "École ou établissement scolaire"),
    ("entreprise", "Entreprise ou comité social et économique"),
    ("particulier", "Particulier"),
    ("service_municipal", "Service municipal"),
    ("autre_collectivite", "Autre collectivité ou organisme public"),
]
UNITES = [
    ("heure", "Heure"),
    ("demi_journee", "Demi-journée (4 heures)"),
    ("journee", "Journée"),
    ("forfait", "Forfait par occupation"),
]
NATURES_MAJORATION = [
    ("week_end", "Week-end (samedi et dimanche)"),
    ("soiree", "Soirée (à partir de l'heure indiquée)"),
    ("ferie", "Jour férié"),
    ("non_resident", "Usager non résident"),
]


class GrilleTarifaire(models.Model):
    """Grille votée par délibération, applicable sur une période (TAR-01) ; une grille votée ne se modifie plus."""

    STATUTS = [("brouillon", "En préparation"), ("votee", "Votée"), ("archivee", "Archivée")]
    nom = models.CharField(max_length=150)
    debut = models.DateField("applicable à partir du")
    fin = models.DateField("applicable jusqu'au", null=True, blank=True)
    deliberation_reference = models.CharField("référence de la délibération", max_length=150, blank=True, default="")
    deliberation_date = models.DateField(null=True, blank=True)
    statut = models.CharField(max_length=10, choices=STATUTS, default="brouillon")
    heure_soiree = models.TimeField("début de la soirée (majoration)", null=True, blank=True)
    cree_le = models.DateTimeField(auto_now_add=True)

    ecriture_ville_entiere = True

    class Meta:
        ordering = ["-debut"]

    def __str__(self) -> str:
        return self.nom

    def sites_concernes(self) -> None:
        return None


class Tarif(models.Model):
    grille = models.ForeignKey(GrilleTarifaire, on_delete=models.CASCADE, related_name="tarifs")
    espace = models.ForeignKey("referentiel.Espace", null=True, blank=True, on_delete=models.CASCADE, related_name="tarifs")
    famille = models.ForeignKey(
        "referentiel.FamilleEspace",
        null=True,
        blank=True,
        on_delete=models.CASCADE,
        related_name="tarifs",
        help_text="Tarif commun à une famille d'espaces (un tarif propre à l'espace prévaut).",
    )
    categorie = models.CharField(max_length=20, choices=CATEGORIES)
    unite = models.CharField(max_length=15, choices=UNITES, default="heure")
    prix_centimes = models.PositiveIntegerField()
    caution_centimes = models.PositiveIntegerField(default=0, help_text="CAU-01 : caution exigée (0 : aucune).")

    class Meta:
        ordering = ["grille", "espace", "famille", "categorie"]
        constraints = [
            models.CheckConstraint(
                condition=(Q(espace__isnull=False) & Q(famille__isnull=True))
                | (Q(espace__isnull=True) & Q(famille__isnull=False)),
                name="tarif_espace_ou_famille",
            ),
            models.UniqueConstraint(fields=["grille", "espace", "categorie", "unite"], name="tarif_unique_espace"),
            models.UniqueConstraint(fields=["grille", "famille", "categorie", "unite"], name="tarif_unique_famille"),
        ]

    def __str__(self) -> str:
        return f"{self.espace or self.famille} — {self.get_categorie_display()} — {self.get_unite_display()}"

    def sites_concernes(self) -> None:
        return None


class Majoration(models.Model):
    grille = models.ForeignKey(GrilleTarifaire, on_delete=models.CASCADE, related_name="majorations")
    nature = models.CharField(max_length=15, choices=NATURES_MAJORATION)
    taux = models.PositiveIntegerField("taux (dix-millièmes)", help_text="2500 = 25 %.")
    categories = models.JSONField(default=list, blank=True, help_text="Catégories concernées (vide : toutes).")

    class Meta:
        constraints = [models.UniqueConstraint(fields=["grille", "nature"], name="majoration_unique")]

    def __str__(self) -> str:
        return f"{self.get_nature_display()} : {self.taux / 100:.2f} %"

    def sites_concernes(self) -> None:
        return None


class Prestation(models.Model):
    """Prestation annexe (ménage, gardiennage supplémentaire, sonorisation…) — TAR-02."""

    grille = models.ForeignKey(GrilleTarifaire, on_delete=models.CASCADE, related_name="prestations")
    code = models.SlugField(max_length=40)
    libelle = models.CharField(max_length=150)
    unite = models.CharField(max_length=15, choices=UNITES, default="forfait")
    prix_centimes = models.PositiveIntegerField()

    class Meta:
        constraints = [models.UniqueConstraint(fields=["grille", "code"], name="prestation_unique")]

    def __str__(self) -> str:
        return self.libelle

    def sites_concernes(self) -> None:
        return None


class Reduction(models.Model):
    """Gratuité ou réduction accordée (TAR-03, RG-05) : taux sur le tarif de référence, fondement obligatoire."""

    usager = models.ForeignKey("usagers.Usager", on_delete=models.PROTECT, related_name="reductions")
    type_reservation = models.ForeignKey(
        "reservations.TypeReservation",
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name="reductions",
        help_text="Vide : toutes les réservations de l'usager.",
    )
    taux = models.PositiveIntegerField("taux de réduction (dix-millièmes)", help_text="10000 = gratuité.")
    fondement = models.CharField(max_length=250, help_text="Délibération, convention ou décision (référence).")
    debut = models.DateField()
    fin = models.DateField(null=True, blank=True)
    cree_le = models.DateTimeField(auto_now_add=True)
    cree_par = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, on_delete=models.SET_NULL, related_name="+")

    ecriture_ville_entiere = True

    class Meta:
        ordering = ["usager", "-debut"]
        constraints = [models.CheckConstraint(condition=Q(taux__lte=10000), name="reduction_taux_borne")]

    def __str__(self) -> str:
        return f"{self.usager} : {self.taux / 100:.0f} % ({self.fondement})"

    def sites_concernes(self) -> None:
        return None


class PieceComptable(models.Model):
    """Devis, facture, facture d'acompte ou avoir. Le contenu d'une pièce émise ne change plus (RG-13)."""

    NATURES = [("devis", "Devis"), ("acompte", "Facture d'acompte"), ("facture", "Facture"), ("avoir", "Avoir")]
    STATUTS = [
        ("brouillon", "Brouillon"),
        ("emis", "Émis"),
        ("accepte", "Devis accepté"),
        ("refuse", "Devis refusé"),
        ("expire", "Devis expiré"),
        ("a_titrer", "À titrer"),
        ("titre_emis", "Titre émis"),
        ("solde", "Soldée"),
        ("solde_partiel", "Partiellement soldée"),
        ("en_recouvrement", "En recouvrement"),
        ("annulee", "Annulée par avoir"),
    ]
    nature = models.CharField(max_length=10, choices=NATURES)
    numero = models.CharField(max_length=20, unique=True, null=True, blank=True)
    exercice = models.PositiveSmallIntegerField(null=True, blank=True)
    dossier = models.ForeignKey("reservations.Dossier", on_delete=models.PROTECT, related_name="pieces_comptables")
    usager = models.ForeignKey("usagers.Usager", on_delete=models.PROTECT, related_name="pieces_comptables")
    origine = models.ForeignKey(
        "self",
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name="derivees",
        help_text="Devis d'origine d'une facture, ou facture corrigée par un avoir.",
    )
    objet = models.CharField(max_length=250)
    statut = models.CharField(max_length=15, choices=STATUTS, default="brouillon")
    emise_le = models.DateField(null=True, blank=True)
    echeance = models.DateField(null=True, blank=True)
    validite = models.DateField("devis valable jusqu'au", null=True, blank=True)
    total_reference = models.BigIntegerField(default=0, help_text="Somme des montants de référence (centimes).")
    total_du = models.BigIntegerField(default=0, help_text="Somme des montants dus (centimes, négatif pour un avoir).")
    acompte_deduit = models.BigIntegerField(default=0)
    montant_regle = models.BigIntegerField(default=0)
    motif = models.CharField(max_length=300, blank=True, default="", help_text="Avoir : motif de la correction.")
    reference_virement = models.CharField(max_length=40, blank=True, default="")
    titre_numero = models.CharField("numéro de titre Ciril", max_length=40, blank=True, default="")
    titre_le = models.DateField(null=True, blank=True)
    solde_le = models.DateField(null=True, blank=True)
    accepte_le = models.DateTimeField(null=True, blank=True)
    accepte_par = models.CharField(max_length=200, blank=True, default="")
    document = models.ForeignKey("documents.Document", null=True, blank=True, on_delete=models.PROTECT, related_name="+")
    emise_par = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name="+")
    cree_le = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-cree_le"]
        indexes = [models.Index(fields=["nature", "statut"]), models.Index(fields=["titre_numero"])]

    def __str__(self) -> str:
        return f"{self.get_nature_display()} {self.numero or '(brouillon)'}"

    def sites_concernes(self) -> set[int] | None:
        return self.dossier.sites_concernes()

    @property
    def reste_du(self) -> int:
        return self.total_du - self.acompte_deduit - self.montant_regle


class LigneComptable(models.Model):
    piece = models.ForeignKey(PieceComptable, on_delete=models.CASCADE, related_name="lignes")
    rang = models.PositiveSmallIntegerField()
    libelle = models.CharField(max_length=250)
    occurrence = models.ForeignKey(
        "reservations.Occurrence", null=True, blank=True, on_delete=models.PROTECT, related_name="lignes_comptables"
    )
    espace = models.ForeignKey("referentiel.Espace", null=True, blank=True, on_delete=models.PROTECT, related_name="+")
    nature = models.CharField(
        max_length=15,
        choices=[
            ("occupation", "Occupation"),
            ("majoration", "Majoration"),
            ("prestation", "Prestation"),
            ("frais", "Frais d'annulation"),
            ("acompte", "Acompte"),
        ],
    )
    quantite = models.PositiveIntegerField(help_text="Minutes pour l'unité « heure », sinon nombre d'unités.")
    unite = models.CharField(max_length=15, choices=UNITES)
    prix_unitaire = models.BigIntegerField()
    montant_reference = models.BigIntegerField()
    taux_reduction = models.PositiveIntegerField(default=0)
    montant_du = models.BigIntegerField()
    fondement = models.CharField(max_length=250, blank=True, default="")
    tarif = models.ForeignKey(Tarif, null=True, blank=True, on_delete=models.PROTECT, related_name="+")

    class Meta:
        ordering = ["piece", "rang"]

    def __str__(self) -> str:
        return self.libelle


class LotTitres(models.Model):
    """Export des titres de recettes vers Ciril (TAR-06) : lot numéroté, rejouable, tracé."""

    numero = models.CharField(max_length=20, unique=True)
    format = models.CharField(max_length=5, choices=[("csv", "CSV"), ("xlsx", "Tableur XLSX"), ("xml", "XML")])
    pieces = models.ManyToManyField(PieceComptable, related_name="lots_titres")
    fichier = models.ForeignKey("noyau.Fichier", on_delete=models.PROTECT, related_name="+")
    total_centimes = models.BigIntegerField()
    cree_par = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, on_delete=models.SET_NULL, related_name="+")
    cree_le = models.DateTimeField(auto_now_add=True)

    ecriture_ville_entiere = True

    class Meta:
        ordering = ["-cree_le"]

    def __str__(self) -> str:
        return self.numero

    def sites_concernes(self) -> None:
        return None


class ImportEncaissements(models.Model):
    """Import d'un état des titres soldés exporté de Ciril (TAR-13) : rapport des lignes rapprochées ou non."""

    fichier = models.ForeignKey("noyau.Fichier", on_delete=models.PROTECT, related_name="+")
    lignes_lues = models.PositiveIntegerField(default=0)
    rapprochees = models.PositiveIntegerField(default=0)
    rejets = models.JSONField(default=list)
    cree_par = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, on_delete=models.SET_NULL, related_name="+")
    cree_le = models.DateTimeField(auto_now_add=True)

    ecriture_ville_entiere = True

    class Meta:
        ordering = ["-cree_le"]

    def __str__(self) -> str:
        return f"Import du {self.cree_le:%d/%m/%Y %H:%M}"

    def sites_concernes(self) -> None:
        return None


class Encaissement(models.Model):
    """Règlement constaté (import Ciril ou pointage manuel par la régie), en ajout seul."""

    immuable = True

    piece = models.ForeignKey(PieceComptable, on_delete=models.PROTECT, related_name="encaissements")
    montant = models.BigIntegerField()
    date = models.DateField()
    reference = models.CharField(max_length=100, blank=True, default="")
    origine = models.CharField(
        max_length=10,
        choices=[("import", "Import de l'état Ciril"), ("pointage", "Pointage manuel"), ("payfip", "Paiement en ligne PayFiP")],
    )
    import_lot = models.ForeignKey(
        ImportEncaissements, null=True, blank=True, on_delete=models.PROTECT, related_name="encaissements"
    )
    agent = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, on_delete=models.SET_NULL, related_name="+")
    cree_le = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["piece", "date"]

    def __str__(self) -> str:
        return f"{self.montant} c le {self.date}"

    def sites_concernes(self) -> set[int] | None:
        return self.piece.sites_concernes()


class AFacturer(models.Model):
    """Élément facturable en attente (frais d'annulation tardive RG-08, prestation ajoutée après coup)."""

    dossier = models.ForeignKey("reservations.Dossier", on_delete=models.PROTECT, related_name="a_facturer")
    occurrence = models.ForeignKey("reservations.Occurrence", null=True, blank=True, on_delete=models.PROTECT, related_name="+")
    libelle = models.CharField(max_length=250)
    nature = models.CharField(max_length=15, default="frais")
    montant_reference = models.BigIntegerField()
    taux_reduction = models.PositiveIntegerField(default=0)
    montant_du = models.BigIntegerField()
    fondement = models.CharField(max_length=250, blank=True, default="")
    facture = models.ForeignKey(PieceComptable, null=True, blank=True, on_delete=models.PROTECT, related_name="elements")
    cree_le = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["cree_le"]
        constraints = [models.UniqueConstraint(fields=["occurrence", "nature"], name="a_facturer_unique_par_seance")]

    def __str__(self) -> str:
        return self.libelle

    def sites_concernes(self) -> set[int] | None:
        return self.dossier.sites_concernes()


class EtatDesLieux(models.Model):
    """Constat d'entrée ou de sortie (saisi au back-office ou sur l'application mobile hors ligne)."""

    occurrence = models.ForeignKey("reservations.Occurrence", on_delete=models.PROTECT, related_name="etats_des_lieux")
    moment = models.CharField(max_length=10, choices=[("entree", "Entrée"), ("sortie", "Sortie")])
    constat = models.CharField(
        max_length=10, choices=[("conforme", "Conforme"), ("degats", "Dégâts constatés")], default="conforme"
    )
    observations = models.TextField(blank=True, default="")
    photos = models.ManyToManyField("noyau.Fichier", blank=True, related_name="+")
    signature_usager = models.ForeignKey("noyau.Fichier", null=True, blank=True, on_delete=models.PROTECT, related_name="+")
    agent = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, on_delete=models.SET_NULL, related_name="+")
    source = models.CharField(
        max_length=10, choices=[("backoffice", "Back-office"), ("mobile", "Application mobile")], default="backoffice"
    )
    constate_le = models.DateTimeField()
    cree_le = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-constate_le"]
        constraints = [models.UniqueConstraint(fields=["occurrence", "moment"], name="etat_des_lieux_unique")]

    def __str__(self) -> str:
        return f"État des lieux de {self.get_moment_display().lower()} — {self.occurrence}"

    def sites_concernes(self) -> set[int]:
        return self.occurrence.sites_concernes()


class Caution(models.Model):
    """CAU-02 : attendue → reçue → restituable → restituée | retenue partielle | retenue totale → encaissée."""

    STATUTS = [
        ("attendue", "Attendue"),
        ("recue", "Reçue"),
        ("restituable", "Restituable"),
        ("retenue_a_valider", "Retenue à valider (second agent)"),
        ("restituee", "Restituée"),
        ("retenue_partielle", "Retenue partielle"),
        ("retenue_totale", "Retenue totale"),
        ("encaissee", "Encaissée"),
    ]
    MODES = [("cheque", "Chèque (non encaissé)"), ("consignation", "Consignation auprès du comptable"), ("virement", "Virement")]
    dossier = models.ForeignKey("reservations.Dossier", on_delete=models.PROTECT, related_name="cautions")
    reservation = models.ForeignKey("reservations.Reservation", on_delete=models.PROTECT, related_name="cautions")
    usager = models.ForeignKey("usagers.Usager", on_delete=models.PROTECT, related_name="cautions")
    montant = models.BigIntegerField()
    statut = models.CharField(max_length=20, choices=STATUTS, default="attendue")
    mode = models.CharField(max_length=15, choices=MODES, blank=True, default="")
    reference = models.CharField(max_length=100, blank=True, default="", help_text="N° de chèque, référence de consignation…")
    recue_le = models.DateField(null=True, blank=True)
    montant_retenu = models.BigIntegerField(default=0)
    motif_retenue = models.TextField(blank=True, default="")
    photos_retenue = models.ManyToManyField("noyau.Fichier", blank=True, related_name="+")
    retenue_proposee_par = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name="+"
    )
    restituee_le = models.DateField(null=True, blank=True)
    cree_le = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-cree_le"]
        constraints = [models.UniqueConstraint(fields=["reservation"], name="caution_unique_par_reservation")]

    def __str__(self) -> str:
        return f"Caution {self.dossier.numero} — {self.get_statut_display()}"

    def sites_concernes(self) -> set[int]:
        return self.reservation.sites_concernes()


class MouvementCaution(models.Model):
    """Journal inaltérable des cautions (CAU-06) : chaque étape y est ajoutée, jamais modifiée."""

    immuable = True

    caution = models.ForeignKey(Caution, on_delete=models.PROTECT, related_name="mouvements")
    action = models.CharField(max_length=30)
    statut_avant = models.CharField(max_length=20)
    statut_apres = models.CharField(max_length=20)
    montant = models.BigIntegerField(default=0)
    motif = models.TextField(blank=True, default="")
    agent = models.CharField(max_length=200)
    le = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["caution", "le", "pk"]

    def __str__(self) -> str:
        return f"{self.action} ({self.statut_avant} → {self.statut_apres})"
