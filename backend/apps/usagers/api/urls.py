from rest_framework.routers import SimpleRouter

from . import views

routeur = SimpleRouter(trailing_slash=False)
routeur.register("usagers/usagers", views.VueUsagers, basename="usagers")
routeur.register("usagers/contacts", views.VueContacts, basename="contacts")
routeur.register("usagers/rattachements", views.VueRattachements, basename="rattachements")
routeur.register("usagers/types-pieces", views.VueTypesPieces, basename="types-pieces")
routeur.register("usagers/pieces", views.VuePieces, basename="pieces")

urlpatterns = routeur.urls
