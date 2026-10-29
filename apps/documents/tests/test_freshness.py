"""Documents devenus obsolètes et suivi automatique de ce qui expire (D-050)."""

from datetime import timedelta

import pytest
from django.core.files.uploadedfile import SimpleUploadedFile
from django.utils import timezone

from apps.clients.models import Assignment, ContactPoint, Relation
from apps.core.testing.factories import ClientFactory, PersonFactory
from apps.documents import freshness, generation, services, types
from apps.documents.models import Document
from apps.documents.tests.complete import complete
from apps.tasks.models import Task

pytestmark = pytest.mark.django_db


def company():
    client = ClientFactory(name="Société Fictive", street="Rue Fictive", city="Namur")
    ContactPoint.objects.create(client=client, kind="email", value="compta@fictif.test")
    Relation.objects.create(entity=client, person=PersonFactory(name="Fictif"), role="manager")
    return complete(client)


def finalized(client, doc_type="identification_client"):
    return generation.finalize(generation.generate(client, doc_type))


def row(client, case="identification-client"):
    return types.rows(client, case)[0]


def test_generated_document_keeps_a_fingerprint_without_personal_data():
    client = company()
    document = finalized(client)
    assert set(document.data_fingerprint) == {
        "identite",
        "adresse",
        "activite",
        "mandataires",
        "risque",
    }
    assert "Namur" not in str(document.data_fingerprint)
    assert row(client).level == "ok"


def test_changed_address_makes_the_document_out_of_date_and_creates_a_task(user):
    client = company()
    Assignment.objects.create(client=client, user=user, role=Assignment.Role.MANAGER)
    document = finalized(client)
    client.city = "Liège"
    client.save()
    current = row(client)
    assert current.level == "warning" and current.text.startswith("À mettre à jour : adresse")
    assert freshness.follow_up() == 1
    assert freshness.follow_up() == 0  # une seule tâche
    task = Task.objects.get(kind="document:maj-identification_client")
    assert task.assignee == user and task.period_key == document.pk.hex[:30]
    assert "adresse" in task.title and task.category == "aml"
    # Mise à jour du document : la tâche se ferme seule.
    finalized(client)
    task.refresh_from_db()
    assert task.status == "done"
    assert row(client).level == "ok"


def test_new_manager_makes_the_ubo_declaration_out_of_date():
    client = company()
    generation.finalize(generation.generate(client, "declaration_ubo"))
    Relation.objects.create(
        entity=client, person=PersonFactory(name="Nouveau"), role="shareholder",
        share_percentage=60,
    )  # fmt: skip
    assert "bénéficiaires effectifs" in row(client, "declaration-ubo").text


def test_documents_uploaded_by_hand_are_not_checked():
    client = company()
    services.store(client, SimpleUploadedFile("x.pdf", b"%PDF-1.4 fictif"), title="Fiche",
                   case="identification-client", doc_type="identification_client")  # fmt: skip
    client.city = "Liège"
    client.save()
    assert row(client).level == "ok"


def test_expiring_risk_sheet_becomes_a_task_closed_by_the_new_sheet():
    client = company()
    soon = timezone.localdate() + timedelta(days=20)
    services.store(client, SimpleUploadedFile("x.pdf", b"%PDF-1.4 fictif"), title="Fiche",
                   case="fiche-risque", doc_type="fiche_risque", expires_on=soon)  # fmt: skip
    far = timezone.localdate() + timedelta(days=400)
    other = company()
    services.store(other, SimpleUploadedFile("x.pdf", b"%PDF-1.4 fictif"), title="Fiche",
                   case="fiche-risque", doc_type="fiche_risque", expires_on=far)  # fmt: skip
    assert freshness.follow_up() == 1
    task = Task.objects.get()
    assert task.client == client and task.due_date == soon
    assert task.title == "Réviser la fiche de risque"
    services.store(client, SimpleUploadedFile("y.pdf", b"%PDF-1.4 fictif 2"), title="Fiche",
                   case="fiche-risque", doc_type="fiche_risque", expires_on=far)  # fmt: skip
    task.refresh_from_db()
    assert task.status == "done"
    assert Document.objects.filter(doc_type="fiche_risque", archived_at__isnull=True).count() == 2


def test_new_risk_level_makes_both_identifications_out_of_date():
    """D-103 : l'identification du mandataire ne suivait pas la fiche de risque."""
    from apps.documents.models import RiskAssessment

    client = company()  # fiche de risque « faible »
    manager = complete(types.mandataires(client)[0])
    generation.finalize(generation.generate(client, "identification_mandataire", person=manager))
    finalized(client)
    assert row(client).level == "ok"
    review = timezone.localdate() + timedelta(days=300)
    RiskAssessment.objects.create(client=client, answers={}, score=9, level="high",
                                  next_review=review)  # fmt: skip
    rows = types.rows(client, "identification-mandataires")
    assert rows[0].level == "warning" and "fiche de risque" in rows[0].text
    assert row(client).level == "warning" and "fiche de risque" in row(client).text


def test_mandataire_identification_needs_the_risk_sheet_first():
    from apps.documents.models import RiskAssessment

    client = company()
    RiskAssessment.objects.filter(client=client).delete()
    manager = types.mandataires(client)[0]
    missing = generation.missing_data(client, "identification_mandataire", manager)
    assert "niveau de risque (fiche de risque)" in missing
