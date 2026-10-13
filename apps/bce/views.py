"""Recherche dans la copie BCE (utilisée à la création d'un client) et suivi des imports."""

from django.http import HttpResponse
from django.shortcuts import render

from apps.core.capabilities import Capability
from apps.core.http import AppRequest
from apps.core.permissions import require_capability

from . import services
from .models import ImportRun


def search(request: AppRequest) -> HttpResponse:
    query = request.GET.get("q", "")
    hits = services.search(query, request.user) if len(query.strip()) >= 3 else []
    return render(
        request,
        "bce/_search_results.html",
        {"hits": hits, "query": query, "has_data": services.has_data()},
    )


@require_capability(Capability.BCE_IMPORT)
def imports(request: AppRequest) -> HttpResponse:
    return render(request, "bce/imports.html", {"runs": ImportRun.objects.all()[:50]})
