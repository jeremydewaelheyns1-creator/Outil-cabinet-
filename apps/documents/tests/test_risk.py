"""Fiche de risque sur les modèles ITAA 5.1 et 5.2 : propositions, synthèse, révision,
validation AMLCO (D-049, D-087)."""

from datetime import date, timedelta

import pytest
from django.urls import reverse
from django.utils import timezone

from apps.core.models import AccessLog
from apps.core.testing.factories import ClientFactory
from apps.documents import risk, types
from apps.documents.models import Document, RiskAssessment

pytestmark = pytest.mark.django_db

ALL_LOW = {q.key: "low" for q in risk.QUESTIONS} | {"synthese": "low"}


def proposals(client):
    return {p.question.key: p for p in risk.propose(client)}


def grid(**levels):
    return {q.key: {"level": levels.get(q.key, "low")} for q in risk.QUESTIONS}


def test_grid_follows_the_official_model_5_1():
    assert len(risk.BLOCKS) == 9 and len(risk.QUESTIONS) == 41
    assert risk.BLOCKS[0][1] == "Nature de la mission (annexe I de la LAB)"
    assert {q.block for q in risk.QUESTIONS} == {key for key, _ in risk.BLOCKS}
    # Chaque bloc nourrit exactement un critère du résumé 5.2.
    fed = [b for _, _, blocks in risk.CRITERIA for b in blocks]
    assert sorted(fed) == sorted(key for key, _ in risk.BLOCKS)


def test_tool_prefills_what_it_knows_and_says_why():
    restaurant = ClientFactory(
        nace_codes=[{"code": "56.101", "label": "Restauration à service complet"}],
        client_since=timezone.localdate() - timedelta(days=30),
        country="BE",
    )
    found = proposals(restaurant)
    assert found["secteurs_risque"].answer == "medium"
    assert "56101" in found["secteurs_risque"].reason
    assert found["mission_duree"].answer == "medium"  # nouvelle relation
    assert found["zone_euro"].answer == "low" and found["pays_lbc"].answer == "low"
    assert found["v_jeux"].answer == "low"  # varia d'après la BCE
    assert found["pep"].answer is None  # l'outil ne devine pas : à évaluer
    assert found["presse"].answer is None
    office = ClientFactory(nace_codes=[{"code": "69.202"}], client_since=date(2015, 1, 1))
    assert proposals(office)["secteurs_risque"].answer == "low"
    assert proposals(office)["mission_duree"].answer == "low"
    assert proposals(ClientFactory(nace_codes=[{"code": "68.311"}]))["v_immobilier"].answer == (
        "medium"
    )


def test_high_risk_country_is_proposed():
    found = proposals(ClientFactory(country="IR"))
    assert found["paradis_fiscal"].answer == "high" and found["zone_euro"].answer == "medium"
    assert found["pays_lbc"].answer == "high"


def test_synthesis_is_the_highest_level_and_decisive_factors_cannot_be_lowered():
    assert risk.evaluate(grid()) == (0, "low")
    assert risk.evaluate(grid(especes="medium", secteurs_risque="medium")) == (2, "medium")
    assert risk.evaluate(grid(presse="high"))[1] == "high"
    # Abaisser la synthèse : possible en motivant…
    answers = grid(presse="high")
    assert risk.check(answers, "medium", "")
    assert risk.check(answers, "medium", "Article ancien, sans suite (exemple fictif).") == []
    # … mais jamais sous un critère décisif élevé.
    assert risk.check(grid(pep="high"), "medium", "Motivation")
    assert risk.check(grid(pep="high"), "high", "") == []
    missing = grid()
    del missing["presse"]
    assert "1 critère(s) sans niveau" in risk.check(missing, "low", "")[0]


def test_criteria_follow_the_itaa_summary_form():
    answers = grid(especes="medium", pays_lbc="high")
    answers["especes"]["comment"] = "Caisse enregistreuse (exemple fictif)"
    found = {c.key: c for c in risk.criteria(answers)}
    assert [c.label for c in found.values()] == [
        "Client", "Activité / secteur", "Géographique", "Nature de la mission",
    ]  # fmt: skip
    assert found["client"].level == "medium" and "espèces" in found["client"].motivation
    assert "Caisse enregistreuse" in found["client"].motivation
    assert found["geographie"].level == "high" and found["activite"].level == "low"
    assert found["mission"].motivation == "Aucun facteur relevé."


def test_old_yes_no_sheets_are_still_read():
    old = {"pep": True, "cash": False, "sensitive_sector": True}
    clean = risk.normalise(old)
    assert clean["pep"]["level"] == "high" and clean["especes"]["level"] == "low"
    assert clean["secteurs_risque"]["level"] == "medium"
    target = ClientFactory()
    assessment = RiskAssessment.objects.create(
        client=target, answers=old, score=3, level="high", next_review=date(2030, 1, 1)
    )
    assert risk.pep_of(assessment) is True
    assert proposals(target)["pep"].answer == "high"  # repris de l'ancienne fiche
    assert b"%PDF" in risk._pdf(assessment)[:8]


def test_review_dates_follow_the_level(settings):
    assert risk.next_review("low", date(2026, 3, 1)) == date(2029, 3, 1)  # 3 ans
    assert risk.next_review("medium", date(2026, 3, 1)) == date(2029, 3, 1)
    assert risk.next_review("high", date(2028, 2, 29)) == date(2029, 2, 28)


def test_filling_the_sheet_stores_the_pdf_with_its_expiry(web, user):
    client = ClientFactory(nace_codes=[{"code": "41.201"}])
    page = web.get(reverse("clients:risk_sheet", args=[client.pk]))
    html = page.content.decode()
    assert page.status_code == 200 and "Nature de la mission (annexe I de la LAB)" in html
    answers = {
        **ALL_LOW,
        "secteurs_risque": "medium",
        "especes": "medium",
        "especes-c": "Chantiers payés en liquide (exemple fictif)",
        "synthese": "medium",
    }
    response = web.post(reverse("clients:risk_sheet", args=[client.pk]), answers)
    assert response.status_code == 302
    assessment = RiskAssessment.objects.get()
    assert assessment.level == "medium" and assessment.score == 2
    assert assessment.answers["especes"]["comment"].startswith("Chantiers")
    assert assessment.next_review.year == timezone.localdate().year + 3
    document = Document.objects.get(doc_type="fiche_risque")
    assert document.expires_on == assessment.next_review and document.case == "fiche-risque"
    assert document.file.open("rb").read(5) == b"%PDF-"
    row = types.rows(client, "fiche-risque")[0]
    assert row.level == "ok"
    assert AccessLog.objects.filter(action="create", details__has_key="fiche de risque").exists()
    from .test_generation import text_of

    text = " ".join(text_of(document).split())
    assert "5.1 Formulaire d'évaluation du niveau de risque du client" in text
    assert "5.2 Formulaire de synthèse" in text and "Chantiers payés en liquide" in text
    # La fiche suivante reprend les réponses et commentaires précédents.
    again = proposals(client)
    assert again["presse"].answer == "low" and "Repris de la fiche" in again["presse"].reason
    assert again["especes"].comment.startswith("Chantiers")


def test_unanswered_criteria_are_refused_and_can_be_set_to_low(web):
    client = ClientFactory()
    url = reverse("clients:risk_sheet", args=[client.pk])
    response = web.post(url, {"pep": "low", "synthese": "low"})
    assert response.status_code == 200 and not RiskAssessment.objects.exists()
    assert "sans niveau de risque" in response.content.decode()
    # « Mettre faible partout où c'est vide » : la grille revient remplie, rien n'est enregistré.
    html = web.post(url, {"pep": "high", "remplir": "1"}).content.decode()
    assert not RiskAssessment.objects.exists()
    assert 'name="presse" value="low" checked' in html and 'name="pep" value="high" checked' in html


def test_lowering_a_decisive_factor_is_refused(web):
    client = ClientFactory()
    url = reverse("clients:risk_sheet", args=[client.pk])
    web.post(url, {**ALL_LOW, "pep": "high", "synthese": "low", "commentaire": "Non"})
    assert not RiskAssessment.objects.exists()


def test_high_risk_waits_for_the_amlco(web, make_user, client):
    target = ClientFactory()
    web.post(
        reverse("clients:risk_sheet", args=[target.pk]),
        {**ALL_LOW, "pep": "high", "synthese": "high"},
    )
    assessment = RiskAssessment.objects.get()
    assert assessment.awaiting_approval and assessment.document.review_needed
    url = reverse("clients:risk_approve", args=[target.pk, assessment.pk])
    assert web.post(url).status_code == 403  # un collaborateur ne valide pas
    amlco = make_user(capabilities=["clients.edit", "aml.decide"])
    client.force_login(amlco)
    case = client.get(reverse("clients:document_case", args=[target.pk, "fiche-risque"]))
    assert "validation de l'AMLCO requise" in case.content.decode()
    assert client.post(url).status_code == 302
    assessment.refresh_from_db()
    assert not assessment.awaiting_approval and assessment.approved_by == amlco
    document = Document.objects.get(pk=assessment.document.pk)
    assert not document.review_needed
    # Le PDF est refait avec la validation de l'AMLCO (modèle ITAA 5.2).
    from .test_generation import text_of

    text = " ".join(text_of(document).split())
    assert "AMLCO" in text and "Fait le" in text and "Synthèse" in text


def test_reader_cannot_fill_the_sheet(client, make_user):
    target = ClientFactory()
    client.force_login(make_user(capabilities=[]))
    response = client.post(reverse("clients:risk_sheet", args=[target.pk]), ALL_LOW)
    assert response.status_code == 404 and not RiskAssessment.objects.exists()
