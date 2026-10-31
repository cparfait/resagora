from django.urls import path
from rest_framework.routers import SimpleRouter

from . import views

routeur = SimpleRouter(trailing_slash=False)
routeur.register("personnel/agents", views.VueAgents, basename="agents-personnel")
routeur.register("personnel/habilitations", views.VueHabilitations, basename="habilitations-agents")
routeur.register("personnel/types-habilitation", views.VueTypesHabilitation, basename="types-habilitation")
routeur.register("personnel/besoins", views.VueBesoins, basename="besoins")
routeur.register("personnel/vacations", views.VueVacations, basename="vacations")
routeur.register("personnel/trames", views.VueTrames, basename="trames")
routeur.register("personnel/lignes-trame", views.VueLignesTrame, basename="lignes-trame")
routeur.register("personnel/absences", views.VueAbsences, basename="absences")
routeur.register("personnel/incidents", views.VueIncidents, basename="incidents")
routeur.register("personnel/appareils", views.VueAppareils, basename="appareils")
routeur.register("personnel/saisies", views.VueSaisies, basename="saisies-mobiles")

urlpatterns = [
    path("personnel/compteurs", views.VueCompteurs.as_view(), name="compteurs"),
    path("personnel/ical/<str:jeton>.ics", views.VueIcal.as_view(), name="ical"),
    *routeur.urls,
]
