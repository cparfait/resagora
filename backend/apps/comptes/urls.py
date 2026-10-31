from rest_framework.routers import SimpleRouter

from .api import VueComptes

routeur = SimpleRouter(trailing_slash=False)
routeur.register("usagers/comptes", VueComptes, basename="comptes-portail")

urlpatterns = routeur.urls
