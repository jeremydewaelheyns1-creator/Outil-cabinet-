from django.contrib import admin
from django.contrib.auth.decorators import login_required
from django.urls import include, path

# L'administration passe par la même connexion que l'application (double authentification
# comprise) : on remplace l'écran de connexion propre à l'admin.
admin.site.login = login_required(admin.site.login)  # type: ignore[method-assign]
admin.site.site_header = "Administration"
admin.site.site_title = "Administration"

urlpatterns = [
    path("compte/", include("allauth.urls")),
    path("gestion/", admin.site.urls),
    path("clients/", include("apps.clients.urls")),
    path("bce/", include("apps.bce.urls")),
    path("reprise/", include("apps.reprise.urls")),
    path("", include("apps.core.urls")),
]
