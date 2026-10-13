"""Double authentification obligatoire.

Un utilisateur connecté qui n'a encore configuré aucun second facteur (application
d'authentification ou clé d'accès) est renvoyé vers l'écran de configuration, quel que soit
l'écran demandé. Seuls les écrans nécessaires à cette configuration restent accessibles.
"""

from collections.abc import Callable

from allauth.mfa.utils import is_mfa_enabled
from django.conf import settings
from django.contrib import messages
from django.http import HttpRequest, HttpResponse
from django.shortcuts import redirect
from django.urls import reverse

ALLOWED_URL_NAMES = (
    "mfa_index",
    "mfa_activate_totp",
    "mfa_add_webauthn",
    "mfa_view_recovery_codes",
    "mfa_generate_recovery_codes",
    "mfa_download_recovery_codes",
    "mfa_reauthenticate",
    "account_logout",
    "account_reauthenticate",
)


class RequireMFAMiddleware:
    def __init__(self, get_response: Callable[[HttpRequest], HttpResponse]) -> None:
        self.get_response = get_response
        self._allowed_paths: tuple[str, ...] | None = None

    def allowed_paths(self) -> tuple[str, ...]:
        if self._allowed_paths is None:
            self._allowed_paths = (
                *(reverse(name) for name in ALLOWED_URL_NAMES),
                settings.STATIC_URL,
            )
        return self._allowed_paths

    def __call__(self, request: HttpRequest) -> HttpResponse:
        user = request.user
        if (
            user.is_authenticated
            and not request.path.startswith(self.allowed_paths())
            and not is_mfa_enabled(user)
        ):
            messages.info(
                request,
                "Pour protéger les données des clients, la double authentification est "
                "obligatoire : activez une application d'authentification ou une clé d'accès.",
            )
            return redirect("mfa_index")
        return self.get_response(request)
