"""Récapitulatif des mandats SPF du dossier (D-072)."""

import pytest
from django.urls import reverse

from apps.clients import spf
from apps.clients.models import Client, SpfMandate
from apps.core.models import AccessLog
from apps.core.testing.factories import ClientFactory, PersonFactory

pytestmark = pytest.mark.django_db


def test_only_useful_mandates_are_listed():
    company = ClientFactory(vat_status="subject")
    assert spf.needed(company) == ["tva", "biztax", "ubo"]
    company.vat_status = "not_subject"
    company.ubo_filed_by = Client.UboFiler.CLIENT
    assert spf.needed(company) == ["biztax"]  # pas de TVA, registre UBO déposé par le client
    assert spf.needed(PersonFactory()) == ["ipp"]


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


def test_ubo_filer_choice_removes_the_ubo_line(web):
    company = ClientFactory()
    web.post(reverse("clients:spf_mandate_update", args=[company.pk]), {"ubo_filed_by": "client"})
    company.refresh_from_db()
    assert company.ubo_filed_by == "client" and "ubo" not in spf.needed(company)


def test_changing_needs_edit_right(client, make_user):
    company = ClientFactory()
    client.force_login(make_user())
    url = reverse("clients:spf_mandate_update", args=[company.pk])
    assert client.post(url, {"kind": "biztax", "status": "signed"}).status_code == 403
