"""Accueil, journal des consultations, santé du service."""

from django.contrib.auth.decorators import login_not_required
from django.core.paginator import Paginator
from django.db import connection
from django.http import HttpRequest, HttpResponse, JsonResponse
from django.shortcuts import render
from django.views.decorators.cache import never_cache
from django.views.decorators.http import require_GET

from apps.clients.models import Client

from .capabilities import Capability
from .http import AppRequest
from .models import AccessLog, Event
from .permissions import require_capability


def home(request: AppRequest) -> HttpResponse:
    clients = Client.objects.visible_to(request.user)
    context = {
        "counts": {
            "active": clients.filter(status=Client.Status.ACTIVE).count(),
            "prospect": clients.filter(status=Client.Status.PROSPECT).count(),
            "companies": clients.filter(
                status=Client.Status.ACTIVE, kind=Client.Kind.COMPANY
            ).count(),
            "persons": clients.filter(status=Client.Status.ACTIVE, kind=Client.Kind.PERSON).count(),
        },
        "bce_alerts": clients.filter(status=Client.Status.ACTIVE)
        .exclude(bce_juridical_situation="")
        .order_by("name")[:10],
        "bce_missing": clients.filter(status=Client.Status.ACTIVE, bce_status="absent").order_by(
            "name"
        )[:10],
        "my_clients": clients.filter(assignments__user=request.user)
        .distinct()
        .order_by("name")[:10],
        "failed_events": Event.objects.filter(status=Event.Status.FAILED).count()
        if request.user.is_superuser
        else 0,
    }
    return render(request, "core/home.html", context)


@require_capability(Capability.AUDIT_VIEW)
def access_log(request: AppRequest) -> HttpResponse:
    entries = AccessLog.objects.select_related("user")
    action = request.GET.get("action", "")
    who = request.GET.get("qui", "").strip()
    what = request.GET.get("objet", "").strip()
    if action in AccessLog.Action.values:
        entries = entries.filter(action=action)
    if who:
        entries = entries.filter(user_email__icontains=who)
    if what:
        entries = entries.filter(object_repr__icontains=what)
    page = Paginator(entries, 100).get_page(request.GET.get("page"))
    return render(
        request,
        "core/access_log.html",
        {
            "page": page,
            "actions": AccessLog.Action.choices,
            "filters": {"action": action, "qui": who, "objet": what},
        },
    )


@login_not_required
@never_cache
@require_GET
def health(request: HttpRequest) -> JsonResponse:
    """Sonde de santé pour Cloud Run : l'application répond et la base aussi."""
    with connection.cursor() as cursor:
        cursor.execute("SELECT 1")
    return JsonResponse({"status": "ok"})
