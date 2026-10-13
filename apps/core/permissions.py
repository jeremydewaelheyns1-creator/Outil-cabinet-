"""Vérification des droits dans les vues."""

from collections.abc import Callable
from functools import wraps
from typing import Any

from django.core.exceptions import PermissionDenied
from django.http import HttpRequest, HttpResponse

from .capabilities import Capability
from .models import User

View = Callable[..., HttpResponse]


def has_capability(request: HttpRequest, capability: Capability) -> bool:
    user = request.user
    return isinstance(user, User) and user.has_capability(capability)


def require_capability(capability: Capability) -> Callable[[View], View]:
    def decorator(view: View) -> View:
        @wraps(view)
        def wrapper(request: HttpRequest, *args: Any, **kwargs: Any) -> HttpResponse:
            if not has_capability(request, capability):
                raise PermissionDenied
            return view(request, *args, **kwargs)

        return wrapper

    return decorator
