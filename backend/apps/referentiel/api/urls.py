from rest_framework.routers import SimpleRouter

from . import views

routeur = SimpleRouter(trailing_slash=False)
routeur.register("referentiel/sites", views.VueSites, basename="sites")
routeur.register("referentiel/batiments", views.VueBatiments, basename="batiments")
routeur.register("referentiel/familles", views.VueFamilles, basename="familles")
routeur.register("referentiel/espaces", views.VueEspaces, basename="espaces")

urlpatterns = routeur.urls
