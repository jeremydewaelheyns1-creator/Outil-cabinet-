"""Sonde de santé, traitée avant tout autre intergiciel.

Les sondes de Cloud Run appellent le conteneur directement en HTTP, avec un nom d'hôte
interne : elles seraient refusées (hôte non autorisé) ou redirigées vers HTTPS. Cette
réponse ne contient aucune donnée.
"""

from collections.abc import Callable

from django.db import connection
from django.http import HttpRequest, HttpResponse, JsonResponse

HEALTH_PATH = "/sante/"


class HealthCheckMiddleware:
    def __init__(self, get_response: Callable[[HttpRequest], HttpResponse]) -> None:
        self.get_response = get_response

    def __call__(self, request: HttpRequest) -> HttpResponse:
        if request.path == HEALTH_PATH and request.method in ("GET", "HEAD"):
            with connection.cursor() as cursor:
                cursor.execute("SELECT 1")
            response = JsonResponse({"status": "ok"})
            response["Cache-Control"] = "no-store"
            return response
        return self.get_response(request)
