"""Routes /api/portail/* (canal portail uniquement). Toute route ajoutée ici doit l'être aussi dans
la liste blanche de la façade (facade/facade/routes.py), sinon elle reste injoignable depuis Internet."""

from django.urls import path

from . import catalogue

urlpatterns = [
    path("catalogue/sites", catalogue.VueSitesPublics.as_view()),
    path("catalogue/familles", catalogue.VueFamillesPubliques.as_view()),
    path("catalogue/espaces", catalogue.VueEspacesPublics.as_view()),
    path("catalogue/espaces/<int:pk>", catalogue.VueEspacePublic.as_view()),
]
