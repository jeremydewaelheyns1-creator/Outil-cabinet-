"""Assistant IA (D-121) : un seul point de passage vers le fournisseur (Mistral, Europe).

- Éteint tant qu'aucune clé n'est posée (MISTRAL_API_KEY, rangée par le script
  d'installation dans Secret Manager) : tout l'outil marche sans lui.
- Données minimisées : les numéros (national, d'entreprise, TVA, IBAN) et les e-mails sont
  remplacés par des repères avant l'envoi (`privacy.mask`). Les fonctions qui enverraient des
  données de clients restent coupées tant que le cabinet n'a pas confirmé le « zéro
  conservation » du fournisseur (`personal=True`).
- Chaque appel est journalisé (fonction, dossier, jetons, coût) sans le contenu ; plafond de
  dépense mensuel.
- L'IA propose, l'humain décide : rien n'est appliqué sans validation.
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from decimal import Decimal
from typing import Any

from django.conf import settings
from django.db.models import Sum
from django.utils import timezone

from apps.clients.models import Client
from apps.core.models import User

from .models import AiCall

log = logging.getLogger(__name__)

# Prix indicatifs (€ par million de jetons) : pour le plafond mensuel, pas pour la facture.
PRICES: dict[str, tuple[Decimal, Decimal]] = {
    "mistral-small-latest": (Decimal("0.10"), Decimal("0.30")),
    "mistral-medium-latest": (Decimal("0.40"), Decimal("2.00")),
    "mistral-large-latest": (Decimal("2.00"), Decimal("6.00")),
}


class Unavailable(Exception):
    """Assistant éteint, plafond atteint ou fournisseur injoignable : l'outil continue sans."""


def enabled() -> bool:
    return bool(settings.MISTRAL_API_KEY)


def personal_data_allowed() -> bool:
    """Données de clients autorisées seulement si le cabinet a confirmé le « zéro conservation »
    du fournisseur (Réglages du cabinet)."""
    from apps.core.models import CabinetSettings

    return bool(CabinetSettings.current().ai_personal_data)


def spent_this_month() -> Decimal:
    start = timezone.localdate().replace(day=1)
    total = AiCall.objects.filter(created_at__date__gte=start).aggregate(s=Sum("cost_eur"))["s"]
    return total or Decimal(0)


@dataclass
class Answer:
    data: dict[str, Any]
    call: AiCall


def _post(payload: dict[str, Any]) -> dict[str, Any]:
    import httpx

    response = httpx.post(
        settings.AI_ENDPOINT,
        headers={"Authorization": f"Bearer {settings.MISTRAL_API_KEY}"},
        json=payload,
        timeout=60,
    )
    response.raise_for_status()
    result: dict[str, Any] = response.json()
    return result


def ask_json(feature: str, system: str, prompt: str, *, client: Client | None = None,
             user: User | None = None, personal: bool = False,
             model: str | None = None) -> Answer:  # fmt: skip
    """Pose une question et attend une réponse JSON. Lève `Unavailable` si l'assistant ne peut
    pas répondre (l'appelant continue alors sans lui)."""
    if not enabled():
        raise Unavailable("Assistant IA non configuré.")
    if personal and not personal_data_allowed():
        raise Unavailable("Données de clients non autorisées vers l'assistant (zéro conservation).")
    if spent_this_month() >= Decimal(str(settings.AI_MONTHLY_CAP_EUR)):
        raise Unavailable("Plafond mensuel de l'assistant IA atteint.")
    name = model or settings.AI_MODEL
    call = AiCall(feature=feature[:40], client=client, user=user, model=name)
    payload = {
        "model": name,
        "temperature": 0,
        "response_format": {"type": "json_object"},
        "messages": [{"role": "system", "content": system}, {"role": "user", "content": prompt}],
    }
    try:
        result = _post(payload)
        usage = result.get("usage") or {}
        call.tokens_in = int(usage.get("prompt_tokens") or 0)
        call.tokens_out = int(usage.get("completion_tokens") or 0)
        price_in, price_out = PRICES.get(name, PRICES["mistral-medium-latest"])
        call.cost_eur = (call.tokens_in * price_in + call.tokens_out * price_out) / 1_000_000
        content = result["choices"][0]["message"]["content"]
        data = json.loads(content)
        if not isinstance(data, dict):
            raise ValueError("réponse inattendue")
        call.ok = True
        return Answer(data, call)
    except Exception as exc:  # fournisseur injoignable, réponse illisible…
        call.error = type(exc).__name__[:200]  # le type seulement : jamais le contenu
        log.warning("Assistant IA indisponible (%s, %s)", feature, call.error)
        raise Unavailable("L'assistant IA n'a pas pu répondre.") from exc
    finally:
        call.save()
