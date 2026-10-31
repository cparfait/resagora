"""Paiement en ligne PayFiP (lot 7, TAR-07, POR-07) : une tentative par passage sur PayFiP, créée avant la
redirection ; seul le résultat relu auprès de PayFiP fait foi, jamais le retour du navigateur. Une tentative n'est
jamais close localement sans résultat de PayFiP : remplacée ou expirée, elle reste relue (ADR 0008)."""

from __future__ import annotations

import uuid

from django.conf import settings
from django.db import models
from django.db.models import Q

#: Une seule tentative « en cours » par facture (contrainte) : en attente de PayFiP ou usager sur PayFiP.
STATUTS_EN_COURS = ("creee", "redirigee")
#: Relues auprès de PayFiP (retour, notification, rapprochement) tant qu'un résultat peut encore arriver.
STATUTS_A_RELIRE = ("creee", "redirigee", "remplacee", "expiree")
#: Résultats définitifs (déclencheur) ; « a_controler » ne se clôt que par un agent, après contrôle.
STATUTS_DEFINITIFS = ("payee", "refusee", "abandonnee", "erreur")


class TentativePaiement(models.Model):
    STATUTS = [
        ("creee", "En préparation"),
        ("redirigee", "En cours sur PayFiP"),
        ("remplacee", "Remplacée par une autre tentative (encore relue)"),
        ("payee", "Payée"),
        ("refusee", "Refusée par la banque"),
        ("abandonnee", "Abandonnée par l'usager"),
        ("expiree", "Sans résultat de PayFiP (encore relue 7 jours)"),
        ("a_controler", "À contrôler par le service financier"),
        ("erreur", "Close sans paiement"),
    ]
    MODES = [("titres", "PayFiP Titres et Rôles"), ("regie", "PayFiP Régie")]
    CONTROLES = [
        ("", "—"),
        ("trop_percu", "Trop-perçu à rembourser"),
        ("doublon_probable", "Déjà encaissé par ailleurs ? À vérifier"),
        ("incoherent", "Résultat PayFiP incohérent"),
        ("resultat_inconnu", "Résultat PayFiP inconnu"),
        ("saisie_test", "Paiement de test hors recette"),
    ]

    uuid = models.UUIDField(default=uuid.uuid4, unique=True, editable=False, help_text="Identifiant public (portail).")
    piece = models.ForeignKey("finances.PieceComptable", on_delete=models.PROTECT, related_name="tentatives_paiement")
    contact = models.ForeignKey("usagers.Contact", null=True, blank=True, on_delete=models.SET_NULL, related_name="+")
    mode = models.CharField(max_length=6, choices=MODES)
    numcli = models.CharField(max_length=10)
    exer = models.CharField(max_length=4)
    refdet = models.CharField(max_length=30)
    objet = models.CharField(max_length=100)
    montant = models.PositiveBigIntegerField(help_text="Montant demandé à PayFiP (centimes).")
    mel = models.EmailField(blank=True, default="", help_text="Effacée à l'anonymisation de l'usager.")
    saisie = models.CharField(max_length=1, help_text="T (test), X (activation) ou W (production).")
    id_op = models.CharField(max_length=64, unique=True, null=True, blank=True)
    statut = models.CharField(max_length=11, choices=STATUTS, default="creee")
    resultrans = models.CharField(max_length=1, blank=True, default="")
    numauto = models.CharField(max_length=20, blank=True, default="")
    paye_le = models.DateTimeField(null=True, blank=True)
    encaissement = models.OneToOneField(
        "finances.Encaissement", null=True, blank=True, on_delete=models.PROTECT, related_name="tentative_payfip"
    )
    trop_percu = models.PositiveBigIntegerField(default=0, help_text="Montant payé au-delà du reste dû.")
    controle = models.CharField(max_length=16, choices=CONTROLES, blank=True, default="")
    erreur = models.CharField(max_length=300, blank=True, default="", help_text="Détail technique (jamais montré à l'usager).")
    cree_le = models.DateTimeField(auto_now_add=True)
    verifiee_le = models.DateTimeField(null=True, blank=True, help_text="Dernière demande de lecture du résultat.")
    notifications = models.PositiveIntegerField(default=0, help_text="Notifications reçues de PayFiP.")
    close_par = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.PROTECT, related_name="+")
    motif_cloture = models.CharField(max_length=300, blank=True, default="")

    class Meta:
        ordering = ["-cree_le"]
        constraints = [
            models.UniqueConstraint(
                fields=["piece"], condition=Q(statut__in=STATUTS_EN_COURS), name="une_tentative_en_cours_par_piece"
            )
        ]

    def __str__(self) -> str:
        return f"Paiement en ligne {self.refdet} ({self.get_statut_display()})"

    @property
    def en_cours(self) -> bool:
        return self.statut in STATUTS_EN_COURS

    def sites_concernes(self) -> set[int]:
        return set(self.piece.dossier.reservations.values_list("espace__batiment__site_id", flat=True))


class RemboursementTropPercu(models.Model):
    """Suivi d'un trop-perçu (ajout seul, RG-13) : remboursé par la Ville (régie) ou par le comptable (titres)."""

    tentative = models.OneToOneField(TentativePaiement, on_delete=models.PROTECT, related_name="remboursement")
    montant = models.PositiveBigIntegerField()
    date = models.DateField()
    reference = models.CharField(max_length=100)
    par = models.CharField(max_length=10, choices=[("ville", "Régie de la Ville"), ("comptable", "Comptable public")])
    agent = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="+")
    cree_le = models.DateTimeField(auto_now_add=True)

    immuable = True

    def __str__(self) -> str:
        return f"Remboursement du trop-perçu {self.tentative.refdet}"
