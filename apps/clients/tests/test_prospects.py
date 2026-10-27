"""Prospect → client à la signature de la lettre de mission (D-077)."""

import pytest
from django.urls import reverse

from apps.clients import prospects
from apps.clients.models import Assignment, Client
from apps.core.models import Notification
from apps.core.testing.factories import UserFactory

pytestmark = pytest.mark.django_db


def prospect_sending_a_letter():
    from apps.documents import generation
    from apps.documents.tests.letter_fixture import install
    from apps.documents.tests.test_client_link import link_of
    from apps.documents.tests.test_documents import company_with_manager

    company, _ = company_with_manager()
    company.status = Client.Status.PROSPECT
    company.vat_status = ""
    company.client_since = None
    company.save()
    expert = UserFactory()
    Assignment.objects.create(client=company, user=expert, role=Assignment.Role.MANAGER)
    install()
    draft = generation.generate(company, "lettre_mission")
    request = generation.send_for_signature(draft)
    return company, expert, "/" + link_of(request)


def test_signed_letter_turns_the_prospect_into_a_client(client, django_capture_on_commit_callbacks):
    from apps.documents.tests.test_client_link import signature_png

    company, expert, path = prospect_sending_a_letter()
    data = {"signer_name": "Anne Fictif", "signature": signature_png(), "approve": "1"}
    with django_capture_on_commit_callbacks(execute=True):
        client.post(path, data)
    company.refresh_from_db()
    assert company.status == Client.Status.ACTIVE and company.client_since is not None
    note = Notification.objects.get(user=expert)
    assert "Nouveau client" in note.title and "statut TVA" in " ".join(note.lines)
    # Idempotent : une seconde fois ne change rien et ne renvoie pas de notification.
    assert not prospects.become_client(company)
    assert Notification.objects.count() == 1


def test_prospect_has_no_deadlines_until_it_becomes_client(web, django_capture_on_commit_callbacks):
    from apps.tasks.generator import generate_for_client
    from apps.tasks.models import Task

    company, _, _ = prospect_sending_a_letter()
    company.vat_status = "subject"
    company.vat_periodicity = "quarterly"
    company.save()
    generate_for_client(company)
    assert not Task.objects.filter(client=company).exists()
    page = web.get(reverse("clients:identity", args=[company.pk])).content.decode()
    assert "Devient client" in page
    with django_capture_on_commit_callbacks(execute=True):
        web.post(reverse("clients:become_client", args=[company.pk]))
    company.refresh_from_db()
    assert company.status == Client.Status.ACTIVE
    assert Task.objects.filter(client=company).exists()  # échéances créées pour le client


def test_without_expert_the_admins_are_told():
    from apps.core.testing.factories import ClientFactory

    admin = UserFactory(is_staff=True)
    company = ClientFactory(status=Client.Status.PROSPECT)
    prospects.become_client(company, reason="Test")
    assert Notification.objects.filter(user=admin).exists()
