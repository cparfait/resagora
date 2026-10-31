from django.urls import path
from rest_framework.routers import SimpleRouter

from . import views

routeur = SimpleRouter(trailing_slash=False)
routeur.register("reservations/types", views.VueTypesReservation, basename="types-reservation")
routeur.register("reservations/dossiers", views.VueDossiers, basename="dossiers")
routeur.register("reservations/reservations", views.VueReservations, basename="reservations")
routeur.register("reservations/seances", views.VueOccurrences, basename="seances")
routeur.register("reservations/campagnes", views.VueCampagnes, basename="campagnes")
routeur.register("reservations/liste-attente", views.VueListeAttente, basename="liste-attente")
routeur.register("reservations/vues", views.VueVuesEnregistrees, basename="vues-planning")

urlpatterns = [path("reservations/planning", views.VuePlanning.as_view(), name="planning"), *routeur.urls]
