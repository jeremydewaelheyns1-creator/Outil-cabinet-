import pytest
from django.core.exceptions import ValidationError

from apps.clients.models import Client, Relation
from apps.core.testing.factories import (
    ClientFactory,
    PersonFactory,
    PortfolioFactory,
    RelationFactory,
    UserFactory,
)
from apps.core.testing.numbers import national_number

pytestmark = pytest.mark.django_db


def test_display_name():
    assert PersonFactory.build(name="Dupont", first_name="Marie").display_name == "Dupont Marie"
    assert ClientFactory.build(name="Boulangerie Fictive", legal_form="SRL").display_name == (
        "Boulangerie Fictive SRL"
    )


def test_empty_identifiers_are_stored_as_null_so_several_clients_can_lack_them():
    ClientFactory(enterprise_number="", reference="  ")
    ClientFactory(enterprise_number="", reference="")
    assert (
        Client.objects.filter(enterprise_number__isnull=True, reference__isnull=True).count() == 2
    )


def test_person_requires_first_name_and_company_cannot_have_national_number():
    with pytest.raises(ValidationError) as error:
        PersonFactory.build(first_name="").full_clean()
    assert "first_name" in error.value.message_dict
    company = ClientFactory.build(national_number=national_number(3))
    with pytest.raises(ValidationError) as error:
        company.full_clean()
    assert "national_number" in error.value.message_dict


def test_fiscal_year_end_must_exist():
    client = ClientFactory.build(fiscal_year_end_month=2, fiscal_year_end_day=30)
    with pytest.raises(ValidationError) as error:
        client.full_clean()
    assert "fiscal_year_end_day" in error.value.message_dict


def test_search_ignores_accents_and_case_and_finds_numbers():
    target = ClientFactory(name="Société Générale Fictive")
    ClientFactory(name="Autre")
    assert list(Client.objects.search("societe generale")) == [target]
    assert list(Client.objects.search(target.enterprise_number_display)) == [target]
    assert list(Client.objects.search(f"BE{target.enterprise_number}")) == [target]
    person = PersonFactory(name="Lefèvre", first_name="Hélène")
    assert list(Client.objects.search("helene lefevre")) == [person]
    assert list(Client.objects.search("Lefevre Helene")) == [person]


def test_general_search_never_matches_national_number():
    number = national_number(5)
    PersonFactory(national_number=number, name="Sans", first_name="Rapport")
    assert list(Client.objects.search(number)) == []


def test_visible_to_respects_private_portfolios():
    member, outsider = UserFactory(), UserFactory()
    private = PortfolioFactory(is_private=True)
    private.members.add(member)
    hidden = ClientFactory(portfolio=private)
    shared = ClientFactory()
    assert set(Client.objects.visible_to(member)) == {hidden, shared}
    assert set(Client.objects.visible_to(outsider)) == {shared}


def test_relation_rules():
    company, person = ClientFactory(), PersonFactory()
    with pytest.raises(ValidationError):
        Relation(entity=company, person=company, role=Relation.Role.MANAGER).full_clean()
    with pytest.raises(ValidationError):
        Relation(
            entity=company, person=person, role=Relation.Role.MANAGER, share_percentage=10
        ).full_clean()
    relation = RelationFactory(entity=company, person=person, share_percentage=50)
    assert relation in Relation.objects.current()


def test_history_is_kept():
    client = ClientFactory(name="Avant")
    client.name = "Après"
    client.save()
    assert [h.name for h in client.history.all()] == ["Après", "Avant"]
