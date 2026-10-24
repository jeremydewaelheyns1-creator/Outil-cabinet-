from typing import Any

from django.conf import settings
from django.http import HttpRequest


def app_context(request: HttpRequest) -> dict[str, Any]:
    context: dict[str, Any] = {"CABINET_NAME": settings.CABINET_NAME}
    user = getattr(request, "user", None)
    if user is not None and user.is_authenticated:
        context["unread_notifications"] = user.notifications.filter(read_at__isnull=True).count()
    return context
