from django.urls import path
from rest_framework.routers import SimpleRouter

from . import views

routeur = SimpleRouter(trailing_slash=False)
routeur.register("admin/roles", views.VueRoles, basename="roles")
routeur.register("admin/perimetres", views.VuePerimetres, basename="perimetres")
routeur.register("admin/groupes-ad", views.VueGroupesAD, basename="groupes-ad")
routeur.register("admin/habilitations", views.VueHabilitations, basename="habilitations")
routeur.register("admin/agents", views.VueUtilisateurs, basename="agents")

urlpatterns = [
    path("auth/csrf", views.VueCsrf.as_view(), name="csrf"),
    path("auth/connexion", views.VueConnexion.as_view(), name="connexion"),
    path("auth/deconnexion", views.VueDeconnexion.as_view(), name="deconnexion"),
    path("auth/totp", views.VueTotp.as_view(), name="totp"),
    path("auth/totp/enrolement", views.VueEnrolementTotp.as_view(), name="totp-enrolement"),
    path("moi", views.VueMoi.as_view(), name="moi"),
    path("admin/actions", views.VueCatalogueActions.as_view(), name="actions"),
    *routeur.urls,
]
