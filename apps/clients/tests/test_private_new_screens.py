"""Écrans ajoutés le 27/10 : un dossier d'un portefeuille privé reste invisible (404)."""

import pytest
from django.test import Client as Browser
from django.urls import reverse

from apps.clients.models import Client
from apps.core.testing.factories import ClientFactory, PortfolioFactory, UserFactory

pytestmark = pytest.mark.django_db


@pytest.mark.parametrize(
    ("name", "method"),
    [
        ("clients:letter_prepare", "get"),
        ("clients:letter_prepare", "post"),
        ("clients:spf_mandate_request", "get"),
        ("clients:spf_mandate_request", "post"),
        ("clients:spf_mandate_update", "post"),
        ("clients:become_client", "post"),
        ("clients:prospect_delete", "get"),
        ("clients:prospect_delete", "post"),
        ("clients:ubo", "get"),
        ("clients:risk_sheet", "get"),
    ],
)
def test_private_dossier_stays_invisible(name, method):
    secret = ClientFactory(portfolio=PortfolioFactory(is_private=True),
                           status=Client.Status.PROSPECT)  # fmt: skip
    browser = Browser()
    browser.force_login(UserFactory(is_staff=True, capabilities=["clients.edit"]))
    url = reverse(name, args=[secret.pk])
    response = getattr(browser, method)(url, {"action": "noter", "confirme": "1"})
    assert response.status_code == 404
    assert Client.objects.filter(pk=secret.pk, status=Client.Status.PROSPECT).exists()
