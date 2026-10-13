"""Vérification VIES avec un service simulé (aucun appel réseau)."""

import httpx
import pytest

from apps.integrations import vies
from apps.integrations.models import VatCheck

pytestmark = pytest.mark.django_db


def fake(status: int = 200, payload: dict | None = None, error: Exception | None = None):
    def handler(request: httpx.Request) -> httpx.Response:
        if error:
            raise error
        assert request.method == "POST"
        return httpx.Response(status, json=payload or {})

    return httpx.Client(transport=httpx.MockTransport(handler))


def test_valid_number_is_recorded_with_proof():
    payload = {"valid": True, "name": "SRL FICTIVE", "address": "RUE FICTIVE 1\n5000 NAMUR",
               "requestIdentifier": "WAPIAAAA"}  # fmt: skip
    check = vies.check("BE", "BE 0403.170.701", http=fake(payload=payload))
    assert check.result == VatCheck.Result.VALID
    assert check.vat_number == "0403170701"
    assert check.request_identifier == "WAPIAAAA"
    assert VatCheck.objects.count() == 1


def test_invalid_number():
    check = vies.check("BE", "0403170701", http=fake(payload={"valid": False, "name": "---"}))
    assert check.result == VatCheck.Result.INVALID
    assert check.name == ""


def test_member_state_unavailable_is_not_reported_as_invalid():
    payload = {"actionSucceed": False, "errorWrappers": [{"error": "MS_UNAVAILABLE"}]}
    check = vies.check("BE", "0403170701", http=fake(payload=payload))
    assert check.result == VatCheck.Result.UNAVAILABLE
    assert check.error_code == "MS_UNAVAILABLE"


def test_network_error_is_recorded():
    check = vies.check("BE", "0403170701", http=fake(error=httpx.ConnectTimeout("lent")))
    assert check.result == VatCheck.Result.UNAVAILABLE
    assert check.error_code == "ConnectTimeout"


def test_server_error():
    assert vies.check("BE", "0403170701", http=fake(status=503)).result == "unavailable"
