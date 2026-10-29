"""Archives par année, période (TVA) et thème ; aperçu lisible des XML d'Intervat (D-097)."""

import pytest
from django.core.files.uploadedfile import SimpleUploadedFile
from django.urls import reverse

from apps.documents import services
from apps.documents.models import Document
from apps.vat import importer
from apps.vat.tests.test_vat import pdf_with, upload, vat_client, vat_xml

pytestmark = pytest.mark.django_db


def declarations(user):
    company = vat_client()
    number = company.enterprise_number
    formatted = f"{number[:4]}.{number[4:7]}.{number[7:]}"
    files = []
    for quarter in (2, 3):
        files.append(upload(f"t{quarter}.xml", vat_xml(number, quarter=quarter)))
        text = f"Déclaration périodique à la TVA BE {formatted} {quarter}e trimestre 2026"
        files.append(upload(f"t{quarter}.pdf", pdf_with(text)))
    importer.import_files(files, clients=type(company).objects.all(), user=user)
    return company


def test_vat_archive_by_year_then_quarter(web, user):
    company = declarations(user)
    services.store(company, SimpleUploadedFile("cc.pdf", b"%PDF-1.4 fictif"),
                   title="Compte courant TVA", folder="tva", user=user)  # fmt: skip
    title = "Déclaration TVA 4e trimestre 2025 (PDF)"
    old = services.store(company, SimpleUploadedFile("t4.pdf", b"%PDF-1.4 fictif 2"),
                         title=title, folder="tva", user=user)  # fmt: skip
    url = reverse("clients:archive", args=[company.pk, "tva"])
    html = web.get(url).content.decode()
    assert "?annee=2026" in html and "?annee=2025" in html  # dossiers par année
    assert "T3-26" in html and "T2-26" in html  # sous-onglets par trimestre
    assert "Compte courant TVA" in html  # par thème
    assert old.title not in html  # 2025 : sous son propre onglet
    only_t3 = web.get(url, {"annee": "2026", "periode": "p:2026-T3"}).content.decode()
    assert only_t3.count("(XML)") == 1 and only_t3.count("(PDF)") == 1  # XML et PDF réunis
    assert "2e trimestre" not in only_t3
    assert old.title in web.get(url, {"annee": "2025"}).content.decode()


def test_xml_is_shown_as_a_readable_table(web, user):
    company = declarations(user)
    xml = Document.objects.get(
        client=company, title__contains="3e trimestre", title__endswith="(XML)"
    )
    url = reverse("clients:document_viewer", args=[company.pk, xml.pk])
    html = web.get(url, HTTP_HX_REQUEST="true").content.decode()
    assert "Déclaration périodique à la TVA — 3e trimestre 2026" in html
    assert "Taxe due à l&#x27;État" in html and "272,44" in html
    assert "Pas d&#x27;aperçu" not in html
