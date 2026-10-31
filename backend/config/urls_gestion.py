"""Canal « gestion » : API des agents (LAN) et API mobile en option A (SEC-01, SEC-10)."""

from django.urls import include, path
from drf_spectacular.views import SpectacularAPIView
from rest_framework.routers import SimpleRouter

from apps.audit.api import VueJournalAudit
from apps.noyau.views import sante

routeur = SimpleRouter(trailing_slash=False)
routeur.register("audit/journal", VueJournalAudit, basename="journal-audit")

gestion = [
    path("", include("apps.habilitations.api.urls")),
    path("", include("apps.referentiel.api.urls")),
    *routeur.urls,
]

urlpatterns = [
    path("sante", sante),
    path("api/gestion/", include(gestion)),
    path("api/schema/gestion", SpectacularAPIView.as_view(urlconf=[path("api/gestion/", include(gestion))]), name="schema"),
]
