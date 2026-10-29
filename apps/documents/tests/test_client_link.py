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


# --- Signature en ligne (D-048) ---------------------------------------------------------------


def signature_png() -> str:
    import base64

    from PIL import ImageDraw

    image = Image.new("RGBA", (400, 150), (255, 255, 255, 0))
    draw = ImageDraw.Draw(image)
    draw.line([(20, 120), (120, 30), (200, 110), (380, 40)], fill=(20, 36, 59, 255), width=4)
    buffer = io.BytesIO()
    image.save(buffer, format="PNG")
    return "data:image/png;base64," + base64.b64encode(buffer.getvalue()).decode()


def letter_sent_for_signature():
    from apps.documents import generation
    from apps.documents.tests.letter_fixture import install

    company, _ = company_with_manager()
    install()
    draft = generation.generate(company, "lettre_mission")
    request = generation.send_for_signature(draft)
    return company, request, "/" + link_of(request)


def test_signature_request_email_has_a_signing_link():
    _, request, path = letter_sent_for_signature()
    assert "signer en ligne" in request.emails.get().body and path.startswith("/depot-client/")


def test_client_reads_and_signs_online(client):
    from pypdf import PdfReader

    from apps.documents.models import Signature

    company, request, path = letter_sent_for_signature()
    page = client.get(path).content.decode()
    assert "Signer le document" in page and "page-1.png" in page
    assert client.get(path + "page-1.png").status_code == 200
    original = request.documents.get(state="awaiting_signature")
    pages_before = len(PdfReader(original.file.open("rb")).pages)
    data = {"signer_name": "Anne Fictif", "signer_role": "gérante",
            "signature": signature_png(), "approve": "1"}  # fmt: skip
    html = client.post(path, data).content.decode()
    assert "signé" in html
    request.refresh_from_db()
    assert request.status == DocumentRequest.Status.RECEIVED
    signed = Document.objects.get(client=company, case="lettre-de-mission", state="final")
    assert len(PdfReader(signed.file.open("rb")).pages) == pages_before + 1  # + certificat
    proof = Signature.objects.get()
    assert proof.signer_name == "Anne Fictif" and proof.document == signed
    assert len(proof.original_sha256) == 64 and proof.original_sha256 != proof.signed_sha256
    original.refresh_from_db()
    assert original.archived_at is not None  # la version envoyée reste aux archives
    assert (
        client.get(path).status_code == 404 and client.get(path + "page-1.png").status_code == 404
    )


def test_signing_needs_approval_name_and_a_real_signature(client):
    _, request, path = letter_sent_for_signature()
    html = client.post(path, {"signer_name": "Anne Fictif", "signature": signature_png()}).content
    assert "Cochez la case" in html.decode()
    blank = "data:image/png;base64," + __import__("base64").b64encode(
        _blank_png()).decode()  # fmt: skip
    html = client.post(path, {"signer_name": "Anne Fictif", "signature": blank,
                              "approve": "1"}).content.decode()  # fmt: skip
    assert "Signature trop courte" in html
    html = client.post(path, {"signer_name": "Anne Fictif", "signature": "data:text/html,<b>",
                              "approve": "1"}).content.decode()  # fmt: skip
    assert "Signature manquante" in html
    request.refresh_from_db()
    assert request.status == DocumentRequest.Status.PENDING


def _blank_png() -> bytes:
    buffer = io.BytesIO()
    Image.new("RGBA", (400, 150), (255, 255, 255, 0)).save(buffer, format="PNG")
    return buffer.getvalue()


def test_card_is_read_after_the_answer_not_while_the_client_waits(client, monkeypatch):
    """D-103 : 30 à 45 secondes d'attente côté client. La lecture se fait ensuite, au passage
    des travaux automatiques ; le client a sa réponse tout de suite."""
    from apps.core import events
    from apps.core.models import Event
    from apps.documents import identity

    calls = []
    monkeypatch.setattr(identity, "process", lambda document, **kw: calls.append(document.pk))
    _request, path = new_request()
    response = client.post(path, {"files": [photo("recto.png", "red"), photo("verso.png", "blue")]})
    assert "reçu" in response.content.decode() and calls == []  # rien lu pendant la requête
    added = Event.objects.get(type="document.added")
    assert added.status == Event.Status.PENDING
    events.retry_pending(older_than_seconds=0)  # passage des travaux automatiques
    assert calls == [Document.objects.get(case="pieces-identite").pk]


def test_photos_combined_by_the_link_are_duplicates_when_dropped_again(client, web):
    """D-103 : Jeremy a redéposé les photos de la carte envoyées par le lien : doublon."""
    from django.urls import reverse

    from apps.documents.models import InboxItem

    _request, path = new_request()
    recto, verso = photo("recto.png", "red"), photo("verso.png", "blue")
    client.post(path, {"files": [recto, verso]})
    document = Document.objects.get(case="pieces-identite")
    assert len(document.source_hashes) == 2
    verso.seek(0)
    web.post(reverse("depot:index"), {"files": [SimpleUploadedFile("verso.png", verso.read())]})
    item = InboxItem.objects.get()
    assert item.duplicate_of == document
