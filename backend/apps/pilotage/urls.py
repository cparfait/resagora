from django.urls import path

from . import api, vues_impressions

urlpatterns = [
    path("pilotage/a-traiter", api.VueATraiter.as_view(), name="a-traiter"),
    path("pilotage/direction", api.VueDirection.as_view(), name="tableau-direction"),
    path("pilotage/statistiques/occupation", api.VueOccupation.as_view(), name="statistiques-occupation"),
    path("pilotage/statistiques/repartition", api.VueRepartition.as_view(), name="statistiques-repartition"),
    path("pilotage/statistiques/recettes", api.VueRecettes.as_view(), name="statistiques-recettes"),
    path("pilotage/statistiques/personnel", api.VuePersonnel.as_view(), name="statistiques-personnel"),
    path("pilotage/planning.pdf", vues_impressions.VuePlanningPdf.as_view(), name="planning-pdf"),
    path("pilotage/feuille-de-salle.pdf", vues_impressions.VueFeuilleDeSalle.as_view(), name="feuille-de-salle"),
    *vues_impressions.routeur.urls,
]
