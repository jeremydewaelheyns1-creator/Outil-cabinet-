"""Fabriques factory-boy : données fictives cohérentes pour les tests."""

from typing import Any

import factory
from allauth.mfa.models import Authenticator

from apps.clients.models import Client, Relation
from apps.core.models import Portfolio, SecurityProfile, User

from .numbers import enterprise_number


class SecurityProfileFactory(factory.django.DjangoModelFactory):
    class Meta:
        model = SecurityProfile
        django_get_or_create = ("name",)

    name = factory.Sequence(lambda n: f"Profil {n}")
    capabilities: Any = factory.LazyFunction(list)


class UserFactory(factory.django.DjangoModelFactory):
    class Meta:
        model = User
        skip_postgeneration_save = True

    email = factory.Sequence(lambda n: f"collaborateur{n}@cabinet.test")
    first_name = "Alex"
    last_name = factory.Sequence(lambda n: f"Test{n}")
    initials = factory.Sequence(lambda n: f"T{n}")
    password = factory.django.Password("mot-de-passe-de-test-123")

    @factory.post_generation
    def mfa(obj: User, create: bool, extracted: bool | None, **kwargs: Any) -> None:
        """Par défaut, l'utilisateur a déjà configuré sa double authentification."""
        if create and extracted is not False:
            Authenticator.objects.create(
                user=obj, type=Authenticator.Type.TOTP, data={"secret": "fictif"}
            )

    @factory.post_generation
    def capabilities(obj: User, create: bool, extracted: list[str] | None, **kwargs: Any) -> None:
        if create and extracted:
            obj.profile = SecurityProfileFactory(
                name=f"Profil {'+'.join(sorted(extracted))}", capabilities=list(extracted)
            )
            obj.save()


class PortfolioFactory(factory.django.DjangoModelFactory):
    class Meta:
        model = Portfolio

    name = factory.Sequence(lambda n: f"Portefeuille {n}")


def default_portfolio() -> Portfolio:
    return Portfolio.objects.get(name="Cabinet")


class ClientFactory(factory.django.DjangoModelFactory):
    class Meta:
        model = Client

    kind = Client.Kind.COMPANY
    name = factory.Sequence(lambda n: f"Société Fictive {n}")
    legal_form = "SRL"
    portfolio = factory.LazyFunction(default_portfolio)
    enterprise_number = factory.Sequence(enterprise_number)
    city = "Namur"
    postal_code = "5000"


class PersonFactory(ClientFactory):
    kind = Client.Kind.PERSON
    name = factory.Sequence(lambda n: f"Dupont{n}")
    first_name = "Marie"
    legal_form = ""
    enterprise_number = None


class RelationFactory(factory.django.DjangoModelFactory):
    class Meta:
        model = Relation

    entity = factory.SubFactory(ClientFactory)
    person = factory.SubFactory(PersonFactory)
    role = Relation.Role.SHAREHOLDER
