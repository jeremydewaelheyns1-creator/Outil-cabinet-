"""Génération des échéances : sans doublon, et qui suit les changements de la fiche."""

from datetime import date

import pytest

from apps.clients.models import Assignment
from apps.core.testing.factories import ClientFactory, UserFactory
from apps.tasks.generator import generate_all, generate_all_if_due, generate_for_client
from apps.tasks.models import Task

pytestmark = pytest.mark.django_db

TODAY = date(2026, 10, 13)


def quarterly_company(**fields):
    defaults = {
        "vat_status": "subject",
        "vat_periodicity": "quarterly",
        "fiscal_year_end_month": 12,
        "fiscal_year_end_day": 31,
    }
    defaults.update(fields)
    return ClientFactory(**defaults)


def kinds(client):
    return sorted(set(client.tasks.values_list("kind", flat=True)))


def test_generation_creates_expected_tasks_once():
    client = quarterly_company()
    result = generate_for_client(client, TODAY)
    assert result.created > 0
    assert kinds(client) == [
        "assemblee_generale", "comptes_annuels", "isoc", "listing_clients_tva", "tva_trimestrielle"
    ]  # fmt: skip
    q3 = client.tasks.get(kind="tva_trimestrielle", period_key="2026-T3")
    assert q3.due_date == date(2026, 10, 20)
    assert q3.steps.count() == 5
    # Fenêtre : rien avant 60 jours en arrière, rien au-delà d'environ 12 mois.
    assert not client.tasks.filter(due_date__lt=date(2026, 8, 14)).exists()
    assert not client.tasks.filter(due_date__gt=date(2027, 10, 31)).exists()
    again = generate_for_client(client, TODAY)
    assert again.created == 0


def test_changing_periodicity_replaces_future_untouched_tasks_only():
    client = quarterly_company()
    generate_for_client(client, TODAY)
    started = client.tasks.get(kind="tva_trimestrielle", period_key="2026-T3")
    started.status = Task.Status.IN_PROGRESS
    started.save()
    client.vat_periodicity = "monthly"
    client.save()
    result = generate_for_client(client, TODAY)
    assert result.removed > 0
    remaining = client.tasks.filter(kind="tva_trimestrielle")
    assert list(remaining) == [started]  # le travail commencé n'est jamais perdu
    assert client.tasks.filter(kind="tva_mensuelle", period_key="2026-10").exists()


def test_former_client_loses_future_tasks():
    client = quarterly_company()
    generate_for_client(client, TODAY)
    client.status = "former"
    client.save()
    generate_for_client(client, TODAY)
    assert not client.tasks.filter(due_date__gte=TODAY).exists()


def test_assignee_comes_from_the_dossier_team_and_follows_changes(
    django_capture_on_commit_callbacks,
):
    manager, assistant, newcomer = UserFactory(), UserFactory(), UserFactory()
    client = quarterly_company()
    Assignment.objects.create(client=client, user=manager, role="manager")
    Assignment.objects.create(client=client, user=assistant, role="assistant")
    generate_for_client(client, TODAY)
    assert client.tasks.get(kind="tva_trimestrielle", period_key="2026-T3").assignee == assistant
    assert client.tasks.filter(kind="isoc").first().assignee == manager

    from apps.core import events

    Assignment.objects.filter(client=client, role="assistant").update(user=newcomer)
    with django_capture_on_commit_callbacks(execute=True):
        events.emit("client.team_changed", subject=client)
    assert client.tasks.get(kind="tva_trimestrielle", period_key="2026-T3").assignee == newcomer


def test_client_events_trigger_generation(django_capture_on_commit_callbacks):
    from apps.core import events

    client = quarterly_company()
    with django_capture_on_commit_callbacks(execute=True):
        events.emit("client.created", subject=client)
    assert client.tasks.exists()


def test_generate_all_runs_once_a_day():
    quarterly_company()
    run = generate_all()
    assert run.created > 0 and run.clients == 1
    assert generate_all_if_due() is None
