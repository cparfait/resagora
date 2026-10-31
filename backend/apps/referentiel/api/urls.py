from rest_framework.routers import SimpleRouter

from . import views, vues_saison

routeur = SimpleRouter(trailing_slash=False)
routeur.register("referentiel/sites", views.VueSites, basename="sites")
routeur.register("referentiel/batiments", views.VueBatiments, basename="batiments")
routeur.register("referentiel/familles", views.VueFamilles, basename="familles")
routeur.register("referentiel/espaces", views.VueEspaces, basename="espaces")
routeur.register("referentiel/saisons", vues_saison.VueSaisons, basename="saisons")
routeur.register("referentiel/periodes", vues_saison.VuePeriodes, basename="periodes")
routeur.register("referentiel/horaires", vues_saison.VueHoraires, basename="horaires")
routeur.register("referentiel/fermetures", vues_saison.VueFermetures, basename="fermetures")
routeur.register("referentiel/photos", vues_saison.VuePhotos, basename="photos")
routeur.register("referentiel/documents", vues_saison.VueDocumentsEspace, basename="documents-espace")

urlpatterns = routeur.urls
