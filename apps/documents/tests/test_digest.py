"""Résumé mensuel des employés et e-mails automatiques groupés au client (D-052)."""

from datetime import date, timedelta

import pytest
from django.urls import reverse
from django.utils import timezone

from apps.clients.models import Assignment, Relation
from apps.core.models import Notification
from apps.core.testing.factories import PersonFactory
from apps.documents import digest, identity, services
from apps.documents.models import DocumentRequest, IdentityCard
from apps.documents.tests.test_documents import company_with_manager

pytestmark = pytest.mark.django_db


def test_monthly_notifications_once_with_counts(user):
    company, manager = company_with_manager()
    Assignment.objects.create(client=company, user=user, role=Assignment.Role.MANAGER)
    request = services.create_request(company, "identity_card", person=manager)
    request.created_at = timezone.make_aware(timezone.datetime(2026, 10, 12, 10))
    request.save()
    assert digest.monthly(date(2026, 11, 1)) == 1
    assert digest.monthly(date(2026, 11, 2)) == 0  # une seule fois par mois
    conformity = Notification.objects.get(user=user, key="conformite:2026-11")
    assert conformity.title == "1 dossier à mettre en ordre"
    assert "1 dossier incomplet" in conformity.lines
    activity = Notification.objects.get(user=user, key="activite:2026-11")
    assert activity.title == "Ce que l'outil a fait en octobre"
    assert "1 demande envoyée aux clients" in activity.lines
    assert manager.display_name not in str(activity.lines)  # des nombres, pas de noms


def test_bell_shows_unread_and_page_marks_them_read(web, user):
    Notification.objects.create(user=user, key="x", title="2 dossiers à mettre en ordre")
    home = web.get(reverse("core:home")).content.decode()
    assert 'class="bell-count">1<' in home
    page = web.get(reverse("core:notifications")).content.decode()
    assert "2 dossiers à mettre en ordre" in page and "nouveau" in page
    assert 'class="bell-count"' not in web.get(reverse("core:home")).content.decode()


def test_expiring_cards_of_one_client_go_in_one_email():
    company, anne = company_with_manager()
    marc = PersonFactory(name="Fictif", first_name="Marc")
    Relation.objects.create(entity=company, person=marc, role="manager")
    soon = timezone.localdate() + timedelta(days=5)
    for person in (anne, marc):
        IdentityCard.objects.create(person=person, valid_until=soon, source="manual")
    assert identity.request_renewals() == 2
    bundle = DocumentRequest.objects.get(kind="bundle")
    assert bundle.items.count() == 2 and bundle.emails.count() == 1
    assert identity.request_renewals() == 0  # déjà demandé
