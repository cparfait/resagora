from rest_framework.routers import SimpleRouter

from . import views

routeur = SimpleRouter(trailing_slash=False)
routeur.register("materiel/catalogue", views.VueMateriels, basename="materiels")
routeur.register("materiel/stocks", views.VueStocks, basename="stocks")
routeur.register("materiel/prets", views.VuePrets, basename="prets-materiel")
routeur.register("materiel/mouvements", views.VueMouvements, basename="mouvements-materiel")
routeur.register("materiel/controles", views.VueControles, basename="controles-materiel")
routeur.register("materiel/pannes", views.VuePannes, basename="pannes-materiel")

urlpatterns = routeur.urls
