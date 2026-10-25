"""Échéances à une date et une heure (D-061) : rendez-vous, rappel, « répondre au SPF »…

Créées à la main dans « Ma journée › Mon agenda » ou depuis un e-mail (clic droit), toujours
liées à un dossier. Elles s'affichent en pointillé dans l'agenda, dans les échéances du dossier
et, le jour J, dans « À traiter ». « Me rappeler le jour J » ajoute une notification dans
l'outil (la cloche) ce jour-là — jamais d'e-mail.
"""

from __future__ import annotations

from datetime import date, time

from django.core.exceptions import ValidationError
from django.urls import reverse
from django.utils import timezone

from apps.clients.models import Client
from apps.core.models import Notification, User

from .models import MANUAL, Task


def add(user: User, *, client: Client, day: date, at: time | None, until: time | None,
        comment: str, remind: bool) -> Task:  # fmt: skip
    comment = comment.strip()[:200]
    if not comment:
        raise ValidationError("Écrivez ce que c'est (ex. : Rendez-vous).")
    if until and not at:
        raise ValidationError("Indiquez aussi l'heure de début.")
    if at and until and until <= at:
        raise ValidationError("L'heure de fin doit venir après l'heure de début.")
    return Task.objects.create(
        client=client, kind=MANUAL, title=comment, due_date=day, due_time=at, end_time=until,
        remind=remind, assignee=user,
    )  # fmt: skip


def send_reminders(today: date | None = None) -> int:
    """Le jour J : une notification par échéance « me rappeler » (une seule fois)."""
    today = today or timezone.localdate()
    due = (
        Task.objects.open()
        .filter(remind=True, reminded_at__isnull=True, due_date=today, assignee__isnull=False)
        .select_related("client", "assignee")
    )
    count = 0
    for task in due:
        if task.assignee is None:
            continue
        hour = f" à {task.due_time:%H:%M}" if task.due_time else ""
        Notification.objects.get_or_create(
            user=task.assignee, key=f"rappel:{task.pk}",
            defaults={"title": f"Rappel{hour} : {task.title}"[:200],
                      "lines": [task.client.display_name],
                      "link": reverse("clients:tasks", args=[task.client_id])},
        )  # fmt: skip
        task.reminded_at = timezone.now()
        task.save(update_fields=["reminded_at", "updated_at"])
        count += 1
    return count
