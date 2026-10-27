"""Automatismes du module TVA."""

from __future__ import annotations

from apps.core import events
from apps.core.models import Event

from .models import VatFiling


@events.on("task.rescheduled")
def follow_task_due_date(event: Event) -> None:
    """Échéance déplacée (nouvelle date légale) : la ligne TVA reliée affiche la même date."""
    from apps.tasks.models import Task

    task_id = (event.payload or {}).get("tache")
    task = Task.objects.filter(pk=int(task_id)).first() if task_id else None
    if task is not None:
        VatFiling.objects.filter(task=task).exclude(due_date=task.due_date).update(
            due_date=task.due_date
        )
