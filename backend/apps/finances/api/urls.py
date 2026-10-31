from django.urls import path
from rest_framework.routers import SimpleRouter

from . import views

routeur = SimpleRouter(trailing_slash=False)
routeur.register("finances/grilles", views.VueGrilles, basename="grilles")
routeur.register("finances/tarifs", views.VueTarifs, basename="tarifs")
routeur.register("finances/majorations", views.VueMajorations, basename="majorations")
routeur.register("finances/prestations", views.VuePrestations, basename="prestations")
routeur.register("finances/reductions", views.VueReductions, basename="reductions")
routeur.register("finances/pieces", views.VuePieces, basename="pieces")
routeur.register("finances/lots-titres", views.VueLotsTitres, basename="lots-titres")
routeur.register("finances/imports-encaissements", views.VueImportsEncaissements, basename="imports-encaissements")
routeur.register("finances/cautions", views.VueCautions, basename="cautions")
routeur.register("finances/etats-des-lieux", views.VueEtatsDesLieux, basename="etats-des-lieux")

urlpatterns = [path("finances/simulation", views.VueSimulationGestion.as_view(), name="simulation-gestion"), *routeur.urls]
