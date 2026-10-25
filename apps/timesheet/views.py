"""Écrans de la feuille de temps (D-058) : la semaine en calendrier, et le temps passé sur
un dossier (panneau de gauche du dossier, rubrique Facturation)."""

from __future__ import annotations

from collections import defaultdict
from datetime import timedelta
from typing import Any

from django.contrib import messages
from django.core.exceptions import PermissionDenied
from django.http import HttpResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils import timezone
from django.views.decorators.http import require_POST

from apps.clients.models import Client
from apps.clients.views import render_section
from apps.core.audit import log_access
from apps.core.capabilities import Capability
from apps.core.http import AppRequest
from apps.core.models import AccessLog, User

from . import services
from .forms import TimeEntryForm
from .models import TimeEntry, hours_label


def _person(request: AppRequest) -> User:
    """La feuille affichée : la sienne, ou celle d'un collègue avec le droit « timesheet.all »."""
    wanted = request.GET.get("qui", "")
    if wanted.isdigit() and int(wanted) != request.user.pk:
        if not request.user.has_capability(Capability.TIMESHEET_ALL):
            raise PermissionDenied
        return get_object_or_404(User, pk=int(wanted), is_active=True)
    return request.user


def week(request: AppRequest) -> HttpResponse:
    today = timezone.localdate()
    monday = services.parse_week(request.GET.get("semaine", ""), today)
    person = _person(request)
    mine = person.pk == request.user.pk
    if not mine:
        log_access(
            request, AccessLog.Action.VIEW, person, details={"feuille de temps": str(monday)}
        )
    editing = None
    if mine and request.GET.get("modifier", "").isdigit():
        editing = TimeEntry.objects.filter(
            user=request.user, pk=int(request.GET["modifier"])
        ).first()
    in_week = monday <= today <= monday + timedelta(days=6)
    initial: dict[str, Any] = {"day": today if in_week else monday}
    if request.GET.get("dossier", "").isdigit():
        initial["client"] = int(request.GET["dossier"])
    form = TimeEntryForm(instance=editing, initial=initial, user=request.user)
    context = {
        **services.week(person, monday, today),
        "form": form,
        "editing": editing,
        "person": person,
        "mine": mine,
        "colleagues": (
            User.objects.filter(is_active=True).order_by("first_name", "last_name")
            if request.user.has_capability(Capability.TIMESHEET_ALL)
            else None
        ),
    }
    return render(request, "timesheet/week.html", context)


@require_POST
def save(request: AppRequest) -> HttpResponse:
    entry_id = request.POST.get("entry", "")
    instance = (
        get_object_or_404(TimeEntry, pk=int(entry_id), user=request.user)
        if entry_id.isdigit()
        else TimeEntry(user=request.user)
    )
    form = TimeEntryForm(request.POST, instance=instance, user=request.user)
    if form.is_valid():
        entry = form.save()
        messages.success(
            request, f"Enregistré : {hours_label(entry.minutes)} le {entry.day:%d/%m}."
        )
        target = f"{reverse('temps:week')}?semaine={entry.day:%Y-%m-%d}"
    else:
        errors = "; ".join(str(e) for errs in form.errors.values() for e in errs)
        messages.error(request, f"Rien n'a été enregistré : {errors}")
        target = reverse("temps:week")
    back = request.POST.get("retour", "")
    if back.startswith("/") and "//" not in back:
        return redirect(back)
    return redirect(target)


@require_POST
def delete(request: AppRequest, entry_id: int) -> HttpResponse:
    entry = get_object_or_404(TimeEntry, pk=entry_id, user=request.user)
    day = entry.day
    entry.delete()
    messages.success(request, "Entrée supprimée.")
    back = request.POST.get("retour", "")
    if back.startswith("/") and "//" not in back:
        return redirect(back)
    return redirect(f"{reverse('temps:week')}?semaine={day:%Y-%m-%d}")


def client_time(request: AppRequest, pk: int) -> HttpResponse:
    """Rubrique « Temps passé » du dossier : totaux pour tous ; le détail des lignes de
    collègues seulement avec le droit « timesheet.all »."""

    def build(client: Client) -> dict[str, Any]:
        sees_all = request.user.has_capability(Capability.TIMESHEET_ALL)
        entries = list(client.time_entries.select_related("user").order_by("-day", "-start"))
        by_month: dict[str, int] = defaultdict(int)
        by_activity: dict[str, int] = defaultdict(int)
        for e in entries:
            by_month[f"{e.day:%m/%Y}"] += e.minutes
            by_activity[e.get_activity_display()] += e.minutes
        shown = [e for e in entries if sees_all or e.user_id == request.user.pk][:100]
        total = sum(e.minutes for e in entries)
        billable = sum(e.minutes for e in entries if e.billable)
        return {
            "entries": shown,
            "hidden": sum(1 for e in entries if not (sees_all or e.user_id == request.user.pk)),
            "total": hours_label(total),
            "billable": hours_label(billable),
            "by_month": [(m, hours_label(v)) for m, v in list(by_month.items())[:12]],
            "by_activity": sorted(
                ((a, hours_label(v), v) for a, v in by_activity.items()), key=lambda r: -r[2]
            ),
            "form": TimeEntryForm(
                initial={"day": timezone.localdate(), "client": client.pk}, user=request.user
            ),
        }

    return render_section(request, pk, "time_spent", "timesheet/client_time.html", build)
