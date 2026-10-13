"""Écrans des échéances : rubrique du dossier client et échéancier du cabinet."""

from __future__ import annotations

from datetime import timedelta
from typing import Any

from django.contrib import messages
from django.core.paginator import Paginator
from django.http import HttpResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.views.decorators.http import require_POST

from apps.clients.models import Client
from apps.clients.views import open_dossier, render_section
from apps.core import events
from apps.core.http import AppRequest
from apps.core.models import User

from .forms import ManualTaskForm
from .models import MANUAL, Task, TaskStep

UPCOMING_DAYS = 90


def _users() -> list[User]:
    return list(User.objects.filter(is_active=True))


# --- Rubrique « Échéances » du dossier ------------------------------------------------------


def client_tasks(request: AppRequest, pk: int) -> HttpResponse:
    def build(client: Client) -> dict[str, Any]:
        today = timezone.localdate()
        tasks = list(client.tasks.select_related("assignee").prefetch_related("steps"))
        open_tasks = [t for t in tasks if t.is_open]
        horizon = today + timedelta(days=UPCOMING_DAYS)
        closed = sorted(
            (t for t in tasks if not t.is_open),
            key=lambda t: t.completed_at or t.updated_at,
            reverse=True,
        )
        return {
            "overdue": [t for t in open_tasks if t.due_date < today],
            "upcoming": [t for t in open_tasks if today <= t.due_date <= horizon],
            "later": [t for t in open_tasks if t.due_date > horizon],
            "closed": closed[:20],
            "manual_form": ManualTaskForm(),
            "users": _users(),
            "statuses": Task.Status.choices,
        }

    return render_section(request, pk, "tasks", "tasks/client_tasks.html", build)


@require_POST
def add_manual_task(request: AppRequest, pk: int) -> HttpResponse:
    client = open_dossier(request, pk)
    form = ManualTaskForm(request.POST, instance=Task(client=client, kind=MANUAL))
    if form.is_valid():
        form.save()
        messages.success(request, "Échéance ajoutée.")
    else:
        errors = "; ".join(str(e) for errs in form.errors.values() for e in errs)
        messages.error(request, f"Échéance non ajoutée : {errors}")
    return redirect("clients:tasks", pk=client.pk)


# --- Actions sur une tâche (HTMX) -------------------------------------------------------------


def _get_task(request: AppRequest, pk: int) -> Task:
    return get_object_or_404(
        Task.objects.visible_to(request.user).select_related("client", "assignee"), pk=pk
    )


def _respond(request: AppRequest, task: Task, open_steps: bool = False) -> HttpResponse:
    if request.htmx:
        return render(
            request,
            "tasks/_task.html",
            {
                "t": task,
                "users": _users(),
                "statuses": Task.Status.choices,
                "show_client": request.POST.get("avec_client") == "1",
                "open_steps": open_steps,
            },
        )
    return redirect("clients:tasks", pk=task.client_id)


@require_POST
def set_status(request: AppRequest, pk: int) -> HttpResponse:
    task = _get_task(request, pk)
    status = request.POST.get("status", "")
    if status not in Task.Status.values or status == task.status:
        return _respond(request, task)
    was_open = task.is_open
    task.status = status
    if not task.is_open:
        task.completed_at = timezone.now()
        task.completed_by = request.user
    else:
        task.completed_at = None
        task.completed_by = None
    task.save()
    if was_open and status == Task.Status.DONE:
        events.emit("task.completed", subject=task.client, actor=request.user,
                    payload={"task": task.pk, "kind": task.kind})  # fmt: skip
    elif not was_open and task.is_open:
        events.emit("task.reopened", subject=task.client, actor=request.user,
                    payload={"task": task.pk, "kind": task.kind})  # fmt: skip
    return _respond(request, task)


@require_POST
def toggle_step(request: AppRequest, pk: int, step_pk: int) -> HttpResponse:
    task = _get_task(request, pk)
    step = get_object_or_404(TaskStep, pk=step_pk, task=task)
    step.done = not step.done
    step.done_at = timezone.now() if step.done else None
    step.done_by = request.user if step.done else None
    step.save()
    if step.done and task.status == Task.Status.TODO:
        task.status = Task.Status.IN_PROGRESS
        task.save(update_fields=["status", "updated_at"])
    return _respond(request, task, open_steps=True)


@require_POST
def set_assignee(request: AppRequest, pk: int) -> HttpResponse:
    task = _get_task(request, pk)
    value = request.POST.get("assignee", "")
    task.assignee = (
        User.objects.filter(pk=value, is_active=True).first() if value.isdigit() else None
    )
    task.save(update_fields=["assignee", "updated_at"])
    return _respond(request, task)


# --- Échéancier du cabinet --------------------------------------------------------------------

WHEN_CHOICES = (
    ("30", "En retard et 30 prochains jours"),
    ("7", "En retard et 7 prochains jours"),
    ("retard", "En retard uniquement"),
    ("90", "En retard et 90 prochains jours"),
    ("tout", "Toutes les dates"),
)
STATUS_FILTERS = (
    ("ouvertes", "À traiter"),
    ("attente", "En attente du client"),
    ("terminees", "Terminées"),
    ("toutes", "Tous les statuts"),
)


def board(request: AppRequest) -> HttpResponse:
    today = timezone.localdate()
    filters = {
        "qui": request.GET.get("qui", "moi"),
        "quand": request.GET.get("quand", "30"),
        "statut": request.GET.get("statut", "ouvertes"),
        "categorie": request.GET.get("categorie", ""),
        "q": request.GET.get("q", "").strip(),
    }
    tasks = Task.objects.visible_to(request.user).select_related("client", "assignee")
    if filters["qui"] == "moi":
        tasks = tasks.filter(assignee=request.user)
    elif filters["qui"] == "personne":
        tasks = tasks.filter(assignee__isnull=True)
    elif filters["qui"].isdigit():
        tasks = tasks.filter(assignee_id=int(filters["qui"]))
    if filters["statut"] == "ouvertes":
        tasks = tasks.open()
    elif filters["statut"] == "attente":
        tasks = tasks.filter(status=Task.Status.WAITING)
    elif filters["statut"] == "terminees":
        tasks = tasks.filter(status__in=[Task.Status.DONE, Task.Status.NOT_APPLICABLE])
    if filters["quand"] == "retard":
        tasks = tasks.filter(due_date__lt=today)
    elif filters["quand"] in ("7", "30", "90"):
        tasks = tasks.filter(due_date__lte=today + timedelta(days=int(filters["quand"])))
    if filters["categorie"] in Task.Category.values:
        tasks = tasks.filter(category=filters["categorie"])
    if filters["q"]:
        tasks = tasks.filter(client__in=Client.objects.search(filters["q"]))
    tasks = tasks.prefetch_related("steps").order_by("due_date", "client__name")
    page = Paginator(tasks, 100).get_page(request.GET.get("page"))
    mine = Task.objects.visible_to(request.user).filter(assignee=request.user).open()
    context = {
        "page": page,
        "filters": filters,
        "users": _users(),
        "statuses": Task.Status.choices,
        "categories": Task.Category.choices,
        "when_choices": WHEN_CHOICES,
        "status_filters": STATUS_FILTERS,
        "counts": {
            "overdue": mine.filter(due_date__lt=today).count(),
            "week": mine.filter(
                due_date__gte=today, due_date__lte=today + timedelta(days=7)
            ).count(),
            "waiting": mine.filter(status=Task.Status.WAITING).count(),
        },
    }
    if request.htmx and request.htmx.target == "echeances":
        return render(request, "tasks/_board_results.html", context)
    return render(request, "tasks/board.html", context)
