"""« Ma journée » (D-059). Données fictives."""

from datetime import time, timedelta
from html import unescape

import pytest
from django.urls import reverse
from django.utils import timezone

from apps.clients.models import Assignment
from apps.core.testing.factories import ClientFactory, PersonFactory, PortfolioFactory
from apps.documents.models import Document, DocumentRequest
from apps.tasks.models import Task
from apps.timesheet.models import TimeEntry

pytestmark = pytest.mark.django_db


def test_my_day_shows_what_is_ready_and_what_to_do(web, user):
    today = timezone.localdate()
    client = ClientFactory(name="Boulangerie Fictive")
    Assignment.objects.create(client=client, user=user, role=Assignment.Role.MANAGER)
    Task.objects.create(client=client, title="TVA septembre", due_date=today - timedelta(days=3),
                        assignee=user)  # fmt: skip
    person = PersonFactory(name="Fictif", first_name="Anne")
    Document.objects.create(client=client, person=person, case="pieces-identite",
                            title="Carte", review_needed=True, size=1, sha256="0" * 64,
                            content_type="application/pdf", original_name="c.pdf")  # fmt: skip
    TimeEntry.objects.create(user=user, client=client, day=today, start=time(9), end=time(10, 30))
    html = unescape(web.get(reverse("core:today")).content.decode())
    assert "Ma journée" in html and "Prêt à valider" in html
    assert "Carte d'identité reçue — Fictif Anne" in html
    assert "TVA septembre" in html and "en retard de 3 j" in html
    assert "1 h 30" in html  # temps encodé aujourd'hui


def test_my_day_never_shows_hidden_dossiers(web, user):
    secret = ClientFactory(name="Secret Fictif", portfolio=PortfolioFactory(is_private=True))
    Task.objects.create(client=secret, title="Tâche cachée", due_date=timezone.localdate(),
                        assignee=user)  # fmt: skip
    html = web.get(reverse("core:today")).content.decode()
    assert "Tâche cachée" not in html and "Secret Fictif" not in html


def test_overnight_counts(web, user):
    client = ClientFactory()
    Assignment.objects.create(client=client, user=user, role=Assignment.Role.MANAGER)
    DocumentRequest.objects.create(client=client, kind="identity_card", title="Carte",
                                   status="received", closed_at=timezone.now())  # fmt: skip
    html = unescape(web.get(reverse("core:today")).content.decode())
    assert "1 pièce reçue d'un client" in html


def test_empty_day(web):
    assert "Tout est à jour" in web.get(reverse("core:today")).content.decode()
