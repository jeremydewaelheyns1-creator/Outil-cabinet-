"""Documents : dépôt sécurisé, lecture journalisée, demandes « À recevoir », relances."""

from datetime import timedelta

import pytest
from django.core.files.uploadedfile import SimpleUploadedFile
from django.urls import reverse
from django.utils import timezone

from apps.clients.models import Client, ContactPoint, Relation
from apps.core.models import AccessLog, Event
from apps.core.testing.factories import ClientFactory, PersonFactory, PortfolioFactory
from apps.documents import services
from apps.documents.models import Document, DocumentRequest, OutgoingEmail

pytestmark = pytest.mark.django_db

PDF = b"%PDF-1.4\n% document fictif\n"
PNG = b"\x89PNG\r\n\x1a\n" + b"0" * 20


def pdf(name: str = "fictif.pdf", content: bytes = PDF) -> SimpleUploadedFile:
    return SimpleUploadedFile(name, content, content_type="application/pdf")


def company_with_manager() -> tuple[Client, Client]:
    company = ClientFactory()
    ContactPoint.objects.create(client=company, kind="email", value="compta@fictif.test")
    manager = PersonFactory(name="Fictif", first_name="Anne")
    Relation.objects.create(entity=company, person=manager, role="manager")
    return company, manager


# --- Dépôt -----------------------------------------------------------------------------------


def test_store_checks_content_not_just_the_name():
    company = ClientFactory()
    with pytest.raises(services.ValidationError):
        services.store(company, pdf(content=b"<html>pas un pdf</html>"), title="x", case="ubo")
    with pytest.raises(services.ValidationError):
        services.store(company, SimpleUploadedFile("x.svg", b"<svg/>"), title="x", case="ubo")
    with pytest.raises(services.ValidationError):
        services.store(company, SimpleUploadedFile("vide.pdf", b""), title="x", case="ubo")
    document = services.store(company, pdf(), title="Registre des parts", case="ubo")
    assert document.content_type == "application/pdf"
    assert len(document.sha256) == 64
    # Nom de stockage aléatoire : ni le nom du fichier ni celui du client.
    assert "fictif" not in document.file.name and company.name not in document.file.name


def test_store_refuses_too_large_files(settings):
    settings.DOCUMENT_MAX_BYTES = 10
    with pytest.raises(services.ValidationError):
        services.store(ClientFactory(), pdf(), title="x", case="ubo")


def test_new_identity_card_archives_the_previous_one():
    company, manager = company_with_manager()
    old = services.store(company, pdf(), title="Carte", case="pieces-identite", person=manager)
    new = services.store(company, pdf(), title="Carte", case="pieces-identite", person=manager)
    old.refresh_from_db()
    assert (old.case, old.folder) == ("", "administratif") and old.archived_at
    assert services.current_documents(company, "pieces-identite") == [new]


def test_upload_view_requires_edit_right_and_logs(web, client, make_user):
    company = ClientFactory()
    url = reverse("clients:document_upload", args=[company.pk])
    data = {"title": "Lettre de mission 2026", "case": "lettre-de-mission", "file": pdf()}
    response = web.post(url, data)
    assert response.status_code == 302
    document = Document.objects.get()
    assert AccessLog.objects.filter(action="create", object_id=str(document.pk)).exists()
    client.force_login(make_user())  # lecture seule
    data["file"] = pdf()
    assert client.post(url, data).status_code == 403


def test_upload_view_rejects_unknown_place(web):
    company = ClientFactory()
    url = reverse("clients:document_upload", args=[company.pk])
    web.post(url, {"title": "x", "case": "../../etc", "file": pdf()})
    assert not Document.objects.exists()


# --- Lecture ---------------------------------------------------------------------------------


def test_reading_a_document_is_logged_and_sandboxed(web):
    company = ClientFactory()
    document = services.store(company, pdf(), title="Statuts", folder="legal")
    response = web.get(reverse("clients:document_file", args=[company.pk, document.pk]))
    assert response.status_code == 200
    assert b"".join(response.streaming_content) == PDF
    assert "sandbox" in response["Content-Security-Policy"]
    assert response["Cache-Control"] == "private, no-store"
    assert AccessLog.objects.filter(action="view", object_id=str(document.pk)).exists()


def test_documents_of_private_clients_are_unreachable(web):
    hidden = ClientFactory(portfolio=PortfolioFactory(is_private=True))
    document = services.store(hidden, pdf(), title="Secret", folder="legal")
    url = reverse("clients:document_file", args=[hidden.pk, document.pk])
    assert web.get(url).status_code == 404
    # Ni par un autre dossier visible.
    other = ClientFactory()
    assert (
        web.get(reverse("clients:document_file", args=[other.pk, document.pk])).status_code == 404
    )


def test_office_files_are_downloaded_not_displayed(web):
    company = ClientFactory()
    xlsx = SimpleUploadedFile("tableau.xlsx", b"PK\x03\x04" + b"0" * 20)
    document = services.store(company, xlsx, title="Tableau", folder="administratif")
    response = web.get(reverse("clients:document_file", args=[company.pk, document.pk]))
    assert response["Content-Disposition"].startswith("attachment")


# --- Demandes « À recevoir » ----------------------------------------------------------------


def test_request_prepares_a_neutral_email(web):
    company, manager = company_with_manager()
    response = web.post(
        reverse("clients:request_create", args=[company.pk]),
        {"kind": "identity_card", "person": manager.pk},
    )
    assert response.status_code == 302
    request = DocumentRequest.objects.get()
    assert request.title == "Carte d'identité de Fictif Anne"
    assert request.recipient == "compta@fictif.test"
    email = OutgoingEmail.objects.get()
    assert request.reference in email.subject and not email.delivered
    assert manager.national_number is None or manager.national_number not in email.body
    html = web.get(reverse("clients:document_case", args=[company.pk, "a-recevoir"])).content
    assert (
        "Carte d&#x27;identité de Fictif Anne" in html.decode()
        or "Carte d'identité" in html.decode()
    )


def test_identity_request_needs_a_person(web):
    company, _ = company_with_manager()
    web.post(reverse("clients:request_create", args=[company.pk]), {"kind": "identity_card"})
    assert not DocumentRequest.objects.exists()


def test_person_must_be_linked_to_the_client(web):
    company, _ = company_with_manager()
    stranger = PersonFactory()
    web.post(
        reverse("clients:request_create", args=[company.pk]),
        {"kind": "identity_card", "person": stranger.pk},
    )
    assert not DocumentRequest.objects.exists()


def test_receiving_files_the_document_in_its_case(web):
    company, manager = company_with_manager()
    request = services.create_request(company, "identity_card", person=manager)
    url = reverse("clients:request_receive", args=[company.pk, request.pk])
    web.post(url, {"file": pdf("carte.pdf")})
    request.refresh_from_db()
    assert request.status == DocumentRequest.Status.RECEIVED
    document = Document.objects.get()
    assert (document.case, document.person, document.request) == (
        "pieces-identite",
        manager,
        request,
    )
    assert Event.objects.filter(type="document_request.received").exists()
    # Plus rien « à recevoir ».
    assert services.pending_requests(company) == []


def test_reminders_then_red_after_the_last_one(settings):
    settings.REQUEST_REMINDER_DAYS = 7
    settings.REQUEST_MAX_REMINDERS = 2
    company, manager = company_with_manager()
    request = services.create_request(company, "identity_card", person=manager)
    today = timezone.localdate()
    assert services.send_due_reminders(today) == 0
    assert services.send_due_reminders(today + timedelta(days=7)) == 1
    assert services.send_due_reminders(today + timedelta(days=7)) == 0  # pas deux fois
    assert services.send_due_reminders(today + timedelta(days=14)) == 1
    assert services.send_due_reminders(today + timedelta(days=30)) == 0  # maximum atteint
    request.refresh_from_db()
    assert request.reminders_sent == 2
    assert OutgoingEmail.objects.filter(kind="reminder").count() == 2
    request.next_reminder_on = today
    request.save()
    assert services.overdue_requests(company) == [request]


def test_cancelled_request_is_not_reminded():
    company, manager = company_with_manager()
    request = services.create_request(company, "identity_card", person=manager)
    services.cancel(request)
    assert services.send_due_reminders(timezone.localdate() + timedelta(days=60)) == 0


def test_documents_tab_reflects_the_situation(web):
    company, manager = company_with_manager()
    html = web.get(reverse("clients:documents", args=[company.pk])).content.decode()
    assert "Aucune demande en attente" in html
    services.create_request(company, "identity_card", person=manager)
    services.store(
        company, pdf(), title="Lettre", case="lettre-de-mission", doc_type="lettre_mission"
    )
    html = web.get(reverse("clients:documents", args=[company.pk])).content.decode()
    assert "1 demande en attente" in html and "Tout est en ordre" in html


def test_archive_folder_lists_and_accepts_documents(web):
    company = ClientFactory()
    services.store(company, SimpleUploadedFile("scan.png", PNG), title="Déclaration ISOC 2024",
                   folder="isoc")  # fmt: skip
    url = reverse("clients:archive", args=[company.pk, "isoc"])
    html = web.get(url, follow=True).content.decode()  # → classeur, sujet ISOC (D-105)
    assert "Déclaration ISOC 2024" in html and "Ajouter un document" in html
