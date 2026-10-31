"""Canal « portail » : instance mTLS joignable uniquement par la façade DMZ (SEC-01).

Seules les routes /api/portail/* y sont montées (et /api/mobile/* en option B, SEC-10).
"""

from django.urls import include, path

from apps.noyau.views import sante

urlpatterns = [
    path("sante", sante),
    path("api/portail/", include("apps.portail.urls")),
    path("api/mobile/", include("apps.personnel.urls_mobile")),
]
