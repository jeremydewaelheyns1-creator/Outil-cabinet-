"""Fiche de risque guidée : propositions, calcul, révision, validation AMLCO (D-049)."""

from datetime import date, timedelta

import pytest
from django.urls import reverse
from django.utils import timezone

from apps.core.models import AccessLog
from apps.core.testing.factories import ClientFactory
from apps.documents import risk, types
from apps.documents.models import Document, RiskAssessment

pytestmark = pytest.mark.django_db

ALL_NO = {q.key: "non" for q in risk.QUESTIONS}


def proposals(client):
    return {p.question.key: p for p in risk.propose(client)}


def test_tool_prefills_what_it_knows_and_says_why():
    restaurant = ClientFactory(
        nace_codes=[{"code": "56.101", "label": "Restauration à service complet"}],
        client_since=timezone.localdate() - timedelta(days=30),
        country="BE",
    )
    found = proposals(restaurant)
    assert found["sensitive_sector"].answer is True
    assert "56101" in found["sensitive_sector"].reason
    assert found["new_client"].answer is True
    assert found["foreign"].answer is False
    assert found["pep"].answer is None  # l'outil ne devine pas : à répondre
    office = ClientFactory(nace_codes=[{"code": "69.202"}], client_since=date(2015, 1, 1))
    assert proposals(office)["sensitive_sector"].answer is False
    assert proposals(office)["new_client"].answer is False


def test_high_risk_country_is_proposed():
    found = proposals(ClientFactory(country="IR"))
    assert found["high_risk_country"].answer is True and found["foreign"].answer is True


def test_score_and_levels():
    assert risk.evaluate({}) == (0, "low")
    # Modèle ITAA 5.2 : un facteur dans un critère le met en « standard ».
    assert risk.evaluate({"new_client": True}) == (1, "medium")
    assert risk.evaluate({"sensitive_sector": True, "new_client": True}) == (3, "medium")
    assert risk.evaluate({"sensitive_sector": True, "cash": True, "foreign": True})[1] == "high"
    # Un seul facteur décisif suffit : risque élevé.
    assert risk.evaluate({"pep": True}) == (3, "high")


def test_criteria_follow_the_itaa_summary_form():
    found = {c.key: c for c in risk.criteria({"cash": True, "high_risk_country": True})}
    assert [c.label for c in found.values()] == [
        "Client", "Activité / secteur", "Géographique", "Nature de la mission",
    ]  # fmt: skip
    assert found["activite"].level == "medium" and "espèces" in found["activite"].motivation
    assert found["geographie"].level == "high" and found["client"].level == "low"
    assert found["mission"].motivation == "Aucun facteur relevé."


def test_review_dates_follow_the_level(settings):
    assert risk.next_review("low", date(2026, 3, 1)) == date(2029, 3, 1)  # 3 ans
    assert risk.next_review("medium", date(2026, 3, 1)) == date(2029, 3, 1)
    assert risk.next_review("high", date(2028, 2, 29)) == date(2029, 2, 28)


def test_filling_the_sheet_stores_the_pdf_with_its_expiry(web, user):
    client = ClientFactory(nace_codes=[{"code": "41.201"}])
    page = web.get(reverse("clients:risk_sheet", args=[client.pk]))
    assert page.status_code == 200 and "secteur" in page.content.decode()
    answers = {**ALL_NO, "sensitive_sector": "oui", "cash": "oui"}
    response = web.post(reverse("clients:risk_sheet", args=[client.pk]), answers)
    assert response.status_code == 302
    assessment = RiskAssessment.objects.get()
    assert assessment.level == "medium" and assessment.score == 4
    assert assessment.next_review.year == timezone.localdate().year + 3
    document = Document.objects.get(doc_type="fiche_risque")
    assert document.expires_on == assessment.next_review and document.case == "fiche-risque"
    assert document.file.open("rb").read(5) == b"%PDF-"
    row = types.rows(client, "fiche-risque")[0]
    assert row.level == "ok"
    assert AccessLog.objects.filter(action="create", details__has_key="fiche de risque").exists()
    # La fiche suivante reprend les réponses manuelles précédentes.
    assert proposals(client)["cash"].answer is True


def test_unanswered_questions_are_refused(web):
    client = ClientFactory()
    response = web.post(reverse("clients:risk_sheet", args=[client.pk]), {"pep": "non"})
    assert response.status_code == 200 and not RiskAssessment.objects.exists()


def test_high_risk_waits_for_the_amlco(web, make_user, client):
    target = ClientFactory()
    web.post(reverse("clients:risk_sheet", args=[target.pk]), {**ALL_NO, "pep": "oui"})
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
    response = client.post(reverse("clients:risk_sheet", args=[target.pk]), ALL_NO)
    assert response.status_code == 404 and not RiskAssessment.objects.exists()
