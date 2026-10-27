"""Récapitulatif des mandats SPF du dossier (D-072)."""

import pytest
from django.urls import reverse

from apps.clients import spf
from apps.clients.models import SpfMandate
from apps.core.models import AccessLog
from apps.core.testing.factories import ClientFactory, PersonFactory

pytestmark = pytest.mark.django_db


def test_only_useful_mandates_are_listed():
    company = ClientFactory(vat_status="subject")
    assert spf.needed(company) == ["tva", "biztax", "ubo", "finprof", "contentieux"]
    company.vat_status = "not_subject"
    assert spf.needed(company) == ["biztax", "ubo", "finprof", "contentieux"]  # pas de TVA
    assert spf.needed(PersonFactory()) == ["ipp", "contentieux"]


def test_lines_are_red_until_signed(web):
    company = ClientFactory(vat_status="subject")
    url = reverse("clients:documents", args=[company.pk])
    page = web.get(url).content.decode()
    assert "TVA (Intervat)" in page and "mandate-danger" in page and "mandate-ok" not in page
    update = reverse("clients:spf_mandate_update", args=[company.pk])
    web.post(update, {"kind": "tva", "status": "signed"})
    assert SpfMandate.objects.get(client=company, kind="tva").status == "signed"
    assert "mandate-ok" in web.get(url).content.decode()
    assert AccessLog.objects.filter(action="update", details__has_key="mandat SPF").exists()
    web.post(update, {"kind": "ipp", "status": "signed"})  # pas utile pour une société
    assert not SpfMandate.objects.filter(kind="ipp").exists()


def test_changing_needs_edit_right(client, make_user):
    company = ClientFactory()
    client.force_login(make_user())
    url = reverse("clients:spf_mandate_update", args=[company.pk])
    assert client.post(url, {"kind": "biztax", "status": "signed"}).status_code == 403


# --- « Demander les mandats manquants » (D-075) ---


def company_with_email():
    from apps.clients.models import ContactPoint

    company = ClientFactory(vat_status="subject", contact_name="Dupont")
    ContactPoint.objects.create(client=company, kind="email", value="compta@fictif.test")
    SpfMandate.objects.create(client=company, kind="tva", status="signed")
    return company


def test_request_page_lists_only_what_is_missing(web):
    company = company_with_email()
    page = web.get(reverse("clients:spf_mandate_request", args=[company.pk])).content.decode()
    assert "Biztax (ISOC)" in page and "4 mandats à signer pour le SPF Finances" in page
    assert "ne pas les recocher" in page and "compta@fictif.test" in page
    docs = web.get(reverse("clients:documents", args=[company.pk])).content.decode()
    assert "Demander les 4 mandats manquants" in docs


def test_send_one_email_and_turn_lines_orange(web, monkeypatch):
    from apps.documents.models import Document
    from apps.outlook import graph

    company = company_with_email()
    sent = []
    link = type("Link", (), {"address": "moi@cabinet-fictif.test"})()
    monkeypatch.setattr(graph, "mailbox_for", lambda user: link)
    monkeypatch.setattr(graph, "send", lambda link, **kw: sent.append(kw))
    url = reverse("clients:spf_mandate_request", args=[company.pk])
    response = web.post(url, {"action": "email"})
    assert response.status_code == 302 and len(sent) == 1
    assert sent[0]["to"] == "compta@fictif.test" and "Registre UBO" in sent[0]["body"]
    statuses = dict(SpfMandate.objects.filter(client=company).values_list("kind", "status"))
    assert statuses == {"tva": "signed", "biztax": "requested", "ubo": "requested",
                        "finprof": "requested", "contentieux": "requested"}  # fmt: skip
    assert Document.objects.filter(client=company, folder="courriels").exists()
    assert (
        "mandate-warning"
        in web.get(reverse("clients:documents", args=[company.pk])).content.decode()
    )


def test_without_outlook_nothing_changes(web, monkeypatch):
    from apps.outlook import graph

    company = company_with_email()
    monkeypatch.setattr(graph, "mailbox_for", lambda user: None)
    web.post(reverse("clients:spf_mandate_request", args=[company.pk]), {"action": "email"})
    assert not SpfMandate.objects.filter(client=company, status="requested").exists()


def test_note_requested_without_email(web):
    company = company_with_email()
    web.post(reverse("clients:spf_mandate_request", args=[company.pk]), {"action": "noter"})
    assert SpfMandate.objects.filter(client=company, status="requested").count() == 4


def test_person_national_number_is_never_shown(web):
    person = PersonFactory(national_number="85073003328")
    page = web.get(reverse("clients:spf_mandate_request", args=[person.pk])).content.decode()
    assert "85073003328" not in page and "85.07.30" not in page and "voir la fiche" in page
