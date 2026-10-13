"""Vérification des numéros de TVA par l'API REST officielle VIES.

Documentation : https://ec.europa.eu/taxation_customs/vies/#/technical-information
Requête : POST {VIES_API_URL} avec {"countryCode": "BE", "vatNumber": "0403170701"}.
"""

from __future__ import annotations

import logging
from typing import Any

import httpx
from django.conf import settings

from apps.clients.models import Client
from apps.core.models import User

from .models import VatCheck

logger = logging.getLogger(__name__)

# Codes d'erreur VIES qui signifient « réessayez plus tard », pas « numéro invalide ».
TRANSIENT_ERRORS = {
    "MS_UNAVAILABLE",
    "TIMEOUT",
    "SERVICE_UNAVAILABLE",
    "MS_MAX_CONCURRENT_REQ",
    "GLOBAL_MAX_CONCURRENT_REQ",
    "SERVER_BUSY",
}


def _http_client() -> httpx.Client:
    return httpx.Client(timeout=settings.VIES_TIMEOUT_SECONDS)


def check(
    country_code: str,
    vat_number: str,
    *,
    client: Client | None = None,
    user: User | None = None,
    http: httpx.Client | None = None,
) -> VatCheck:
    """Interroge VIES et enregistre le résultat, quel qu'il soit."""
    country_code = country_code.upper()
    vat_number = "".join(c for c in vat_number if c.isalnum()).upper()
    if vat_number.startswith(country_code):
        vat_number = vat_number[len(country_code) :]
    payload: dict[str, Any] = {"countryCode": country_code, "vatNumber": vat_number}
    requester: str = settings.VIES_REQUESTER_VAT
    if requester:
        payload["requesterMemberStateCode"] = requester[:2]
        payload["requesterNumber"] = requester[2:]

    record = VatCheck(
        client=client, country_code=country_code, vat_number=vat_number, checked_by=user
    )
    owns_http = http is None
    session = http or _http_client()
    try:
        response = session.post(settings.VIES_API_URL, json=payload)
        data: dict[str, Any] = response.json() if response.content else {}
        record.raw = data
        error = _error_code(data)
        if response.status_code >= 500 or error in TRANSIENT_ERRORS:
            record.result = VatCheck.Result.UNAVAILABLE
            record.error_code = error or f"HTTP {response.status_code}"
        elif data.get("valid") is True or data.get("isValid") is True:
            record.result = VatCheck.Result.VALID
            record.name = _clean(data.get("name"))[:255]
            record.address = _clean(data.get("address"))
            record.request_identifier = str(data.get("requestIdentifier") or "")[:100]
        else:
            record.result = VatCheck.Result.INVALID
            record.error_code = error[:50]
    except (httpx.HTTPError, ValueError) as exc:
        logger.warning("VIES indisponible : %s", exc)
        record.result = VatCheck.Result.UNAVAILABLE
        record.error_code = type(exc).__name__[:50]
    finally:
        if owns_http:
            session.close()
    record.save()
    return record


def _error_code(data: dict[str, Any]) -> str:
    if data.get("userError") and data["userError"] != "VALID":
        return str(data["userError"])
    wrappers = data.get("errorWrappers") or []
    if wrappers and isinstance(wrappers[0], dict):
        return str(wrappers[0].get("error") or "")
    return ""


def _clean(value: object) -> str:
    """VIES renvoie « --- » quand l'information n'est pas communiquée."""
    text = str(value or "").strip()
    return "" if text in {"---", "-"} else text
