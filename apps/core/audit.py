"""Écriture dans le journal des consultations."""

from __future__ import annotations

from typing import Any

from django.conf import settings
from django.db import models
from django.http import HttpRequest

from .models import AccessLog, User


def client_ip(request: HttpRequest | None) -> str | None:
    """Adresse IP du visiteur.

    Derrière Google Cloud, chaque relais ajoute l'adresse qu'il voit à la fin de
    X-Forwarded-For. Le début de l'en-tête peut être falsifié par le visiteur : on ne lit donc
    que l'entrée ajoutée par le dernier relais de confiance (TRUSTED_PROXY_COUNT).
    """
    if request is None:
        return None
    proxies: int = settings.TRUSTED_PROXY_COUNT
    forwarded = str(request.META.get("HTTP_X_FORWARDED_FOR", ""))
    if proxies > 0 and forwarded:
        parts = [part.strip() for part in forwarded.split(",") if part.strip()]
        if len(parts) >= proxies:
            return parts[-proxies]
    remote = request.META.get("REMOTE_ADDR")
    return str(remote) if remote else None


def log_access(
    request: HttpRequest | None,
    action: AccessLog.Action,
    obj: models.Model | None = None,
    *,
    user: User | None = None,
    details: dict[str, Any] | None = None,
    object_type: str = "",
    object_repr: str = "",
) -> AccessLog:
    if user is None and request is not None and isinstance(request.user, User):
        user = request.user
    if obj is not None:
        object_type = object_type or obj._meta.label_lower
        object_repr = object_repr or str(obj)
    return AccessLog.objects.create(
        user=user,
        user_email=user.email if user else "",
        action=action,
        object_type=object_type,
        object_id=str(obj.pk) if obj is not None else "",
        object_repr=object_repr[:255],
        ip_address=client_ip(request),
        details=details or {},
    )
