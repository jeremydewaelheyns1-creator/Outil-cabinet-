"""Lecture d'un modèle par l'assistant (D-132), réponse de l'IA simulée."""

from __future__ import annotations

import pytest
from django.core.files.uploadedfile import SimpleUploadedFile
from django.urls import reverse

from apps.ai import banc, model_reader
from apps.ai.tests.test_ai import fake_reply
from apps.documents import from_example, letter
from apps.documents.models import LetterTemplate

pytestmark = pytest.mark.django_db


def _case(name):
    return next(c for c in banc.cases() if c.name == name)


def test_blocks_show_one_line_per_table_row():
    lines = [line for _, line in model_reader.blocks(_case("PV rempli avec tableaux").content)]
    assert any("[tableau 2, ligne 5] : - ATN Auto |  | 1.000,00" in line for line in lines)
    assert not any("autre case" in line for line in lines)


def test_the_reading_is_applied_with_guards():
    case = _case("PV rempli avec tableaux")
    lines = dict(model_reader.blocks(case.content))
    row = next(i for i, line in lines.items() if "ATN Auto" in line)
    head = next(i for i, line in lines.items() if line.endswith("Agence Essai Immo SRL"))
    sign = next(i for i, line in lines.items() if line.endswith(": Administrateur"))
    data = {"elements": [
        {"bloc": f"P{head}", "texte": "Agence Essai Immo SRL", "code": "client.denomination"},
        {"bloc": f"P{row}", "texte": "1.000,00", "code": "demander", "intitule": "ATN Auto ?"},
        {"bloc": f"P{row}", "texte": "ATN Auto", "code": "demander", "intitule": "x"},  # libellé
        {"bloc": f"P{sign}", "texte": "Administrateur", "code": "ag.date"},  # pas une date
        {"bloc": "P999", "texte": "rien", "code": "demander"},
        {"bloc": f"P{head}", "texte": "absent", "code": "client.denomination"},
    ], "passages": [{"bloc": f"P{head}", "condition": "question"}]}  # fmt: skip
    reading = model_reader.apply(case.content, "pv_ag", data)
    text = from_example.text_of(reading.content)
    assert "[Société]" in text and "Agence Essai Immo" not in text
    assert "ATN Auto" in text and "Administrateur" in text
    assert reading.refused == 4 and reading.options == {}
    holes = model_reader.overlay(from_example.holes_for(reading.content, "pv_ag"),
                                 reading.content, "pv_ag", reading)  # fmt: skip
    asked = [v for v in holes.values() if v.get("source") == "assistant"]
    assert {"field": "demander", "label": "ATN Auto", "source": "assistant"} in asked


def test_a_name_found_once_is_replaced_everywhere():
    case = _case("AGE transfert de siège")
    lines = dict(model_reader.blocks(case.content))
    first = next(i for i, line in lines.items() if "présidence" in line)
    data = {"elements": [{"bloc": f"P{first}", "texte": "Sophie Essaisix",
                          "code": "client.representant"}]}  # fmt: skip
    reading = model_reader.apply(case.content, "pv_ag", data)
    assert "Sophie Essaisix" not in from_example.text_of(reading.content)


def test_upload_uses_the_reader_then_the_rules(client, make_user, settings, monkeypatch):
    client.force_login(make_user(is_staff=True, capabilities=["clients.edit"]))
    settings.MISTRAL_API_KEY = "fictive"
    case = _case("Lettre de mission en tableaux")
    lines = dict(model_reader.blocks(case.content))
    row = next(i for i, line in lines.items() if "Tenue de la comptabilité" in line)
    seen = []
    fake_reply(monkeypatch, {"elements": [
        {"bloc": f"P{row}", "texte": "3.600,00 €", "code": "demander",
         "intitule": "Honoraires tenue de la comptabilité"},
    ]}, seen)  # fmt: skip
    upload = SimpleUploadedFile("lettre.docx", case.content)
    client.post(reverse("lettre:models"), {"sorte": "lettre", "modele": upload})
    template = LetterTemplate.objects.get()
    assert template.origin["lu"] is True
    labels = [label for _, label in letter.questions(template)]
    assert "Honoraires tenue de la comptabilité" in labels
    assert "Garage" not in seen[0]["messages"][1]["content"]  # bien ce document
    assert "0654.321.097" not in seen[0]["messages"][1]["content"]  # numéros masqués
    page = client.get(reverse("lettre:model", args=[template.pk])).content.decode()
    assert 'class="hole-ask"' in page and "Ce que l'outil a compris" in page


def test_a_correction_becomes_an_example(client, make_user, settings, monkeypatch):
    from apps.core.models import CabinetSettings

    client.force_login(make_user(is_staff=True, capabilities=["clients.edit"]))
    settings.MISTRAL_API_KEY = "fictive"
    case = _case("Lettre de mission vide")
    lines = dict(model_reader.blocks(case.content))
    row = next(i for i, line in lines.items() if "Honoraires" in line)
    fake_reply(
        monkeypatch,
        {
            "elements": [
                {"bloc": f"P{row}", "texte": "……", "code": "demander", "intitule": "Montant"}
            ]
        },
    )
    upload = SimpleUploadedFile("lettre.docx", case.content)
    client.post(reverse("lettre:models"), {"sorte": "lettre", "modele": upload})
    template = LetterTemplate.objects.get()
    key = next(k for k, v in template.holes.items() if v.get("label") == "Montant")
    data = {"action": "enregistrer"}
    for k, v in template.holes.items():
        data[f"trou-{k}"], data[f"libelle-{k}"] = v["field"], v["label"]
    data[f"libelle-{key}"] = "Honoraires mensuels HTVA"
    client.post(reverse("lettre:model", args=[template.pk]), data)
    examples = CabinetSettings.current().ai_examples
    assert examples[-1]["intitule"] == "Honoraires mensuels HTVA"
    assert "⟨……⟩" in examples[-1]["contexte"]


def test_the_bench_runs_without_the_assistant():
    scores = banc.run(use_ai=False)
    assert sum(s.total for s in scores) > 100
    assert sum(s.ok for s in scores) / sum(s.total for s in scores) > 0.9
