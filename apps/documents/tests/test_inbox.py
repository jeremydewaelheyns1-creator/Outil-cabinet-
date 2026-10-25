"""Dépôt unique (D-041) : l'outil trouve seul le dossier, sinon « À classer ». Données fictives."""

from datetime import timedelta

import pytest
from django.core.files.uploadedfile import SimpleUploadedFile
from django.db import transaction
from django.urls import reverse
from django.utils import timezone

from apps.clients.models import Client
from apps.core.models import AccessLog
from apps.core.testing.factories import ClientFactory, PortfolioFactory
from apps.documents import identity, inbox
from apps.documents.models import Document, IdentityCard, InboxItem
from apps.documents.tests.test_identity import card_text, setup_company
from apps.vat.models import VatFiling
from apps.vat.tests.test_vat import vat_xml

pytestmark = pytest.mark.django_db

PDF = b"%PDF-1.4\n% document fictif\n"
PNG = b"\x89PNG\r\n\x1a\n" + b"0" * 20


@pytest.fixture
def card_reader(monkeypatch):
    """La lecture (OCR) renvoie un texte fourni par le test ; événements exécutés aussitôt."""
    box = {"text": None}
    monkeypatch.setattr(identity, "CARD_READER", lambda content, content_type: box["text"])
    monkeypatch.setattr(transaction, "on_commit", lambda func, *a, **k: func())
    return box


def test_drop_page_is_in_the_top_bar(web):
    html = web.get(reverse("core:home")).content.decode()
    assert reverse("depot:index") in html


def test_read_only_user_cannot_drop(client, make_user):
    client.force_login(make_user())
    assert client.get(reverse("depot:index")).status_code == 403


def test_vat_xml_goes_to_its_dossier(web):
    company = ClientFactory(vat_status="subject", vat_periodicity="quarterly")
    files = [SimpleUploadedFile("d.xml", vat_xml(company.enterprise_number))]
    web.post(reverse("depot:index"), {"files": files})
    assert VatFiling.objects.get(client=company).xml is not None
    assert not InboxItem.objects.exists()
    assert AccessLog.objects.filter(action="import", object_id=str(company.pk)).exists()


def test_identity_card_is_recognised_and_applied(web, card_reader):
    _, person = setup_company()
    card_reader["text"] = card_text(person)
    web.post(reverse("depot:index"), {"files": [SimpleUploadedFile("scan.png", PNG)]})
    document = Document.objects.get(case="pieces-identite")
    assert document.person == person
    card = IdentityCard.objects.get(person=person)
    assert card.auto_applied and card.document == document
    assert not InboxItem.objects.exists()


def test_card_goes_to_the_company_when_the_person_is_not_a_client(web, card_reader):
    company, person = setup_company()
    Client.objects.filter(pk=person.pk).update(status=Client.Status.PROSPECT)
    person.refresh_from_db()
    card_reader["text"] = card_text(person)
    web.post(reverse("depot:index"), {"files": [SimpleUploadedFile("scan.png", PNG)]})
    assert Document.objects.get(case="pieces-identite").client == company


def test_card_of_someone_without_a_file_waits_to_be_classified(web, card_reader):
    _, person = setup_company()
    card_reader["text"] = card_text(person, nn="85073000655")  # numéro d'une autre personne
    web.post(reverse("depot:index"), {"files": [SimpleUploadedFile("scan.png", PNG)]})
    assert not Document.objects.exists()
    item = InboxItem.objects.get()
    assert "aucune fiche" in item.reason and "85073000655" not in item.reason


def test_card_of_a_hidden_person_is_not_filed(web, card_reader):
    hidden = ClientFactory(portfolio=PortfolioFactory(is_private=True), kind="person",
                           name="Cachée", first_name="Anne", enterprise_number=None,
                           national_number="85073000655")  # fmt: skip
    card_reader["text"] = card_text(hidden)
    web.post(reverse("depot:index"), {"files": [SimpleUploadedFile("scan.png", PNG)]})
    assert not Document.objects.exists() and InboxItem.objects.count() == 1


def test_unknown_document_is_only_visible_to_its_author(web, client, make_user, user):
    web.post(reverse("depot:index"), {"files": [SimpleUploadedFile("facture.pdf", PDF)]})
    item = InboxItem.objects.get()
    assert item.uploaded_by == user
    assert "facture.pdf" in web.get(reverse("depot:index")).content.decode()
    response = web.get(reverse("depot:file", args=[item.pk]))
    assert response.status_code == 200 and "sandbox" in response["Content-Security-Policy"]
    colleague = make_user(capabilities=["clients.edit"])
    client.force_login(colleague)
    assert "facture.pdf" not in client.get(reverse("depot:index")).content.decode()
    assert client.get(reverse("depot:file", args=[item.pk])).status_code == 404
    assert client.post(reverse("depot:delete", args=[item.pk])).status_code == 404


def test_classify_by_hand_in_two_steps(web):
    company = ClientFactory()
    web.post(reverse("depot:index"), {"files": [SimpleUploadedFile("statuts.pdf", PDF)]})
    item = InboxItem.objects.get()
    url = reverse("depot:classify", args=[item.pk])
    html = web.post(url, {"client": company.pk}).content.decode()
    assert "Archives › Légal et statuts" in html and "Documents › Lettre de mission" in html
    web.post(url, {"client": company.pk, "place": "folder:legal", "title": "Statuts 2020"})
    document = Document.objects.get(client=company)
    assert (document.folder, document.title) == ("legal", "Statuts 2020")
    assert not InboxItem.objects.exists()


def test_cannot_classify_into_a_hidden_dossier_or_an_unknown_place(web):
    hidden = ClientFactory(portfolio=PortfolioFactory(is_private=True))
    company = ClientFactory()
    web.post(reverse("depot:index"), {"files": [SimpleUploadedFile("x.pdf", PDF)]})
    item = InboxItem.objects.get()
    url = reverse("depot:classify", args=[item.pk])
    web.post(url, {"client": hidden.pk, "place": "folder:legal"})
    web.post(url, {"client": company.pk, "place": "folder:../../etc"})
    assert not Document.objects.exists() and InboxItem.objects.exists()


def test_refused_formats_are_not_kept(web):
    web.post(reverse("depot:index"), {"files": [SimpleUploadedFile("x.exe", b"MZ0000")]})
    assert not InboxItem.objects.exists()


def test_unclassified_files_are_deleted_after_the_retention(web, settings):
    settings.INBOX_RETENTION_DAYS = 30
    web.post(reverse("depot:index"), {"files": [SimpleUploadedFile("x.pdf", PDF)]})
    assert inbox.purge() == 0
    assert inbox.purge(timezone.now() + timedelta(days=31)) == 1
    assert not InboxItem.objects.exists()
