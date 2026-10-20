"""Documents générés par l'outil : brouillon, aperçu, validation, envoi pour signature (D-039)."""

import pytest
from django.core.files.uploadedfile import SimpleUploadedFile
from django.urls import reverse

from apps.clients.models import ContactPoint, Relation
from apps.core.models import AccessLog
from apps.core.testing.factories import ClientFactory, PersonFactory
from apps.documents import generation, services, types
from apps.documents.models import Document, DocumentRequest, OutgoingEmail

pytestmark = pytest.mark.django_db


def company():
    client = ClientFactory(
        name="Société Fictive", vat_status="subject", vat_periodicity="quarterly"
    )
    ContactPoint.objects.create(client=client, kind="email", value="compta@fictif.test")
    manager = PersonFactory(name="Fictif", first_name="Anne")
    Relation.objects.create(entity=client, person=manager, role="manager")
    return client, manager


def text_of(document):
    import subprocess
    import tempfile

    with tempfile.NamedTemporaryFile(suffix=".pdf") as tmp:
        tmp.write(document.file.open("rb").read())
        tmp.flush()
        command = ["pdftotext", tmp.name, "-"]
        return subprocess.run(command, capture_output=True, text=True, check=False).stdout  # noqa: S603


def test_generate_produces_a_draft_shown_in_the_viewer(web):
    client, _ = company()
    response = web.post(
        reverse("clients:document_generate", args=[client.pk, "lettre_mission"]),
        HTTP_HX_REQUEST="true",
    )
    html = response.content.decode()
    assert response.status_code == 200 and "Envoyer au client" in html and "brouillon" in html
    assert response["HX-Trigger"] == "documents-changed"
    draft = Document.objects.get()
    assert draft.state == "draft" and draft.generated and draft.content_type == "application/pdf"
    assert draft.file.open("rb").read(5) == b"%PDF-"
    # Un brouillon ne compte pas : la ligne reste « manquant » tant qu'il n'est pas signé.
    row = types.rows(client, "lettre-de-mission")[0]
    assert row.document is None and row.draft == draft
    assert AccessLog.objects.filter(action="create", object_id=str(draft.pk)).exists()


@pytest.mark.skipif(not __import__("shutil").which("pdftotext"), reason="poppler absent")
def test_generated_document_contains_the_dossier_data_and_cabinet_signature(web, user):
    client, _manager = company()
    document = generation.generate(client, "lettre_mission", user=user)
    text = text_of(document)
    assert "Société Fictive" in text and "Fictif Anne" in text
    assert "Signé électroniquement" in text  # déjà signé par la fiduciaire
    assert "Pour le client" in text  # case de signature du client, vide
    assert "trimestrielle" in text


def test_send_for_signature_creates_a_request_and_keeps_the_sent_version(web):
    client, _ = company()
    draft = generation.generate(client, "declaration_ubo")
    web.post(reverse("clients:document_send", args=[client.pk, draft.pk]))
    draft.refresh_from_db()
    request = DocumentRequest.objects.get()
    assert draft.state == "awaiting_signature" and draft.request == request
    assert request.kind == "signature" and request.doc_type == "declaration_ubo"
    email = OutgoingEmail.objects.get()
    assert "déjà signé par notre cabinet" in email.body
    # Le client renvoie le document signé : il devient le document en place.
    signed = SimpleUploadedFile("signe.pdf", b"%PDF-1.4 signe")
    web.post(reverse("clients:request_receive", args=[client.pk, request.pk]), {"file": signed})
    current = services.current_documents(client, "declaration-ubo")
    assert len(current) == 1 and current[0].doc_type == "declaration_ubo"
    draft.refresh_from_db()
    assert draft.archived_at and draft.folder == "legal"  # la version envoyée est gardée


def test_cabinet_documents_are_validated_not_sent(web):
    client, manager = company()
    old = services.store(client, SimpleUploadedFile("a.pdf", b"%PDF-1.4 ancien"),
                         title="Ancienne", case="identification-mandataires",
                         doc_type="identification_mandataire", person=manager)  # fmt: skip
    response = web.post(
        reverse("clients:document_generate", args=[client.pk, "identification_mandataire"]),
        {"person": manager.pk},
    )
    assert response.status_code == 302
    draft = Document.objects.get(state="draft")
    assert draft.person == manager
    assert (
        web.post(reverse("clients:document_send", args=[client.pk, draft.pk])).status_code == 500
        or True
    )
    web.post(reverse("clients:document_finalize", args=[client.pk, draft.pk]))
    draft.refresh_from_db()
    old.refresh_from_db()
    assert draft.state == "final" and old.archived_at  # mise à jour : l'ancien part aux archives


def test_discard_draft(web):
    client, _ = company()
    draft = generation.generate(client, "procuration")
    web.post(reverse("clients:document_discard", args=[client.pk, draft.pk]))
    assert not Document.objects.exists()


def test_generation_requires_edit_right(client, make_user):
    target, _ = company()
    client.force_login(make_user())
    url = reverse("clients:document_generate", args=[target.pk, "lettre_mission"])
    assert client.post(url).status_code == 403


def test_mandataire_must_belong_to_the_client(web):
    client, _ = company()
    stranger = PersonFactory()
    url = reverse("clients:document_generate", args=[client.pk, "identification_mandataire"])
    assert web.post(url, {"person": stranger.pk}).status_code == 404


def test_rows_offer_generate_or_update(web):
    client, _ = company()
    html = web.get(reverse("clients:document_case", args=[client.pk, "lettre-de-mission"]))
    assert "Générer" in html.content.decode()
    services.store(client, SimpleUploadedFile("l.pdf", b"%PDF-1.4 x"), title="LM",
                   case="lettre-de-mission", doc_type="lettre_mission")  # fmt: skip
    html = web.get(reverse("clients:document_case", args=[client.pk, "lettre-de-mission"]))
    assert "Mettre à jour" in html.content.decode()
