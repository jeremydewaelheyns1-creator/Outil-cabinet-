"""Accueil et journal des consultations (la sonde de santé est dans `health.py`)."""

from django.core.exceptions import PermissionDenied
from django.core.paginator import Paginator
from django.http import HttpResponse
from django.shortcuts import render
from django.utils import timezone

from apps.clients.models import Client

from .capabilities import Capability
from .http import AppRequest
from .models import AccessLog, Event, Notification
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


def settings_page(request: AppRequest) -> HttpResponse:
    """Outils d'administration, regroupés hors du menu quotidien."""
    tools = [
        (
            "Reprise FID-Manager",
            "Importer les clients depuis l'export Excel de FID-Manager (au démarrage).",
            "reprise:index",
            request.user.has_capability(Capability.REPRISE_IMPORT),
        ),
        (
            "Données BCE",
            "Suivi des mises à jour des données publiques des entreprises.",
            "bce:imports",
            request.user.has_capability(Capability.BCE_IMPORT),
        ),
        (
            "Journal des consultations",
            "Qui a ouvert, modifié ou exporté quoi (obligation anti-blanchiment et RGPD).",
            "core:access_log",
            request.user.has_capability(Capability.AUDIT_VIEW),
        ),
        (
            "Comptes et droits",
            "Créer les comptes des collègues, leurs profils et les portefeuilles.",
            "admin:index",
            request.user.is_staff,
        ),
    ]
    allowed = [(title, text, url) for title, text, url, ok in tools if ok]
    if not allowed:
        raise PermissionDenied
    return render(request, "core/settings.html", {"tools": allowed})


def notifications(request: AppRequest) -> HttpResponse:
    """Les notifications de l'employé ; les ouvrir les marque comme lues."""
    items = list(Notification.objects.filter(user=request.user)[:50])
    unread = [n.pk for n in items if n.read_at is None]
    response = render(request, "core/notifications.html", {"items": items, "unread": unread})
    Notification.objects.filter(pk__in=unread).update(read_at=timezone.now())
    return response
