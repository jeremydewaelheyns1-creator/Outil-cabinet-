"""Connexions, échecs de connexion et déconnexions vont au journal des consultations."""

from typing import Any

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
