"""Connexions, échecs de connexion et déconnexions vont au journal des consultations."""

from typing import Any

from allauth.account.signals import password_reset
from django.contrib.auth.signals import user_logged_in, user_logged_out, user_login_failed
from django.dispatch import receiver
from django.http import HttpRequest

from .audit import log_access
from .models import AccessLog, User


@receiver(user_logged_in)
def on_login(sender: Any, request: HttpRequest, user: User, **kwargs: Any) -> None:
    log_access(request, AccessLog.Action.LOGIN, user=user)


@receiver(user_logged_out)
def on_logout(sender: Any, request: HttpRequest, user: User | None, **kwargs: Any) -> None:
    if user is not None:
        log_access(request, AccessLog.Action.LOGOUT, user=user)


@receiver(user_login_failed)
def on_login_failed(
    sender: Any, credentials: dict[str, Any], request: HttpRequest | None = None, **kwargs: Any
) -> None:
    email = str(credentials.get("email") or credentials.get("username") or "")[:254]
    log_access(
        request,
        AccessLog.Action.LOGIN_FAILED,
        details={"identifiant_saisi": email},
    )


@receiver(password_reset)
def on_password_reset(sender: Any, request: HttpRequest, user: User, **kwargs: Any) -> None:
    """Mot de passe choisi via « mot de passe oublié » (D-081) : tracé, jamais le mot de passe."""
    log_access(request, AccessLog.Action.UPDATE, user, user=user,
               details={"mot de passe": "réinitialisé par lien e-mail"})  # fmt: skip
