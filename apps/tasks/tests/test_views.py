"""Écrans des échéances."""

from datetime import date, timedelta

import pytest
from django.urls import reverse
from django.utils import timezone

from apps.core.models import Event
from apps.core.testing.factories import ClientFactory, PortfolioFactory
from apps.tasks.models import Task, TaskStep

pytestmark = pytest.mark.django_db


def make_task(client=None, days=5, **fields):
    task = Task.objects.create(
        client=client or ClientFactory(),
        title=fields.pop("title", "Déclaration TVA fictive"),
        due_date=timezone.localdate() + timedelta(days=days),
        category="tva",
        **fields,
    )
    TaskStep.objects.create(task=task, label="Encodage", position=0)
    TaskStep.objects.create(task=task, label="Contrôle", position=1)
    return task


def test_dossier_section_groups_tasks(web):
    client = ClientFactory()
    make_task(client, days=-3, title="Tâche en retard")
    make_task(client, days=10, title="Tâche à venir")
    make_task(client, days=200, title="Tâche lointaine")
    html = web.get(reverse("clients:tasks", args=[client.pk])).content.decode()
    assert "En retard" in html and "en retard de 3 j" in html
    assert "Tâche à venir" in html and "Plus tard (1)" in html
    summary = web.get(reverse("clients:detail", args=[client.pk])).content.decode()
    assert "1 échéance en retard" in summary


def test_complete_and_reopen_task(web, user):
    task = make_task()
    response = web.post(
        reverse("tasks:status", args=[task.pk]), {"status": "done"}, HTTP_HX_REQUEST="true"
    )
    assert response.status_code == 200 and "terminée" in response.content.decode()
    task.refresh_from_db()
    assert task.status == "done" and task.completed_by == user
    assert Event.objects.filter(type="task.completed").exists()
    web.post(reverse("tasks:status", args=[task.pk]), {"status": "todo"})
    task.refresh_from_db()
    assert task.completed_at is None
    assert Event.objects.filter(type="task.reopened").exists()


def test_checking_a_step_starts_the_task(web, user):
    task = make_task()
    step = task.steps.first()
    response = web.post(reverse("tasks:step", args=[task.pk, step.pk]), HTTP_HX_REQUEST="true")
    assert "1/2 étapes" in response.content.decode()
    step.refresh_from_db()
    task.refresh_from_db()
    assert step.done and step.done_by == user
    assert task.status == Task.Status.IN_PROGRESS


def test_assignee_and_board_filters(web, user):
    mine = make_task(title="La mienne", assignee=user)
    make_task(title="Celle du voisin", days=2)
    make_task(title="Trop lointaine", days=120, assignee=user)
    html = web.get(reverse("tasks:board")).content.decode()
    assert "La mienne" in html and "Celle du voisin" not in html and "Trop lointaine" not in html
    html = web.get(reverse("tasks:board"), {"qui": "tous"}).content.decode()
    assert "Celle du voisin" in html
    web.post(reverse("tasks:assignee", args=[mine.pk]), {"assignee": ""})
    mine.refresh_from_db()
    assert mine.assignee is None


def test_private_portfolio_tasks_are_invisible(web):
    secret_client = ClientFactory(portfolio=PortfolioFactory(is_private=True))
    task = make_task(secret_client, title="Tâche secrète")
    assert "Tâche secrète" not in web.get(reverse("tasks:board"), {"qui": "tous"}).content.decode()
    assert web.post(reverse("tasks:status", args=[task.pk]), {"status": "done"}).status_code == 404


def test_manual_task(web):
    client = ClientFactory()
    response = web.post(
        reverse("tasks:add", args=[client.pk]),
        {"title": "Rappeler le client", "due_date": (date.today() + timedelta(days=3)).isoformat(),
         "category": "autre"},
    )  # fmt: skip
    assert response.url == reverse("clients:tasks", args=[client.pk])
    task = client.tasks.get()
    assert task.kind == "manual" and not task.generated
