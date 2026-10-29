"""Visualiseur de documents (D-036) : fenêtre, pages en images, téléchargement."""

import shutil

import pytest
from django.core.files.uploadedfile import SimpleUploadedFile
from django.urls import reverse

from apps.clients.management.commands.demo import demo_pdf
from apps.core.models import AccessLog
from apps.core.testing.factories import ClientFactory, PortfolioFactory
from apps.documents import services

pytestmark = pytest.mark.django_db
needs_poppler = pytest.mark.skipif(not shutil.which("pdftoppm"), reason="poppler absent")


def stored(client, content=None, name="lettre.pdf", **place):
    upload = SimpleUploadedFile(name, content or demo_pdf("Lettre de mission"))
    return services.store(
        client, upload, title="Lettre de mission", **(place or {"folder": "legal"})
    )


def test_viewer_window_shows_title_place_and_actions(web):
    company = ClientFactory()
    document = stored(company, case="lettre-de-mission")
    response = web.get(
        reverse("clients:document_viewer", args=[company.pk, document.pk]), HTTP_HX_REQUEST="true"
    )
    html = response.content.decode()
    assert response.status_code == 200
    assert "Lettre de mission" in html and "Documents › Lettre de mission" in html
    assert "Télécharger" in html and "Fermer" in html and "Informations" in html
    assert "<html" not in html  # fragment : s'affiche par-dessus la page
    assert AccessLog.objects.filter(action="view", object_id=str(document.pk)).exists()


def test_viewer_page_without_javascript(web):
    company = ClientFactory()
    document = stored(company)
    url = reverse("clients:document_viewer_page", args=[company.pk, document.pk])
    html = web.get(url).content.decode()
    assert "Archives › Légal et statuts" in html and 'aria-current="page">Documents<' in html


@needs_poppler
def test_pdf_pages_are_shown_as_images(web):
    company = ClientFactory()
    document = stored(company)
    html = web.get(
        reverse("clients:document_viewer", args=[company.pk, document.pk]), HTTP_HX_REQUEST="true"
    ).content
    page_url = reverse("clients:document_page", args=[company.pk, document.pk, 1])
    assert page_url in html.decode()
    page = web.get(page_url)
    assert page["Content-Type"] == "image/png" and page.content.startswith(b"\x89PNG")
    assert "sandbox" in page["Content-Security-Policy"]
    assert (
        web.get(reverse("clients:document_page", args=[company.pk, document.pk, 2])).status_code
        == 404
    )


def test_unreadable_office_file_has_no_preview_but_can_be_downloaded(web):
    company = ClientFactory()
    xlsx = b"PK\x03\x04" + b"0" * 20
    document = stored(company, content=xlsx, name="tableau.xlsx")
    html = web.get(
        reverse("clients:document_viewer", args=[company.pk, document.pk]), HTTP_HX_REQUEST="true"
    ).content
    assert "Pas d'aperçu" in html.decode()


def test_download_forces_attachment(web):
    company = ClientFactory()
    document = stored(company)
    url = reverse("clients:document_file", args=[company.pk, document.pk])
    assert web.get(url + "?telecharger=1")["Content-Disposition"].startswith("attachment")
    assert web.get(url)["Content-Disposition"].startswith("inline")


def test_viewer_respects_private_portfolios(web):
    hidden = ClientFactory(portfolio=PortfolioFactory(is_private=True))
    document = stored(hidden)
    for name in ("document_viewer", "document_viewer_page"):
        assert web.get(reverse(f"clients:{name}", args=[hidden.pk, document.pk])).status_code == 404
    page = reverse("clients:document_page", args=[hidden.pk, document.pk, 1])
    assert web.get(page).status_code == 404


def test_viewer_moves_between_documents_of_the_same_place(web):
    company = ClientFactory()
    first = stored(company, case="procuration")
    second = stored(company, case="procuration")  # le plus récent en premier
    html = web.get(
        reverse("clients:document_viewer", args=[company.pk, second.pk]), HTTP_HX_REQUEST="true"
    ).content
    assert "1 / 2" in html.decode()
    assert reverse("clients:document_viewer", args=[company.pk, first.pk]) in html.decode()


def test_viewer_opened_directly_shows_the_full_page(web):
    company = ClientFactory()
    document = stored(company)
    response = web.get(reverse("clients:document_viewer", args=[company.pk, document.pk]))
    assert response.url == reverse("clients:document_viewer_page", args=[company.pk, document.pk])
