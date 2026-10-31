"""Routes /api/portail/* (canal portail uniquement). Toute route ajoutée ici doit l'être aussi dans
la liste blanche de la façade (facade/facade/routes.py), sinon elle reste injoignable depuis Internet ;
`apps/portail/tests/test_contrat_facade.py` vérifie la correspondance dans les deux sens."""

from django.urls import path

from . import catalogue, vues_comptes, vues_documents, vues_dossiers, vues_publiques, vues_usagers

urlpatterns = [
    # Public
    path("catalogue/sites", catalogue.VueSitesPublics.as_view()),
    path("catalogue/familles", catalogue.VueFamillesPubliques.as_view()),
    path("catalogue/espaces", catalogue.VueEspacesPublics.as_view()),
    path("catalogue/espaces/<int:pk>", catalogue.VueEspacePublic.as_view()),
    path("catalogue/espaces/<int:pk>/photos/<int:photo>", catalogue.VuePhotoPublique.as_view()),
    path("catalogue/espaces/<int:pk>/documents/<int:document>", catalogue.VueDocumentPublic.as_view()),
    path("disponibilites", vues_publiques.VueDisponibilites.as_view()),
    path("accessibilite", vues_publiques.VueAccessibilite.as_view()),
    # Comptes
    path("auth/connexion", vues_comptes.VueConnexion.as_view()),
    path("auth/totp", vues_comptes.VueDefiTotp.as_view()),
    path("auth/deconnexion", vues_comptes.VueDeconnexion.as_view()),
    path("auth/inscription", vues_comptes.VueInscription.as_view()),
    path("auth/confirmation-courriel", vues_comptes.VueConfirmation.as_view()),
    path("auth/mot-de-passe-oublie", vues_comptes.VueMotDePasseOublie.as_view()),
    path("auth/reinitialisation", vues_comptes.VueReinitialisation.as_view()),
    path("auth/invitation", vues_comptes.VueInvitation.as_view()),
    path("compte", vues_comptes.VueCompte.as_view()),
    path("compte/mot-de-passe", vues_comptes.VueMotDePasse.as_view()),
    path("compte/totp", vues_comptes.VueTotpCompte.as_view()),
    path("compte/export", vues_comptes.VueExportCompte.as_view()),
    path("compte/preferences", vues_comptes.VuePreferences.as_view()),
    # Structures, contacts, pièces
    path("usagers", vues_usagers.VueUsagersPortail.as_view()),
    path("usagers/<int:pk>", vues_usagers.VueUsagerPortail.as_view()),
    path("usagers/<int:pk>/contacts", vues_usagers.VueContactsUsager.as_view()),
    path("usagers/<int:pk>/pieces", vues_usagers.VuePiecesUsager.as_view()),
    path("usagers/<int:pk>/pieces/<int:piece>/fichier", vues_usagers.VueFichierPiece.as_view()),
    path("pieces-exigees", vues_usagers.VuePiecesExigees.as_view()),
    path("types-demande", vues_dossiers.VueTypesDemande.as_view()),
    # Demandes et dossiers
    path("dossiers", vues_dossiers.VueDossiersPortail.as_view()),
    path("dossiers/<int:pk>", vues_dossiers.VueDossierPortail.as_view()),
    path("dossiers/<int:pk>/envoyer", vues_dossiers.VueEnvoyerDossier.as_view()),
    path("dossiers/<int:pk>/annuler", vues_dossiers.VueAnnulerDossier.as_view()),
    path("dossiers/<int:pk>/occurrences/<int:seance>/annuler", vues_dossiers.VueAnnulerSeance.as_view()),
    path("dossiers/<int:pk>/messages", vues_dossiers.VueMessagesDossier.as_view()),
    path("dossiers/<int:pk>/pieces", vues_dossiers.VuePiecesDossier.as_view()),
    path("dossiers/<int:pk>/documents", vues_documents.VueDocumentsDossier.as_view()),
    path("dossiers/<int:pk>/documents/<int:document>/fichier", vues_documents.VueFichierDocument.as_view()),
    path("dossiers/<int:pk>/documents/<int:document>/signature", vues_documents.VueSignatureDocument.as_view()),
    path("dossiers/<int:pk>/documents/<int:document>/scan-signe", vues_documents.VueScanSigne.as_view()),
    path("campagnes", vues_dossiers.VueCampagnesPortail.as_view()),
    path("campagnes/<int:pk>/demandes", vues_dossiers.VueDemandeCampagne.as_view()),
    path("notifications", vues_dossiers.VueNotificationsPortail.as_view()),
    path("notifications/<int:pk>/lue", vues_dossiers.VueNotificationLue.as_view()),
    # Rappels des tiers (vérifiés par la façade, revérifiés ici auprès de la source)
    path("webhooks/docuseal", vues_documents.VueWebhookDocuSeal.as_view()),
]
