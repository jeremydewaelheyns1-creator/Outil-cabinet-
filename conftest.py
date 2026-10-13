"""Fixtures communes à tous les tests."""

from collections.abc import Callable
from typing import Any

import pytest
from django.test import Client as HttpClient

from apps.core.models import User
from apps.core.testing.factories import UserFactory


@pytest.fixture
def make_user(db: None) -> Callable[..., User]:
    def make(**kwargs: Any) -> User:
        return UserFactory(**kwargs)

    return make


@pytest.fixture
def user(make_user: Callable[..., User]) -> User:
    """Collaborateur standard : peut modifier les fiches, double authentification active."""
    return make_user(capabilities=["clients.edit"])


@pytest.fixture
def web(client: HttpClient, user: User) -> HttpClient:
    """Navigateur connecté avec `user`."""
    client.force_login(user)
    return client
