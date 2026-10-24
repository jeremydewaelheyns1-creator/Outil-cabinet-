"""Rappels de la carte d'identité et avertissement « sans réponse » (D-055)."""

from datetime import timedelta

import pytest
from django.urls import reverse
from django.utils import timezone

from apps.clients.models import Assignment
from apps.documents import identity, services
from apps.documents.models import DocumentRequest, IdentityCard
from apps.documents.tests.test_documents import company_with_manager

pytestmark = pytest.mark.django_db


def expiring_card_request():
    company, person = company_with_manager()
    today = timezone.localdate()
    expiry = today + timedelta(days=15)
    IdentityCard.objects.create(person=person, valid_until=expiry, source="manual")
    assert identity.request_renewals() == 1  # 15 jours avant l'expiration
    return company, DocumentRequest.objects.get(kind="identity_card"), expiry


def test_card_reminders_15_and_30_days_after_expiry_then_manager_alerted():
    company, request, expiry = expiring_card_request()
    assert request.next_reminder_on == expiry + timedelta(days=15)
    assert request.link_expires_at.date() >= expiry + timedelta(days=15)  # lien encore valable
    assert services.send_due_reminders(expiry + timedelta(days=14)) == 0
    assert services.send_due_reminders(expiry + timedelta(days=15)) == 1
    request.refresh_from_db()
    assert request.next_reminder_on == expiry + timedelta(days=30)
    assert services.send_due_reminders(expiry + timedelta(days=30)) == 1
    request.refresh_from_db()
    assert request.reminders_sent == 2
    assert request.next_reminder_on == expiry + timedelta(days=45)  # 15 jours après le rappel
    assert request.link_expires_at.date() >= expiry + timedelta(days=45)
    assert services.send_due_reminders(expiry + timedelta(days=45)) == 0  # plus de rappel
    assert not services.unanswered().exists()  # pas encore : on est avant la date
    DocumentRequest.objects.filter(pk=request.pk).update(next_reminder_on=timezone.localdate())
    assert services.overdue_requests(company) == [request]


def test_other_requests_keep_weekly_reminders():
    company, person = company_with_manager()
    request = services.create_request(company, "identity_card", person=person)  # pas de carte
    assert request.next_reminder_on == timezone.localdate() + timedelta(days=7)


def test_alert_icon_for_the_manager_only(web, user, client, make_user):
    company, request, _ = expiring_card_request()
    Assignment.objects.create(client=company, user=user, role=Assignment.Role.MANAGER)
    assert "sans réponse" not in web.get(reverse("core:home")).content.decode()
    DocumentRequest.objects.filter(pk=request.pk).update(
        reminders_sent=2, next_reminder_on=timezone.localdate()
    )
    home = web.get(reverse("core:home")).content.decode()
    assert "1 sans réponse" in home and reverse("conformite:unanswered") in home
    page = web.get(reverse("conformite:unanswered")).content.decode()
    assert company.display_name in page
    dossier = web.get(reverse("clients:documents", args=[company.pk])).content.decode()
    assert "⚠ 1 sans réponse" in dossier
    colleague = make_user(capabilities=["clients.edit"])
    client.force_login(colleague)  # pas dans l'équipe du dossier : pas d'icône
    assert "1 sans réponse" not in client.get(reverse("core:home")).content.decode()
