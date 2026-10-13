import pytest
from django.core.exceptions import ValidationError

from apps.clients.identifiers import (
    format_enterprise_number,
    mask_national_number,
    normalize_enterprise_number,
    normalize_national_number,
    vat_number_from_enterprise_number,
)
from apps.core.testing.numbers import enterprise_number, national_number


@pytest.mark.parametrize(
    "raw", ["BE 0403.170.701", "0403 170 701", "be0403170701", "403170701", " 0403.170.701 "]
)
def test_enterprise_number_variants_are_normalized(raw):
    assert normalize_enterprise_number(raw) == "0403170701"


def test_invalid_enterprise_number_is_rejected():
    with pytest.raises(ValidationError):
        normalize_enterprise_number("0403.170.702")


def test_empty_values_are_accepted():
    assert normalize_enterprise_number("") == ""
    assert normalize_enterprise_number(None) == ""
    assert normalize_national_number("  ") == ""


def test_formats():
    assert format_enterprise_number("0403170701") == "0403.170.701"
    assert vat_number_from_enterprise_number("0403170701") == "BE0403170701"
    assert vat_number_from_enterprise_number("") == ""


def test_national_number_is_normalized_and_masked():
    number = national_number(1)
    formatted = f"{number[:2]}.{number[2:4]}.{number[4:6]}-{number[6:9]}.{number[9:]}"
    assert normalize_national_number(formatted) == number
    assert mask_national_number(number) == "85.07.30-•••.••"
    assert mask_national_number("") == ""


def test_invalid_national_number_message_does_not_echo_the_value():
    with pytest.raises(ValidationError) as error:
        normalize_national_number("85073000200")
    assert "85073000200" not in str(error.value)


def test_fictional_generators_are_valid():
    assert normalize_enterprise_number(enterprise_number(42)) == enterprise_number(42)
