"""Mot de passe oublié (D-081) : lien par Outlook, sans copie, 1 heure ; dépannage Cloud Shell."""

import re

import pytest
from django.core.management import CommandError, call_command
from django.test import Client as Browser
from django.urls import reverse

from apps.core.models import AccessLog, User
from apps.core.testing.factories import UserFactory
from apps.outlook import graph

pytestmark = pytest.mark.django_db


@pytest.fixture
def outlook(monkeypatch):
    sent = []
    link = type("Link", (), {"address": "admin@cabinet-fictif.test"})()
    monkeypatch.setattr(graph, "mailbox_for", lambda user: link if user and user.is_staff else None)
    monkeypatch.setattr(graph, "send", lambda link, **kw: sent.append(kw))
    return sent


def test_login_page_offers_forgotten_password(client):
    assert "Mot de passe oublié" in client.get(reverse("account_login")).content.decode()


def test_reset_link_by_outlook_without_copy_then_new_password(outlook):
    UserFactory(is_staff=True, email="admin@cabinet-fictif.test")
    user = UserFactory(email="employe@cabinet-fictif.test")
    browser = Browser()
    browser.post(reverse("account_reset_password"), {"email": "employe@cabinet-fictif.test"})
    assert len(outlook) == 1 and outlook[0]["keep_copy"] is False
    assert outlook[0]["to"] == "employe@cabinet-fictif.test" and "une heure" in outlook[0]["body"]
    url = re.search(r"https?://\S+", outlook[0]["body"]).group(0)
    path = "/" + url.split("://", 1)[1].split("/", 1)[1]
    page = browser.get(path, follow=True)
    action = page.redirect_chain[-1][0] if page.redirect_chain else path
    new = "Fictif-Nouveau-2026!"
    browser.post(action, {"password1": new, "password2": new})
    user.refresh_from_db()
    assert user.check_password(new)
    assert AccessLog.objects.filter(details__has_key="mot de passe").exists()


def test_unknown_address_gets_no_email_and_same_answer(outlook):
    UserFactory(is_staff=True)
    response = Browser().post(reverse("account_reset_password"), {"email": "inconnu@ailleurs.test"})
    assert response.status_code == 302 and outlook == []


def test_cloud_shell_command_sets_the_password(monkeypatch):
    user = UserFactory(email="jeremy@cabinet-fictif.test")
    monkeypatch.setenv("NOUVEAU_MOT_DE_PASSE", "Fictif-Depannage-2026!")
    call_command("nouveau_mot_de_passe", "--email", "Jeremy@cabinet-fictif.test")
    user.refresh_from_db()
    assert user.check_password("Fictif-Depannage-2026!")


def test_cloud_shell_command_hints_masked_admins_for_unknown_address(monkeypatch):
    UserFactory(is_staff=True, email="jeremy@cabinet-fictif.test")
    monkeypatch.setenv("NOUVEAU_MOT_DE_PASSE", "Fictif-Depannage-2026!")
    with pytest.raises(CommandError) as error:
        call_command("nouveau_mot_de_passe", "--email", "autre@ailleurs.test")
    assert "j•••@c•••.test" in str(error.value) and "jeremy@" not in str(error.value)
    assert not User.objects.filter(email="autre@ailleurs.test").exists()
