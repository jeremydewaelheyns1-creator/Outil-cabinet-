"""Création du premier compte à l'installation."""

import pytest
from django.core.management import CommandError, call_command

from apps.core.models import User

pytestmark = pytest.mark.django_db


def test_creates_the_first_admin_from_the_environment(monkeypatch):
    monkeypatch.setenv("PREMIER_COMPTE_MOT_DE_PASSE", "Un-mot-de-passe-fictif-2026")
    call_command("premier_compte", email="Admin@Cabinet-Fictif.test", prenom="Jeremy")
    user = User.objects.get()
    assert user.email == "admin@cabinet-fictif.test" and user.is_superuser
    assert user.check_password("Un-mot-de-passe-fictif-2026")


def test_refused_when_an_account_exists(monkeypatch, make_user):
    make_user()
    monkeypatch.setenv("PREMIER_COMPTE_MOT_DE_PASSE", "Un-mot-de-passe-fictif-2026")
    with pytest.raises(CommandError):
        call_command("premier_compte", email="admin@cabinet-fictif.test")


def test_weak_password_is_refused(monkeypatch):
    monkeypatch.setenv("PREMIER_COMPTE_MOT_DE_PASSE", "1234")
    with pytest.raises(CommandError):
        call_command("premier_compte", email="admin@cabinet-fictif.test")
    assert not User.objects.exists()
