"""Calcul des bénéficiaires effectifs sur des structures fictives."""

from datetime import date
from decimal import Decimal

import pytest
from django.test import override_settings

from apps.clients.models import Client, Relation
from apps.clients.services.ubo import Basis, analyse
from apps.core.testing.factories import ClientFactory, PersonFactory, RelationFactory

pytestmark = pytest.mark.django_db


def holds(holder: Client, entity: Client, share: str | None, voting: str | None = None):
    return RelationFactory(
        entity=entity,
        person=holder,
        share_percentage=None if share is None else Decimal(share),
        voting_percentage=None if voting is None else Decimal(voting),
    )


def manages(person: Client, entity: Client, role=Relation.Role.MANAGER):
    return RelationFactory(entity=entity, person=person, role=role)


def names(analysis) -> set[str]:
    return {c.person.name for c in analysis.candidates}


def test_direct_shareholders_above_threshold():
    company = ClientFactory()
    anne, bob, carl = (PersonFactory(name=n) for n in ("Anne", "Bob", "Carl"))
    holds(anne, company, "60")
    holds(bob, company, "26")
    holds(carl, company, "14")
    result = analyse(company)
    assert names(result) == {"Anne", "Bob"}
    assert [c.person.name for c in result.below_threshold] == ["Carl"]


def test_exactly_25_percent_depends_on_the_legal_rule():
    company = ClientFactory()
    for name in ("A", "B", "C", "D"):
        holds(PersonFactory(name=name), company, "25")
    result = analyse(company)
    assert not result.candidates  # « plus de 25 % » : personne, et aucun dirigeant encodé
    with override_settings(UBO_THRESHOLD_INCLUSIVE=True):
        assert names(analyse(company)) == {"A", "B", "C", "D"}


def test_voting_rights_count_separately_from_capital():
    company = ClientFactory()
    founder = PersonFactory(name="Fondatrice")
    holds(founder, company, "10", "40")
    assert names(analyse(company)) == {"Fondatrice"}


def test_indirect_holding_through_controlled_company():
    target, holding = ClientFactory(name="Cible"), ClientFactory(name="Holding")
    owner = PersonFactory(name="Owner")
    holds(holding, target, "30")
    holds(owner, holding, "60")
    result = analyse(target)
    candidate = result.candidates[0]
    assert candidate.person == owner
    # Capital : 60 % × 30 % = 18 % ; votes : contrôle de la holding → 30 %.
    assert candidate.share_percentage == Decimal("18")
    assert candidate.voting_percentage == Decimal("30")
    assert [c.name for c in candidate.holdings[0].chain] == ["Owner", "Holding", "Cible"]


def test_indirect_holding_without_control_is_multiplied():
    target, holding = ClientFactory(), ClientFactory()
    minority = PersonFactory(name="Minoritaire")
    holds(holding, target, "80")
    holds(minority, holding, "40")
    result = analyse(target)
    assert names(result) == {"Minoritaire"}  # 40 % × 80 % = 32 %
    assert result.candidates[0].share_percentage == Decimal("32")


def test_paths_are_added_together():
    target, holding = ClientFactory(), ClientFactory()
    person = PersonFactory(name="Cumul")
    holds(person, target, "15")
    holds(holding, target, "40")
    holds(person, holding, "30")  # 30 % × 40 % = 12 % → total 27 %
    assert names(analyse(target)) == {"Cumul"}


def test_fallback_to_managers_when_nobody_reaches_threshold():
    company = ClientFactory()
    for name in ("A", "B", "C", "D", "E"):
        holds(PersonFactory(name=name), company, "20")
    gerant = PersonFactory(name="Gérant")
    manages(gerant, company)
    result = analyse(company)
    assert names(result) == {"Gérant"}
    assert result.candidates[0].basis == Basis.FALLBACK_MANAGEMENT


def test_nonprofit_uses_directors():
    asbl = ClientFactory(kind=Client.Kind.NONPROFIT, legal_form="ASBL")
    president = PersonFactory(name="Présidente")
    manages(president, asbl, Relation.Role.DIRECTOR)
    result = analyse(asbl)
    assert names(result) == {"Présidente"}
    assert result.candidates[0].basis == Basis.NONPROFIT_MANAGEMENT


def test_declared_and_computed_are_compared():
    company = ClientFactory()
    anne, ancien = PersonFactory(name="Anne"), PersonFactory(name="Ancien")
    holds(anne, company, "100")
    RelationFactory(entity=company, person=ancien, role=Relation.Role.BENEFICIAL_OWNER)
    result = analyse(company)
    assert [p.name for p in result.missing] == ["Anne"]
    assert [p.name for p in result.unexpected] == ["Ancien"]
    assert not result.is_consistent


def test_unknown_structure_is_flagged_not_hidden():
    target, opaque = ClientFactory(), ClientFactory(name="Opaque")
    holds(opaque, target, "70")
    holds(PersonFactory(), target, None)
    result = analyse(target)
    assert [e.name for e in result.unresolved_entities] == ["Opaque"]
    assert len(result.unknown_percentages) == 1
    assert not result.is_complete


def test_circular_holdings_do_not_loop():
    a, b = ClientFactory(), ClientFactory()
    holds(a, b, "50")
    holds(b, a, "50")
    holds(PersonFactory(name="P"), a, "50")
    result = analyse(a)
    assert "P" in names(result)


def test_ended_relations_are_ignored():
    company = ClientFactory()
    former = holds(PersonFactory(name="Cédant"), company, "100")
    former.end_date = date(2020, 1, 1)
    former.save()
    assert "Cédant" not in names(analyse(company))
