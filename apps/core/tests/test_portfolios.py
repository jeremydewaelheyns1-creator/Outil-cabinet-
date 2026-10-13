"""Droits par portefeuille."""

import pytest
from django.contrib.auth.models import AnonymousUser

from apps.core.models import Portfolio
from apps.core.testing.factories import PortfolioFactory, UserFactory

pytestmark = pytest.mark.django_db


def test_private_portfolio_is_visible_to_members_only():
    member, other = UserFactory(), UserFactory()
    private = PortfolioFactory(is_private=True)
    private.members.add(member)
    public = PortfolioFactory()
    assert set(Portfolio.objects.visible_to(member)) >= {private, public}
    assert private not in Portfolio.objects.visible_to(other)
    assert public in Portfolio.objects.visible_to(other)


def test_superuser_sees_everything_and_anonymous_nothing():
    private = PortfolioFactory(is_private=True)
    admin = UserFactory(is_superuser=True)
    assert private in Portfolio.objects.visible_to(admin)
    assert not Portfolio.objects.visible_to(AnonymousUser()).exists()


def test_inactive_user_sees_nothing():
    user = UserFactory(is_active=False)
    assert not Portfolio.objects.visible_to(user).exists()


def test_default_portfolio_and_profiles_exist():
    from apps.core.models import SecurityProfile

    assert Portfolio.objects.filter(name="Cabinet", is_private=False).exists()
    assert SecurityProfile.objects.filter(name="Collaborateur").exists()
