"""Assistant IA (D-121) : éteint sans clé, journal sans contenu, plafond, réglage des modèles.
Le fournisseur n'est jamais appelé : sa réponse est simulée."""

from __future__ import annotations

import json
from decimal import Decimal

import pytest
from django.urls import reverse

from apps.ai import client as ai
from apps.ai import privacy
from apps.ai.models import AiCall

pytestmark = pytest.mark.django_db


def fake_reply(monkeypatch, data, seen=None):
    def post(payload):
        if seen is not None:
            seen.append(payload)
        return {"choices": [{"message": {"content": json.dumps(data)}}],
                "usage": {"prompt_tokens": 1000, "completion_tokens": 200}}  # fmt: skip

    monkeypatch.setattr(ai, "_post", post)


def test_off_without_key(settings):
    settings.MISTRAL_API_KEY = ""
    assert not ai.enabled()
    with pytest.raises(ai.Unavailable):
        ai.ask_json("test", "s", "p")
    assert not AiCall.objects.exists()


def test_call_is_logged_without_content_and_capped(settings, monkeypatch):
    settings.MISTRAL_API_KEY = "fictive"
    fake_reply(monkeypatch, {"ok": True})
    answer = ai.ask_json("test", "système", "question confidentielle")
    assert answer.data == {"ok": True}
    call = AiCall.objects.get()
    assert call.ok and call.tokens_in == 1000 and call.cost_eur > 0
    assert "confidentielle" not in json.dumps([str(v) for v in call.__dict__.values()])
    settings.AI_MONTHLY_CAP_EUR = float(call.cost_eur)  # plafond atteint
    with pytest.raises(ai.Unavailable):
        ai.ask_json("test", "s", "p")


def test_personal_data_can_be_cut_off(settings, monkeypatch):
    from apps.core.models import CabinetSettings

    settings.MISTRAL_API_KEY = "fictive"
    fake_reply(monkeypatch, {})
    current = CabinetSettings.current()
    assert current.ai_personal_data  # actif d'office (D-127)
    current.ai_personal_data = False
    current.save()
    with pytest.raises(ai.Unavailable):
        ai.ask_json("documents", "s", "p", personal=True)


def test_provider_failure_is_logged_and_tool_goes_on(settings, monkeypatch):
    settings.MISTRAL_API_KEY = "fictive"

    def broken(payload):
        raise ConnectionError("injoignable")

    monkeypatch.setattr(ai, "_post", broken)
    with pytest.raises(ai.Unavailable):
        ai.ask_json("test", "s", "p")
    call = AiCall.objects.get()
    assert not call.ok and call.error == "ConnectionError" and call.cost_eur == Decimal(0)


def test_identifiers_are_masked():
    text = "BE 0412.345.678, NN 85.07.30-033.28, IBAN BE68 5390 0754 7034, a@b.be"
    masked = privacy.mask(text)
    for secret in ("0412", "85.07.30", "5390", "a@b.be"):
        assert secret not in masked


def _unknown_pdf(web, text):
    from apps.documents.models import InboxItem
    from apps.documents.tests.test_official_files import pdf

    web.post(reverse("depot:index"), {"files": [pdf("courrier.pdf", text)]})
    return InboxItem.objects.get()


def test_unknown_document_is_read_in_the_background(web, user, settings, monkeypatch):
    from apps.core.models import CabinetSettings
    from apps.core.testing.factories import ClientFactory
    from apps.documents.models import Document, InboxItem

    client = ClientFactory(name="Menuiserie Fictive")
    settings.MISTRAL_API_KEY = "fictive"
    seen = []
    fake_reply(monkeypatch, {"titre": "Taxe communale 2025", "dossier": "administratif",
                             "nom": "Menuiserie Fictive"}, seen)  # fmt: skip
    # Le cabinet a coupé la lecture des documents : rien ne part.
    CabinetSettings.objects.update_or_create(pk=1, defaults={"ai_personal_data": False})
    item = _unknown_pdf(web, "Courrier de la commune pour Menuiserie Fictive : taxe 2025.")
    assert item.suggestion == {} and not seen
    item.delete()
    CabinetSettings.objects.filter(pk=1).update(ai_personal_data=True)
    # Déposé : l'assistant le lit tout seul, la proposition est là, sans bouton à cliquer.
    item = _unknown_pdf(web, "Courrier de la commune pour Menuiserie Fictive : taxe 2025.")
    assert item.suggestion["client"] == client.pk
    assert item.suggestion["place"] == "folder:administratif"
    assert "Menuiserie Fictive" in seen[0]["messages"][1]["content"]
    page = web.get(reverse("depot:index")).content.decode()
    assert "Ranger ainsi" in page and "assistant" not in page.lower()
    # Rien n'est rangé avant le clic ; le clic range.
    assert not Document.objects.filter(client=client).exists()
    web.post(
        reverse("depot:classify", args=[item.pk]),
        {"client": client.pk, "place": "folder:administratif", "title": "Taxe communale 2025"},
    )
    assert Document.objects.get(client=client).title == "Taxe communale 2025"
    assert AiCall.objects.get(feature="classement_document").client == client
    assert InboxItem.objects.count() == 0


def test_numbers_are_masked_before_the_document_leaves(web, settings, monkeypatch):
    from apps.core.models import CabinetSettings

    item = _unknown_pdf(web, "Lettre libre. Compte BE68 5390 0754 7034. Contact : x@y.be")
    settings.MISTRAL_API_KEY = "fictive"
    current = CabinetSettings.current()
    current.ai_personal_data = True
    current.save()
    seen = []
    fake_reply(monkeypatch, {"titre": None, "dossier": None, "nom": None}, seen)
    web.post(reverse("depot:assist", args=[item.pk]))
    sent = seen[0]["messages"][1]["content"]
    assert "5390" not in sent and "x@y.be" not in sent and "[IBAN]" in sent


def test_no_assistant_setting_to_manage(client, make_user, settings):
    from apps.core.models import CabinetSettings

    client.force_login(make_user(is_staff=True))
    settings.MISTRAL_API_KEY = "fictive"
    page = client.get(reverse("core:cabinet_settings")).content.decode()
    assert "<h2>Assistant IA</h2>" not in page and 'name="ai_personal_data"' not in page
    assert CabinetSettings.current().ai_personal_data  # actif d'office (D-127)


def test_the_settings_say_why_the_assistant_does_not_answer(client, make_user, settings,
                                                            monkeypatch):  # fmt: skip
    import httpx

    client.force_login(make_user(is_staff=True))
    settings.MISTRAL_API_KEY = ""
    assert "pas branché" in client.get(reverse("core:cabinet_settings")).content.decode()
    settings.MISTRAL_API_KEY = "fictive"

    def refused(payload):
        request = httpx.Request("POST", "https://api.eu.mistral.ai/v1/chat/completions")
        raise httpx.HTTPStatusError("401", request=request,
                                    response=httpx.Response(401, request=request))  # fmt: skip

    monkeypatch.setattr(ai, "_post", refused)
    with pytest.raises(ai.Unavailable):
        ai.ask_json("test", "s", "p")
    page = client.get(reverse("core:cabinet_settings")).content.decode()
    assert "ne répond pas" in page and "clé refusée (401)" in page
    fake_reply(monkeypatch, {"ok": True})
    ai.ask_json("test", "s", "p")
    assert "actif · 1 réponse(s)" in client.get(reverse("core:cabinet_settings")).content.decode()
