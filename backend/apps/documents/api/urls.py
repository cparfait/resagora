from rest_framework.routers import SimpleRouter

from . import views

routeur = SimpleRouter(trailing_slash=False)
routeur.register("documents/modeles", views.VueModelesDocuments, basename="modeles-documents")
routeur.register("documents/lots", views.VueLots, basename="lots-documents")
routeur.register("documents/documents", views.VueDocuments, basename="documents")

urlpatterns = routeur.urls
