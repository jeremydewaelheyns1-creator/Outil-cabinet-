"""Documents du SPF reconnus et classés au dépôt (D-084). Courriers fictifs fabriqués ici."""

import shutil

import pytest
from django.core.files.uploadedfile import SimpleUploadedFile
from django.urls import reverse

from apps.core.models import CabinetSettings
from apps.core.testing.factories import ClientFactory, PersonFactory
from apps.core.testing.numbers import enterprise_number, national_number
from apps.documents import spf_docs
from apps.documents.models import Document, InboxItem

pytestmark = [
    pytest.mark.django_db,
    pytest.mark.skipif(not shutil.which("pdftotext"), reason="poppler absent"),
]


def pdf(*paragraphs: str) -> SimpleUploadedFile:
    from weasyprint import HTML

    html = "".join(f"<p>{p}</p>" for p in paragraphs)
    return SimpleUploadedFile("courrier.pdf", HTML(string=html).write_pdf(),
                              content_type="application/pdf")  # fmt: skip


def number(seed: int) -> str:
    n = enterprise_number(seed)
    return f"{n[:4]}.{n[4:7]}.{n[7:]}"


def test_isoc_assessment_goes_to_the_company_isoc_archive(web):
    company = ClientFactory(enterprise_number=enterprise_number(7001))
    CabinetSettings.objects.update_or_create(pk=1, defaults={"enterprise_number": number(7002)})
    upload = pdf("SPF FINANCES — AVERTISSEMENT-EXTRAIT DE RÔLE",
                 "Impôt des sociétés — exercice d'imposition 2025",
                 f"Numéro d'entreprise : {number(7001)}",
                 f"Mandataire : cabinet {number(7002)}")  # fmt: skip
    web.post(reverse("depot:index"), {"files": [upload]})
    document = Document.objects.get(client=company)
    assert document.folder == "isoc"
    assert document.title == "Avertissement-extrait de rôle ISOC — exercice 2025"


def test_ipp_assessment_is_found_by_national_number(web):
    nn = national_number(31, "800101")
    person = PersonFactory(national_number=nn)
    upload = pdf("Avertissement-extrait de rôle", "Impôt des personnes physiques",
                 "Exercice d'imposition 2025 (revenus 2024)",
                 f"Numéro national : {nn[:2]}.{nn[2:4]}.{nn[4:6]}-{nn[6:9]}.{nn[9:]}")  # fmt: skip
    web.post(reverse("depot:index"), {"files": [upload]})
    document = Document.objects.get(client=person)
    assert document.folder == "ipp" and "IPP" in document.title


def test_request_for_information_is_filed_to_be_handled(web):
    company = ClientFactory(enterprise_number=enterprise_number(7003))
    upload = pdf("Demande de renseignements (art. 316 CIR 92)", "Impôt des sociétés",
                 f"Société {number(7003)} — merci de répondre dans le mois.")  # fmt: skip
    web.post(reverse("depot:index"), {"files": [upload]})
    document = Document.objects.get(client=company)
    assert document.review_needed and "réponse" in document.review_reason


def test_unknown_number_waits_in_to_classify_with_the_reason(web):
    upload = pdf("Biztax — accusé de réception", "Votre déclaration a bien été déposée.",
                 f"Numéro d'entreprise {number(7999)}")  # fmt: skip
    web.post(reverse("depot:index"), {"files": [upload]})
    item = InboxItem.objects.get()
    assert "Biztax" in item.reason and "aucun dossier" in item.reason
    assert not Document.objects.exists()


def test_ordinary_letter_is_not_guessed():
    assert spf_docs.kind_of("Facture du garage pour l'entretien du véhicule, TVA 21 %") is None
    assert spf_docs.kind_of("Avertissement-extrait de rôle impôt des sociétés").slug == "aer_isoc"


def test_client_listing_goes_to_the_declarant_not_to_its_customers(web):
    """Grand test : un listing clients cite aussi les numéros des clients du déclarant."""
    declarant = ClientFactory(enterprise_number=enterprise_number(7101), name="Graphiste Fictif")
    ClientFactory(enterprise_number=enterprise_number(7102), name="Client Fictif du Graphiste")
    upload = pdf("Listing annuel des clients assujettis — année 2025",
                 f"Déclarant : Graphiste Fictif — numéro de TVA BE {number(7101)}",
                 f"Client : BE {number(7102)} — chiffre d'affaires 2 400,00 EUR — TVA")  # fmt: skip
    web.post(reverse("depot:index"), {"files": [upload]})
    document = Document.objects.get()
    assert document.client == declarant and document.folder == "tva"
