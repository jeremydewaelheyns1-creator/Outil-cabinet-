"""Documents exigés (anti-blanchiment) : lignes, situation, remplacement, demandes (D-037)."""

from datetime import timedelta

import pytest
from django.core.files.uploadedfile import SimpleUploadedFile
from django.urls import reverse
from django.utils import timezone

from apps.clients.models import ContactPoint, Relation
from apps.core.testing.factories import ClientFactory, PersonFactory
from apps.documents import services, types
from apps.documents.models import Document, DocumentRequest

pytestmark = pytest.mark.django_db


def pdf():
    return SimpleUploadedFile("x.pdf", b"%PDF-1.4 fictif")


def company_with_managers():
    company = ClientFactory()
    ContactPoint.objects.create(client=company, kind="email", value="compta@fictif.test")
    anne, holding = PersonFactory(name="Fictif", first_name="Anne"), ClientFactory(name="Holding")
    Relation.objects.create(entity=company, person=anne, role="manager")
    Relation.objects.create(entity=company, person=holding, role="director")
    return company, anne, holding


def by_label(rows):
    return {(r.doc_type.slug, r.person.pk if r.person else None): r for r in rows}


def test_missing_required_documents_are_red_and_one_line_per_mandataire():
    company, anne, holding = company_with_managers()
    rows = by_label(types.rows(company, "anti-blanchiment"))
    assert rows[("identification_client", None)].level == "danger"
    assert ("identification_mandataire", anne.pk) in rows
    assert ("identification_mandataire", holding.pk) in rows  # une société mandataire aussi
    assert rows[("procuration", None)].level == "empty"  # facultative


def test_expiry_states():
    company, _, _ = company_with_managers()
    today = timezone.localdate()

    def store_risk(expires):
        services.store(company, pdf(), title="Fiche", case="anti-blanchiment",
                       doc_type="fiche_risque", expires_on=expires)  # fmt: skip
        return by_label(types.rows(company, "anti-blanchiment"))[("fiche_risque", None)]

    assert store_risk(None).text == "Date d'expiration indéfinie"
    assert store_risk(today + timedelta(days=44)).text == "Expire dans 44 jours"
    assert store_risk(today - timedelta(days=1)).level == "danger"
    assert store_risk(today + timedelta(days=400)).level == "ok"
    # Chaque nouvelle fiche remplace la précédente, qui part aux archives.
    assert Document.objects.filter(doc_type="fiche_risque", archived_at__isnull=True).count() == 1
    assert Document.objects.filter(doc_type="fiche_risque", folder="administratif").count() == 3


def test_replacement_is_per_mandataire():
    company, anne, holding = company_with_managers()
    for person in (anne, holding):
        services.store(company, pdf(), title="Identification", case="anti-blanchiment",
                       doc_type="identification_mandataire", person=person)  # fmt: skip
    current = Document.objects.filter(
        doc_type="identification_mandataire", archived_at__isnull=True
    )
    assert current.count() == 2


def test_case_status_names_the_first_problem(web):
    company, _, _ = company_with_managers()
    html = web.get(reverse("clients:documents", args=[company.pk])).content.decode()
    assert "Identification du client : manquant" in html


def test_request_from_a_row_files_the_document_with_its_type(web):
    company, _, _ = company_with_managers()
    web.post(
        reverse("clients:request_create", args=[company.pk]),
        {"kind": "other", "doc_type": "procuration"},
    )
    request = DocumentRequest.objects.get()
    assert request.title == "Procuration" and request.doc_type == "procuration"
    page = web.get(reverse("clients:document_case", args=[company.pk, "anti-blanchiment"]))
    assert "demandé au client" in page.content.decode()
    web.post(reverse("clients:request_receive", args=[company.pk, request.pk]), {"file": pdf()})
    document = Document.objects.get()
    assert (document.case, document.doc_type) == ("anti-blanchiment", "procuration")


def test_cabinet_documents_cannot_be_requested_from_the_client(web):
    company, _, _ = company_with_managers()
    web.post(
        reverse("clients:request_create", args=[company.pk]),
        {"kind": "other", "doc_type": "fiche_risque"},
    )
    assert not DocumentRequest.objects.exists()


def test_upload_with_type_and_expiry(web):
    company, _, _ = company_with_managers()
    web.post(
        reverse("clients:document_upload", args=[company.pk]),
        {"title": "Fiche de risque 2026", "case": "anti-blanchiment", "doc_type": "fiche_risque",
         "expires_on": "2028-01-31", "file": pdf()},
    )  # fmt: skip
    document = Document.objects.get()
    assert document.doc_type == "fiche_risque" and str(document.expires_on) == "2028-01-31"


def test_mandataire_documents_need_the_person(web):
    company, _, _ = company_with_managers()
    web.post(
        reverse("clients:document_upload", args=[company.pk]),
        {"title": "Id", "case": "anti-blanchiment", "doc_type": "identification_mandataire",
         "file": pdf()},
    )  # fmt: skip
    assert not Document.objects.exists()


def test_persons_have_no_mandataire_or_ubo_lines():
    person = PersonFactory()
    slugs = {r.doc_type.slug for r in types.rows(person, "anti-blanchiment")}
    assert "identification_mandataire" not in slugs and "identification_client" in slugs
