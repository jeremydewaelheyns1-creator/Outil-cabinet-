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


def test_stale_prospects_are_proposed_for_deletion_never_deleted():
    from datetime import timedelta

    from django.utils import timezone

    from apps.core.testing.factories import ClientFactory

    admin = UserFactory(is_staff=True)
    old = ClientFactory(status=Client.Status.PROSPECT)
    Client.objects.filter(pk=old.pk).update(updated_at=timezone.now() - timedelta(days=400))
    ClientFactory(status=Client.Status.PROSPECT)  # récent : pas compté
    assert prospects.remind_stale() == 1
    assert Notification.objects.get(user=admin).link == "/clients/?statut=prospect"
    assert Client.objects.filter(pk=old.pk).exists()


def test_admin_deletes_a_prospect_and_everything_about_it(
    client, django_capture_on_commit_callbacks
):
    from apps.clients.models import ContactPoint
    from apps.core.models import AccessLog
    from apps.documents.models import Document, DocumentRequest

    company, _, _ = prospect_sending_a_letter()
    files = [d.file.name for d in Document.objects.filter(client=company)]
    storage = Document.objects.filter(client=company).first().file.storage
    pk = company.pk
    client.force_login(UserFactory(capabilities=["clients.edit"]))
    url = reverse("clients:prospect_delete", args=[pk])
    assert client.get(url).status_code == 403  # pas administrateur
    client.force_login(UserFactory(is_staff=True, capabilities=["clients.edit"]))
    assert "définitivement" in client.get(url).content.decode()
    with django_capture_on_commit_callbacks(execute=True):
        client.post(url, {"confirme": "1"})
    assert not Client.objects.filter(pk=pk).exists()
    assert not Document.objects.filter(client_id=pk).exists()
    assert not DocumentRequest.objects.filter(client_id=pk).exists()
    assert not ContactPoint.objects.filter(client_id=pk).exists()
    assert not Client.history.filter(id=pk).exists()
    assert not any(storage.exists(name) for name in files)
    assert AccessLog.objects.filter(action="delete", details__has_key="prospect supprimé").exists()


def test_a_client_cannot_be_deleted_this_way():
    from apps.core.testing.factories import ClientFactory

    with pytest.raises(ValueError):
        prospects.delete_prospect(ClientFactory())
