from django.contrib import admin
from django.contrib.auth.views import redirect_to_login
from django.core.exceptions import PermissionDenied
from django.http import HttpRequest, HttpResponse
from django.shortcuts import redirect
from django.urls import include, path, reverse


def admin_login(request: HttpRequest, extra_context: object = None) -> HttpResponse:
    """Remplace l'écran de connexion propre à l'administration.

    Celui de Django ne demande que le mot de passe : il permettrait d'ouvrir une session sans
    second facteur. On renvoie donc toujours vers la connexion de l'application.
    """
    if not request.user.is_authenticated:
        return redirect_to_login(reverse("admin:index"), reverse("account_login"))
    if request.user.is_active and request.user.is_staff:
        return redirect("admin:index")
    raise PermissionDenied


admin.site.login = admin_login  # type: ignore[method-assign]
admin.site.site_header = "Administration"
admin.site.site_title = "Administration"

urlpatterns = [
    path("compte/", include("allauth.urls")),
    path("gestion/", admin.site.urls),
    path("clients/", include("apps.clients.urls")),
    path("bce/", include("apps.bce.urls")),
    path("reprise/", include("apps.reprise.urls")),
    path("echeances/", include("apps.tasks.urls")),
    path("", include("apps.core.urls")),
]
