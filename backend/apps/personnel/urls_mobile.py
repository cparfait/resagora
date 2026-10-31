"""Routes de l'application mobile, montées sur le canal « gestion » (option A) et sur le canal « portail »
(option B) ; chaque vue vérifie à la requête que l'option configurée correspond au canal."""

from django.urls import path

from . import mobile

urlpatterns = [
    path("auth/connexion", mobile.VueConnexionMobile.as_view()),
    path("auth/totp", mobile.VueTotpMobile.as_view()),
    path("auth/deconnexion", mobile.VueDeconnexionMobile.as_view()),
    path("sante", mobile.VueSanteMobile.as_view()),
    path("paquet", mobile.VuePaquet.as_view()),
    path("saisies", mobile.VueSaisies.as_view()),
    path("photos", mobile.VuePhotos.as_view()),
]
