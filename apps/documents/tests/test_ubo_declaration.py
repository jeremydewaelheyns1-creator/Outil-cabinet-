"""Déclaration des bénéficiaires effectifs sur le modèle ITAA 4.2 / 4.3 (D-071)."""

import pytest

from apps.clients.models import Relation
from apps.core.testing.factories import ClientFactory, PersonFactory
from apps.documents import generation, risk, signing
from apps.documents.models import Signature

from .test_client_link import link_of, signature_png
from .test_documents import company_with_manager
from .test_generation import text_of

pytestmark = pytest.mark.django_db


def owned_company():
    """Société fictive : 60 % via une holding détenue à 100 % par Marc, 40 % par Sophie."""
    company, _ = company_with_manager()
    holding = ClientFactory(name="Holding Fictive", kind="company")
    marc = PersonFactory(name="Dubois", first_name="Marc")
    sophie = PersonFactory(name="Lambert", first_name="Sophie")
    Relation.objects.create(entity=company, person=holding, role="shareholder", share_percentage=60)
    Relation.objects.create(entity=holding, person=marc, role="shareholder", share_percentage=100)
    Relation.objects.create(entity=company, person=sophie, role="shareholder", share_percentage=40)
    return company, marc, sophie


def test_declaration_follows_the_itaa_model():
    company, marc, sophie = owned_company()
    document = generation.generate(company, "declaration_ubo")
    text = " ".join(text_of(document).split())
    for part in ("A. Entités exemptées", "B. Identification des bénéficiaires effectifs",
                 "C. Personnes politiquement exposées", "1:33 à 1:36", "plus de 25 %",
                 "dix ans", "indirectement, via Holding Fictive", "Pour le client"):  # fmt: skip
        assert part in text, part
    assert "Pour Cabinet" not in text  # signée par le client seul (modèle ITAA)
    assert {q["person"] for q in document.questions} == {marc.pk, sophie.pk}


def sent():
    company, marc, sophie = owned_company()
    draft = generation.generate(company, "declaration_ubo")
    request = generation.send_for_signature(draft)
    return company, marc, sophie, "/" + link_of(request)


def test_client_answers_pep_and_birth_place_when_signing(client):
    company, marc, sophie, path = sent()
    page = client.get(path).content.decode()
    assert marc.display_name in page and f'name="pep-{marc.pk}"' in page
    base = {"signer_name": "Anne Fictif", "signature": signature_png(), "approve": "1"}
    missing = client.post(path, base).content.decode()
    assert "Répondez aux questions" in missing and not Signature.objects.exists()
    answers = {f"lieu-{marc.pk}": "Namur", f"pep-{marc.pk}": "non",
               f"lieu-{sophie.pk}": "Liège", f"pep-{sophie.pk}": "oui"}  # fmt: skip
    client.post(path, {**base, **answers})
    proof = Signature.objects.get()
    assert proof.answers[str(sophie.pk)] == {
        "name": sophie.display_name,
        "pep": True,
        "lieu": "Liège",
    }
    certificate = " ".join(text_of(proof.document).split())
    assert "Réponses du signataire" in certificate and "Liège" in certificate
    assert signing.latest_answers(company) == proof
    pep = next(p for p in risk.propose(company) if p.question.key == "pep")
    assert pep.answer == "high" and sophie.display_name in pep.reason


def test_answers_are_shown_on_the_ubo_page(client, web):
    company, marc, sophie, path = sent()
    answers = {f"lieu-{marc.pk}": "Namur", f"pep-{marc.pk}": "non",
               f"lieu-{sophie.pk}": "Liège", f"pep-{sophie.pk}": "non"}  # fmt: skip
    client.post(path, {"signer_name": "Anne Fictif", "signature": signature_png(),
                       "approve": "1", **answers})  # fmt: skip
    from django.urls import reverse

    page = web.get(reverse("clients:ubo", args=[company.pk])).content.decode()
    assert "Réponses du client" in page and "Namur" in page
    pep = next(p for p in risk.propose(company) if p.question.key == "pep")
    assert pep.answer == "low"
