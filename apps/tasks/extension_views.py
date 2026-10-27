"""Délais prolongés par le SPF : écran des administrateurs et message à l'ouverture (D-089)."""

from __future__ import annotations

from datetime import date

from django.conf import settings
from django.contrib import messages
from django.core.exceptions import PermissionDenied
from django.http import HttpResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.utils.http import url_has_allowed_host_and_scheme
from django.views.decorators.http import require_POST

from apps.core.http import AppRequest

from . import extensions
from .models import DeadlineExtension, DeadlineNotice


def _id(value: str | None) -> int:
    return int(value) if value and value.isdigit() else 0


def _staff(request: AppRequest) -> None:
    if not request.user.is_staff:
        raise PermissionDenied


def extensions_page(request: AppRequest) -> HttpResponse:
    """Articles à vérifier, prolongations encodées, encodage (manuel ou depuis un article)."""
    _staff(request)
    if request.method == "POST":
        return _post(request)
    notice = DeadlineNotice.objects.filter(pk=_id(request.GET.get("article"))).first()
    return render(
        request,
        "tasks/extensions.html",
        {
            "notices": DeadlineNotice.objects.filter(status=DeadlineNotice.Status.NEW),
            "notice": notice,
            "done_notices": DeadlineNotice.objects.exclude(status=DeadlineNotice.Status.NEW)[:10],
            "extensions": DeadlineExtension.objects.select_related("created_by"),
            "deadlines": extensions.deadlines(),
            "sources": settings.DEADLINE_SOURCES,
        },
    )


def _post(request: AppRequest) -> HttpResponse:
    action = request.POST.get("action")
    if action == "dismiss":
        dismissed = get_object_or_404(DeadlineNotice, pk=_id(request.POST.get("article")))
        dismissed.status = DeadlineNotice.Status.DISMISSED
        dismissed.handled_by, dismissed.handled_at = request.user, timezone.now()
        dismissed.save(update_fields=["status", "handled_at", "handled_by"])
        messages.success(request, "Article écarté.")
    elif action == "cancel":
        extension = get_object_or_404(DeadlineExtension, pk=_id(request.POST.get("prolongation")))
        moved = extensions.cancel(extension, user=request.user)
        messages.success(
            request, f"Prolongation annulée : {moved} échéance(s) remises à leur date."
        )
    elif action == "create":
        deadline = extensions.find(request.POST.get("echeance", ""))
        try:
            new_date = date.fromisoformat(request.POST.get("nouvelle_date", ""))
        except ValueError:
            new_date = None
        notice = DeadlineNotice.objects.filter(pk=_id(request.POST.get("article"))).first()
        if deadline is None or new_date is None:
            messages.error(request, "Choisissez l'échéance et la nouvelle date.")
        elif DeadlineExtension.objects.filter(
            kind=deadline.kind, period_key=deadline.period_key, previous_date=deadline.due_date
        ).exists():
            messages.error(request, "Cette échéance a déjà une prolongation.")
        else:
            try:
                extension = extensions.create(
                    deadline, new_date, user=request.user, note=request.POST.get("note", ""),
                    source_url=request.POST.get("source", "")
                    or (notice.url if notice is not None else ""),
                    notice=notice,
                )  # fmt: skip
            except ValueError as error:
                messages.error(request, str(error))
            else:
                messages.success(
                    request,
                    f"Prolongation enregistrée : {extension.label} le "
                    f"{extension.new_date:%d/%m/%Y} ({deadline.count} dossier(s)). Chacun verra "
                    "le message à sa prochaine ouverture de l'outil.",
                )
    return redirect("tasks:extensions")


@require_POST
def extension_seen(request: AppRequest, pk: int) -> HttpResponse:
    """« Compris » : le message ne revient plus pour cette personne."""
    extension = get_object_or_404(DeadlineExtension, pk=pk)
    extension.seen_by.add(request.user)
    back = request.POST.get("next", "")
    if not url_has_allowed_host_and_scheme(back, {request.get_host()}, request.is_secure()):
        back = "/"
    if request.htmx:
        return HttpResponse("")
    return redirect(back)
