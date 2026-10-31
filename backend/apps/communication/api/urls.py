from django.urls import path
from rest_framework.routers import SimpleRouter

from . import views

routeur = SimpleRouter(trailing_slash=False)
routeur.register("communication/modeles", views.VueModelesMessages, basename="modeles-messages")
routeur.register("communication/envois", views.VueJournalEnvois, basename="envois")
routeur.register("communication/messages", views.VueMessages, basename="messages")

urlpatterns = [
    path("communication/envois-groupes", views.VueEnvoiGroupe.as_view(), name="envois-groupes"),
    *routeur.urls,
]
