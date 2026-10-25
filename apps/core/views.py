"""Accueil et journal des consultations (la sonde de santé est dans `health.py`)."""

from django.core.exceptions import PermissionDenied
from django.core.paginator import Paginator
from django.http import HttpResponse
from django.shortcuts import redirect, render
from django.urls import reverse
from django.utils import timezone
from django.views.decorators.http import require_POST

from apps.clients.models import Client

from .capabilities import Capability
from .http import AppRequest
from .models import AccessLog, Event, Notification
from .permissions import require_capability


def _compliance(request: AppRequest) -> dict[str, int]:
    from apps.documents.compliance import summary_for

    return summary_for(request.user)


def home(request: AppRequest) -> HttpResponse:
    """« Ma journée » (D-059) : ce qui est prêt à valider, à faire, et ce qui s'est fait seul."""
    from . import today

    clients = Client.objects.visible_to(request.user)
    context = {
        **today.build(request.user),
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
        "compliance": _compliance(request),
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


def my_agenda(request: AppRequest) -> HttpResponse:
    """« Ma journée » › Mon agenda : la journée heure par heure, on y ajoute son temps."""
    from datetime import date as _date

    from apps.timesheet import services as timesheet
    from apps.timesheet.forms import TimeEntryForm
    from apps.timesheet.models import TimeEntry

    today = timezone.localdate()
    try:
        day = _date.fromisoformat(request.GET.get("jour", ""))
    except ValueError:
        day = today
    editing = None
    if request.GET.get("modifier", "").isdigit():
        editing = TimeEntry.objects.filter(
            user=request.user, pk=int(request.GET["modifier"])
        ).first()
    initial: dict[str, object] = {"day": day}
    if request.GET.get("dossier", "").isdigit():
        initial["client"] = int(request.GET["dossier"])
    if request.GET.get("texte"):
        initial["description"] = request.GET["texte"][:200]
    form = TimeEntryForm(instance=editing, initial=initial, user=request.user)
    visible = Client.objects.visible_to(request.user).exclude(status=Client.Status.FORMER)
    context = {
        **timesheet.day_view(request.user, day, today),
        **timesheet.deadlines_of(request.user, day),
        "form": form,
        "editing": editing,
        "today": today,
        "mode": "echeance" if request.GET.get("ajouter") == "echeance" else "temps",
        "deadline_clients": visible.order_by("name", "first_name"),
        "reminders": timesheet.reminders_today(request.user, today),
    }
    return render(request, "core/agenda.html", context)


@require_POST
def agenda_deadline(request: AppRequest) -> HttpResponse:
    """« Créer une échéance » depuis l'agenda (D-061)."""
    from datetime import date as _date
    from datetime import time as _time

    from django.contrib import messages
    from django.core.exceptions import ValidationError

    from apps.tasks import deadlines

    back = f"{reverse('core:agenda')}?jour={request.POST.get('jour', '')}"
    client = (
        Client.objects.visible_to(request.user).filter(pk=request.POST.get("dossier") or 0).first()
    )
    try:
        if client is None:
            raise ValidationError("Choisissez le dossier.")
        day = _date.fromisoformat(request.POST.get("jour", ""))
        at = _time.fromisoformat(request.POST["heure"]) if request.POST.get("heure") else None
        until = _time.fromisoformat(request.POST["fin"]) if request.POST.get("fin") else None
        deadlines.add(request.user, client=client, day=day, at=at, until=until,
                      comment=request.POST.get("commentaire", ""),
                      remind=request.POST.get("rappel") == "1")  # fmt: skip
    except (ValidationError, ValueError) as error:
        text = " ".join(error.messages) if isinstance(error, ValidationError) else "Date invalide."
        messages.error(request, f"Échéance non créée : {text}")
        return redirect(f"{back}&ajouter=echeance")
    messages.success(request, "Échéance ajoutée.")
    return redirect(back)
