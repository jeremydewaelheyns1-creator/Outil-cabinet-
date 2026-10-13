from typing import Any

from django.conf import settings
from django.http import HttpRequest


def app_context(request: HttpRequest) -> dict[str, Any]:
    return {"CABINET_NAME": settings.CABINET_NAME}
