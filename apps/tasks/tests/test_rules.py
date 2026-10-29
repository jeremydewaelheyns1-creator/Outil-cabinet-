"""Règles d'échéances : jours fériés, dates, conditions, fichier de règles."""

from datetime import date
from pathlib import Path

import pytest

from apps.clients.models import Client
from apps.core.testing.factories import ClientFactory
from apps.tasks.holidays import easter, is_business_day, next_business_day
from apps.tasks.rules import RuleError, load_rules


@pytest.mark.parametrize(
    ("year", "expected"),
    [(2024, date(2024, 3, 31)), (2025, date(2025, 4, 20)), (2026, date(2026, 4, 5)),
     (2027, date(2027, 3, 28))],
)  # fmt: skip
def test_easter(year, expected):
    assert easter(year) == expected


def test_business_days():
    assert next_business_day(date(2026, 7, 21)) == date(2026, 7, 22)  # fête nationale
    assert next_business_day(date(2026, 11, 1)) == date(2026, 11, 2)  # Toussaint, dimanche
    assert next_business_day(date(2026, 4, 6)) == date(2026, 4, 7)  # lundi de Pâques
    assert next_business_day(date(2026, 10, 13)) == date(2026, 10, 13)
    assert not is_business_day(date(2026, 12, 25))


def rule(code):
    found = load_rules().get(code)
    assert found is not None
    return found


def company(**fields):
    defaults = {
        "kind": Client.Kind.COMPANY,
        "status": Client.Status.ACTIVE,
        "vat_status": Client.VatStatus.SUBJECT,
        "vat_periodicity": Client.VatPeriodicity.QUARTERLY,
        "fiscal_year_end_month": 12,
        "fiscal_year_end_day": 31,
    }
    defaults.update(fields)
    return Client(name="Fictive", **defaults)


def test_vat_quarterly_due_the_25th_without_shift_since_october_2025():
    r = rule("tva_trimestrielle")
    periods = {p.key: p for p in r.periods(company(), 2025, 2026)}
    # Trimestriels : le 25, même un dimanche (plus de report depuis le 01/10/2025, D-094).
    assert r.due_date(periods["2026-T3"]) == date(2026, 10, 25)  # dimanche : pas de report
    assert r.due_date(periods["2026-T2"]) == date(2026, 7, 25)  # samedi : pas de report
    # Avant la fin de la tolérance, le report s'appliquait encore.
    assert r.due_date(periods["2025-T2"]) == date(2025, 7, 25)  # vendredi
    assert periods["2026-T3"].label == "3e trimestre 2026"


def test_vat_monthly_weekend_shift():
    r = rule("tva_mensuelle")
    periods = {p.key: p for p in r.periods(company(), 2026, 2026)}
    assert r.due_date(periods["2026-08"]) == date(2026, 9, 21)  # 20/09/2026 = dimanche
    assert periods["2026-08"].label == "août 2026"


def test_fiscal_year_rules_follow_the_closing_date():
    client = company(fiscal_year_end_month=6, fiscal_year_end_day=30)
    agm, isoc = rule("assemblee_generale"), rule("isoc")
    period = next(iter(agm.periods(client, 2026, 2026)))
    assert (period.start, period.end) == (date(2025, 7, 1), date(2026, 6, 30))
    assert agm.due_date(period) == date(2026, 12, 31)
    assert isoc.due_date(period) == date(2027, 1, 31) or isoc.due_date(period) == date(2027, 2, 1)
    assert period.key == "EX-2026-06-30"


def test_listing_due_31_march_next_year():
    r = rule("listing_clients_tva")
    period = next(iter(r.periods(company(), 2026, 2026)))
    assert r.due_date(period) == date(2027, 3, 31)


def test_conditions():
    assert rule("tva_trimestrielle").applies_to(company())
    assert not rule("tva_mensuelle").applies_to(company())
    assert not rule("tva_trimestrielle").applies_to(company(vat_status="franchise"))
    assert rule("listing_clients_tva").applies_to(company(vat_status="franchise"))
    assert not rule("isoc").applies_to(company(fiscal_year_end_month=None))
    assert not rule("isoc").applies_to(company(kind=Client.Kind.PERSON))
    assert not rule("tva_trimestrielle").applies_to(company(status=Client.Status.FORMER))


def test_ipp_published_dates_then_provisional_16_october():
    """D-102 : dates publiées par le SPF, sinon le 16 octobre de l'année suivante, provisoire."""
    r = rule("ipp")
    person = company(kind="person")
    published = next(iter(r.periods(person, 2025, 2025)))
    assert r.due_date(published) == date(2026, 10, 16) and not r.is_provisional(published)
    future = next(iter(r.periods(person, 2027, 2027)))
    assert r.due_date(future) == date(2028, 10, 16) and r.is_provisional(future)
    assert r.first_year == 2026  # rien de rétroactif


def test_ipp_tasks_start_with_2026_income(db):
    from apps.tasks.generator import generate_for_client

    person = ClientFactory(kind=Client.Kind.PERSON)
    generate_for_client(person, date(2026, 10, 29))
    ipp = list(person.tasks.filter(kind="ipp").values_list("period_key", "due_date"))
    assert ipp == [("2026", date(2027, 10, 16))]  # pas les revenus 2025, déjà passés


def test_invalid_rule_files_are_refused(tmp_path: Path):
    bad = tmp_path / "regles.yaml"
    bad.write_text("regles:\n  - code: x\n    periodicite: hebdo\n", encoding="utf-8")
    with pytest.raises(RuleError, match="périodicité"):
        load_rules.__wrapped__(bad)
    bad.write_text(
        "regles:\n  - {code: x, periodicite: annuelle, echeance: {type: date_annee_suivante,"
        " mois: 3, jour: 31}, conditions: {couleur: [bleu]}}\n",
        encoding="utf-8",
    )
    with pytest.raises(RuleError, match="condition"):
        load_rules.__wrapped__(bad)


def test_project_rules_file_is_valid():
    rules = load_rules()
    assert {"tva_mensuelle", "tva_trimestrielle", "isoc", "comptes_annuels"} <= {
        r.code for r in rules.rules
    }
