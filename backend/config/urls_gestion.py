"""Canal « gestion » : API des agents (LAN) et API mobile en option A (SEC-01, SEC-10)."""

from django.urls import include, path
from drf_spectacular.views import SpectacularAPIView
from rest_framework.routers import SimpleRouter

from apps.audit.api import VueJournalAudit
from apps.noyau.api_parametres import VueParametres
from apps.noyau.views import sante

routeur = SimpleRouter(trailing_slash=False)
routeur.register("audit/journal", VueJournalAudit, basename="journal-audit")

gestion = [
    path("", include("apps.habilitations.api.urls")),
    path("", include("apps.referentiel.api.urls")),
    path("", include("apps.comptes.urls")),
    path("", include("apps.usagers.api.urls")),
    path("", include("apps.reservations.api.urls")),
    path("", include("apps.communication.api.urls")),
    path("", include("apps.documents.api.urls")),
    path("", include("apps.finances.api.urls")),
    path("", include("apps.personnel.api.urls")),
    path("", include("apps.materiel.api.urls")),
    path("", include("apps.valorisation.api")),
    path("", include("apps.pilotage.urls")),
    path("", include("apps.paiements.vues_gestion")),
    path("parametres", VueParametres.as_view(), name="parametres"),
    *routeur.urls,
]

urlpatterns = [
    path("sante", sante),
    path("api/gestion/", include(gestion)),
    path("api/mobile/", include("apps.personnel.urls_mobile")),
    path("api/schema/gestion", SpectacularAPIView.as_view(urlconf=[path("api/gestion/", include(gestion))]), name="schema"),
]
