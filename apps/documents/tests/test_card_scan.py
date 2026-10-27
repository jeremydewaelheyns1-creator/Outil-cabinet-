"""Scan de la carte par la caméra du client (D-083)."""

import shutil
from datetime import timedelta
from pathlib import Path

import pytest
from django.utils import timezone

from apps.core.testing.factories import PersonFactory
from apps.documents import services
from apps.documents.models import DocumentRequest

from .test_client_link import link_of

pytestmark = pytest.mark.django_db


def card_request():
    from apps.clients.models import ContactPoint

    person = PersonFactory()
    ContactPoint.objects.create(client=person, kind="email", value="p@fictif.test")
    return services.create_request(person, DocumentRequest.Kind.IDENTITY_CARD, person=person,
                                   label="", user=None)  # fmt: skip


def test_card_link_stays_valid_90_days():
    request = card_request()
    assert request.link_expires_at >= timezone.now() + timedelta(days=89)


def test_card_page_offers_the_camera_with_the_reader_served_locally(client):
    path = "/" + link_of(card_request())
    response = client.get(path)
    html = response.content.decode()
    assert "data-card-scan" in html and "Ouvrir la caméra" in html
    assert "/static/vendor/tesseract/tesseract.min.js" in html and "card-scan.js" in html
    assert "Déposez une photo" in html  # le dépôt classique reste là
    csp = response["Content-Security-Policy"]
    assert "'wasm-unsafe-eval'" in csp and "unsafe-eval'" not in csp.replace("wasm-unsafe-eval", "")


@pytest.mark.skipif(not shutil.which("tesseract") or not shutil.which("pdfimages"),
                    reason="tesseract / poppler absents")  # fmt: skip
def test_server_reads_the_photos_inside_the_pdf(settings):
    """Recto et verso envoyés par le téléphone sont réunis en PDF : le serveur lit les photos
    qu'il contient, pas seulement la page A4 (où la carte est petite)."""
    import io

    from PIL import Image, ImageDraw, ImageFont

    from apps.core.testing.numbers import national_number
    from apps.documents import client_upload, identity, mrz

    settings.IDENTITY_OCR_ENABLED = True
    font_path = "/usr/share/fonts/truetype/dejavu/DejaVuSansMono-Bold.ttf"
    if not Path(font_path).exists():
        pytest.skip("police absente")
    lines = mrz.build_td1(document_number="592123456789", surname="FICTIF", given_names="ANNE",
                          birth="850730", expiry="310101",
                          national_number=national_number(4, "850730"))  # fmt: skip
    card = Image.new("RGB", (560, 354), (214, 220, 230))
    draw = ImageDraw.Draw(card)
    font = ImageFont.truetype(font_path, 26)
    for i, line in enumerate(lines):
        draw.text((14, 240 + i * 34), line, font=font, fill=(25, 28, 36))
    out = io.BytesIO()
    card.save(out, "JPEG", quality=92)
    from django.core.files.uploadedfile import SimpleUploadedFile

    photos = [(SimpleUploadedFile(n, out.getvalue(), content_type="image/jpeg"), "image/jpeg")
              for n in ("recto.jpg", "verso.jpg")]  # fmt: skip
    pdf = client_upload._combine(photos).read()
    text = identity.ocr_bytes(pdf, "application/pdf") or ""
    result = mrz.read(text)
    assert result is not None and result.valid
