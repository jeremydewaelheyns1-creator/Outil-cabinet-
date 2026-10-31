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


def test_assistant_sets_holes_of_a_model_and_stays_invisible(settings, monkeypatch, client,
                                                             make_user):  # fmt: skip
    from apps.ai import templates_assist
    from apps.closing.tests.test_pv_ag import install
    from apps.documents import letter

    admin = make_user(is_staff=True, capabilities=["clients.edit"])
    client.force_login(admin)
    template, _ = install(client)
    holes = letter.holes(bytes(template.content), "pv_ag")
    settings.MISTRAL_API_KEY = "fictive"
    first = next(i for i, t in letter.paragraphs(bytes(template.content)) if "reporter" in t)
    fake_reply(monkeypatch, {
        "trous": {holes[0].key: {"code": "client.denomination", "question": ""},
                  holes[1].key: {"code": "code-inventé", "question": ""}},
        "paragraphes": {str(first): "sans_dividende", "999": "dividende"},
    })  # fmt: skip
    templates_assist.suggest(template, admin)
    template.refresh_from_db()
    assert template.holes[holes[0].key]["source"] == "assistant"
    assert template.holes[holes[1].key].get("source") != "assistant"  # code inconnu : ignoré
    assert template.options[str(first)]["condition"] == "sans_dividende"
    assert "999" not in template.options and not template.active
    page = client.get(reverse("lettre:model", args=[template.pk])).content.decode()
    assert "assistant" not in page.lower()  # en coulisse : rien à l'écran
    assert AiCall.objects.get().feature == "reglage_modele"


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


def test_assistant_finds_what_the_rules_left_in_a_filled_document(client, make_user, settings,
                                                                  monkeypatch):  # fmt: skip
    from django.core.files.uploadedfile import SimpleUploadedFile

    from apps.core.models import CabinetSettings
    from apps.core.testing.factories import ClientFactory
    from apps.documents import from_example
    from apps.documents.models import LetterTemplate
    from apps.documents.tests.test_from_example import filled_pv

    ClientFactory(name="Menuiserie Fictive", legal_form="SRL")
    admin = make_user(is_staff=True, capabilities=["clients.edit"])
    client.force_login(admin)
    settings.MISTRAL_API_KEY = "fictive"
    current = CabinetSettings.current()
    current.ai_personal_data = True
    current.save()
    # La fiche ne connaît ni le gérant ni les associés : l'assistant les retrouve.
    fake_reply(monkeypatch, {"elements": [
        {"texte": "Paul Testeur", "repere": "[GÉRANT]"},
        {"texte": "Marie Essai", "repere": "[ASSOCIÉ]"},
        {"texte": "texte inventé absent", "repere": "[MONTANT]"},
        {"texte": "Namur", "repere": "[INCONNU]"},
    ]})  # fmt: skip
    upload = SimpleUploadedFile("pv.docx", filled_pv())
    client.post(reverse("lettre:models"), {"sorte": "pv_ag", "modele": upload})
    template = LetterTemplate.objects.get()
    text = from_example.text_of(bytes(template.content))
    assert "Paul Testeur" not in text and "Marie Essai" not in text
    assert template.origin["assistant"] >= 1  # le reste, les règles l'ont déjà trouvé
    assert AiCall.objects.filter(feature="modele_depuis_exemple").exists()


def test_the_assistant_sets_the_unknown_holes_at_upload(client, make_user, settings, monkeypatch):
    from django.core.files.uploadedfile import SimpleUploadedFile

    from apps.documents import letter
    from apps.documents.models import LetterTemplate
    from apps.documents.tests.test_from_example import placeholder_model

    admin = make_user(is_staff=True, capabilities=["clients.edit"])
    client.force_login(admin)
    settings.MISTRAL_API_KEY = "fictive"
    holes = letter.holes(placeholder_model(), "pv_ag")
    lieu = next(h.key for h in holes if "LIEU" in h.text)
    nom = next(h.key for h in holes if "DENOMINATION" in h.text)
    fake_reply(monkeypatch, {"trous": {
        lieu: {"code": "demander", "question": "Où se tient l'assemblée ?"},
        nom: {"code": "demander", "question": "ne doit pas changer"},  # déjà lu par l'outil
    }})  # fmt: skip
    upload = SimpleUploadedFile("pv.docx", placeholder_model())
    client.post(reverse("lettre:models"), {"sorte": "pv_ag", "modele": upload})
    template = LetterTemplate.objects.get()
    assert template.holes[lieu] == {"field": "demander", "label": "Où se tient l'assemblée ?",
                                    "source": "assistant"}  # fmt: skip
    assert template.holes[nom]["field"] == "client.denomination"
    assert template.origin["reglage_ia"] == 1


def test_no_assistant_setting_to_manage(client, make_user, settings):
    from apps.core.models import CabinetSettings

    client.force_login(make_user(is_staff=True))
    settings.MISTRAL_API_KEY = "fictive"
    page = client.get(reverse("core:cabinet_settings")).content.decode()
    assert "Assistant IA" not in page
    assert CabinetSettings.current().ai_personal_data  # actif d'office (D-127)
