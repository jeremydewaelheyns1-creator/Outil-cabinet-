"""Lien sécurisé de dépôt envoyé au client (D-046). Données fictives."""

import io
import re
from datetime import timedelta

import pytest
from django.core.files.uploadedfile import SimpleUploadedFile
from django.utils import timezone
from PIL import Image

from apps.core.models import AccessLog
from apps.documents import services
from apps.documents.models import Document, DocumentRequest
from apps.documents.tests.test_documents import company_with_manager

pytestmark = pytest.mark.django_db


def photo(name: str, color: str) -> SimpleUploadedFile:
    buffer = io.BytesIO()
    Image.new("RGB", (40, 25), color).save(buffer, format="PNG")
    return SimpleUploadedFile(name, buffer.getvalue(), content_type="image/png")


def link_of(request: DocumentRequest) -> str:
    body = request.emails.first().body
    match = re.search(r"https?://\S+/depot-client/([\w-]+)/", body)
    assert match, body
    return match.group(0).split("://", 1)[1].split("/", 1)[1]


def new_request() -> tuple[DocumentRequest, str]:
    company, manager = company_with_manager()
    request = services.create_request(company, "identity_card", person=manager)
    return request, "/" + link_of(request)


def test_request_email_contains_a_personal_link(settings):
    settings.SITE_URL = "https://outil.example.be"
    request, path = new_request()
    body = request.emails.get().body
    assert "https://outil.example.be/depot-client/" in body and "valable jusqu'au" in body
    assert "ne pas l'envoyer par e-mail" in body
    token = path.rstrip("/").rsplit("/", 1)[1]
    assert request.link_hash != token and token not in request.link_token  # jamais en clair


def test_client_uploads_front_and_back_without_an_account(client):
    request, path = new_request()
    page = client.get(path)
    assert page.status_code == 200 and "Fictif Anne" in page.content.decode()
    assert page["Cache-Control"] == "no-store" and page["Referrer-Policy"] == "same-origin"
    response = client.post(path, {"files": [photo("recto.png", "red"), photo("verso.png", "blue")]})
    assert "reçu" in response.content.decode()
    request.refresh_from_db()
    assert request.status == DocumentRequest.Status.RECEIVED
    document = Document.objects.get(case="pieces-identite")
    assert document.content_type == "application/pdf" and document.request == request
    assert AccessLog.objects.filter(action="create", details__via="lien client").exists()
    # Le lien ne sert qu'une fois.
    assert client.get(path).status_code == 404


def test_bad_files_are_refused_and_counted(client, settings):
    settings.REQUEST_LINK_MAX_ATTEMPTS = 2
    request, path = new_request()
    html = client.post(path, {"files": [SimpleUploadedFile("x.txt", b"bonjour")]}).content.decode()
    assert "Format" in html or "format" in html
    client.post(path, {"files": [SimpleUploadedFile("x.txt", b"bonjour")]})
    assert client.get(path).status_code == 404  # trop d'essais : lien bloqué
    request.refresh_from_db()
    assert request.status == DocumentRequest.Status.PENDING and not Document.objects.exists()


def test_pdf_and_photo_together_are_refused(client):
    _, path = new_request()
    pdf = SimpleUploadedFile("a.pdf", b"%PDF-1.4\n%fictif\n")
    html = client.post(path, {"files": [pdf, photo("b.png", "red")]}).content.decode()
    assert "un seul PDF" in html
    assert not Document.objects.exists()


def test_unknown_expired_or_cancelled_links_say_nothing(client):
    request, path = new_request()
    assert client.get("/depot-client/inconnu/").status_code == 404
    DocumentRequest.objects.filter(pk=request.pk).update(
        link_expires_at=timezone.now() - timedelta(minutes=1)
    )
    response = client.get(path)
    assert response.status_code == 404 and "Fictif Anne" not in response.content.decode()
    other, other_path = new_request()
    services.cancel(other)
    assert client.get(other_path).status_code == 404


def test_reminder_keeps_the_same_link_and_extends_it():
    request, path = new_request()
    before = request.link_expires_at
    services.send_due_reminders(timezone.localdate() + timedelta(days=7))
    request.refresh_from_db()
    reminder = request.emails.get(kind="reminder")
    assert path in reminder.body and request.link_expires_at > before


def test_signature_requests_have_no_upload_link():
    company, _ = company_with_manager()
    request = services.create_request(company, "signature", label="Lettre de mission à signer")
    assert not request.link_hash and "depot-client" not in request.emails.get().body
