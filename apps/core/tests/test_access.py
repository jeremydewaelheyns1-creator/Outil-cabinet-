"""Accès : connexion obligatoire, double authentification obligatoire, droits."""

import pytest
from django.test import override_settings
from django.urls import reverse

from apps.core.models import AccessLog
from apps.core.testing.factories import UserFactory

pytestmark = pytest.mark.django_db


def test_anonymous_is_sent_to_login(client):
    response = client.get(reverse("core:home"))
    assert response.status_code == 302
    assert response.url.startswith(reverse("account_login"))


def test_login_page_and_health_are_public(client):
    assert client.get(reverse("account_login")).status_code == 200
    response = client.get("/sante/")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


@override_settings(ALLOWED_HOSTS=["outil.example.be"], SECURE_SSL_REDIRECT=True)
def test_health_check_answers_internal_probes(client):
    response = client.get("/sante/", HTTP_HOST="10.0.0.5:8080")
    assert response.status_code == 200


def test_user_without_second_factor_must_configure_it(client):
    user = UserFactory(mfa=False)
    client.force_login(user)
    response = client.get(reverse("clients:list"))
    assert response.status_code == 302
    assert response.url == reverse("mfa_index")
    # L'écran de configuration lui-même reste accessible.
    assert client.get(reverse("mfa_index")).status_code == 200
    assert client.get(reverse("mfa_activate_totp")).status_code in (200, 302)


def test_user_with_second_factor_reaches_home(web):
    response = web.get(reverse("core:home"))
    assert response.status_code == 200
    assert "Mes dossiers" in response.content.decode()


def test_signup_is_closed(client):
    response = client.get(reverse("account_signup"))
    assert response.status_code in (200, 302)
    assert b'name="password2"' not in response.content


def test_admin_login_goes_through_application_login(client):
    response = client.get(reverse("admin:index"))
    assert response.status_code == 302
    follow = client.get(response.url)
    assert follow.status_code == 302
    assert follow.url.startswith(reverse("account_login"))


def test_failed_login_is_logged(client):
    UserFactory(email="quelquun@cabinet.test")
    client.post(reverse("account_login"), {"login": "quelquun@cabinet.test", "password": "mauvais"})
    entry = AccessLog.objects.get(action=AccessLog.Action.LOGIN_FAILED)
    assert entry.details["identifiant_saisi"] == "quelquun@cabinet.test"


def test_successful_password_step_asks_for_second_factor(client):
    UserFactory(email="totp@cabinet.test")
    response = client.post(
        reverse("account_login"),
        {"login": "totp@cabinet.test", "password": "mot-de-passe-de-test-123"},
    )
    assert response.status_code == 302
    assert response.url == reverse("mfa_authenticate")
    # Pas encore connecté : le second facteur n'a pas été donné.
    assert client.get(reverse("core:home")).status_code == 302


def test_access_log_requires_capability(web, make_user, client):
    assert web.get(reverse("core:access_log")).status_code == 403
    auditor = make_user(capabilities=["audit.view"])
    client.force_login(auditor)
    assert client.get(reverse("core:access_log")).status_code == 200


def test_admin_login_cannot_switch_to_another_account(web, user):
    """L'écran de connexion de l'administration ne doit jamais ouvrir de session sans 2FA."""
    UserFactory(email="chef@cabinet.test", is_staff=True, is_superuser=True)
    response = web.post(
        reverse("admin:login"),
        {"username": "chef@cabinet.test", "password": "mot-de-passe-de-test-123"},
    )
    assert response.status_code == 403
    assert int(web.session["_auth_user_id"]) == user.pk
    assert web.get(reverse("admin:index")).status_code in (302, 403)


def test_staff_reaches_admin_through_application_login(client):
    staff = UserFactory(is_staff=True, is_superuser=True)
    client.force_login(staff)
    assert client.get(reverse("admin:index")).status_code == 200
    assert client.get(reverse("admin:login")).status_code == 302


def test_settings_page_only_for_admin_tools(web, make_user, client):
    assert web.get(reverse("core:settings")).status_code == 403
    assert "Paramètres" not in web.get(reverse("core:home")).content.decode()  # masqué du menu
    auditor = make_user(capabilities=["audit.view"])
    client.force_login(auditor)
    html = client.get(reverse("core:settings")).content.decode()
    assert "Journal des consultations" in html and "Reprise FID-Manager" not in html
