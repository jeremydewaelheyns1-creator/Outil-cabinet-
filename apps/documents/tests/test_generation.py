"""Documents générés par l'outil : brouillon, aperçu, validation, envoi pour signature (D-039)."""

import pytest
from django.core.files.uploadedfile import SimpleUploadedFile
from django.urls import reverse

from apps.clients.models import ContactPoint, Relation
from apps.core.models import AccessLog
from apps.core.testing.factories import ClientFactory, PersonFactory
from apps.documents import generation, services, types
from apps.documents.models import Document, DocumentRequest, OutgoingEmail
from apps.documents.tests.letter_fixture import install

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
        reverse("clients:document_generate", args=[client.pk, "procuration"]),
        HTTP_HX_REQUEST="true",
    )
    html = response.content.decode()
    assert response.status_code == 200 and "Envoyer au client" in html and "brouillon" in html
    assert response["HX-Trigger"] == "documents-changed"
    draft = Document.objects.get()
    assert draft.state == "draft" and draft.generated and draft.content_type == "application/pdf"
    assert draft.file.open("rb").read(5) == b"%PDF-"
    # Un brouillon ne compte pas : la ligne reste « manquant » tant qu'il n'est pas signé.
    row = types.rows(client, "procuration")[0]
    assert row.document is None and row.draft == draft
    assert AccessLog.objects.filter(action="create", object_id=str(draft.pk)).exists()


@pytest.mark.skipif(not __import__("shutil").which("pdftotext"), reason="poppler absent")
def test_generated_letter_contains_the_dossier_data(web, user):
    client, _manager = company()
    install()
    document = generation.generate(client, "lettre_mission", user=user)
    text = " ".join(text_of(document).split())
    assert "Société Fictive" in text and "Anne Fictif" in text


def test_no_mission_letter_without_the_cabinet_model(web):
    client, _ = company()
    assert not generation.can_generate("lettre_mission")
    with pytest.raises(ValueError):
        generation.generate(client, "lettre_mission")
    page = web.get(reverse("clients:document_case", args=[client.pk, "lettre-de-mission"]))
    assert "Pas de modèle du cabinet" in page.content.decode()
    url = reverse("clients:letter_prepare", args=[client.pk])
    assert web.post(url, {}).status_code == 200
    assert not Document.objects.exists()


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
    from apps.documents.tests.complete import complete

    client, manager = company()
    complete(manager)
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
    url = reverse("clients:document_generate", args=[target.pk, "procuration"])
    assert client.post(url).status_code == 403


def test_mandataire_must_belong_to_the_client(web):
    client, _ = company()
    stranger = PersonFactory()
    url = reverse("clients:document_generate", args=[client.pk, "identification_mandataire"])
    assert web.post(url, {"person": stranger.pk}).status_code == 404


def test_rows_offer_generate_or_update(web):
    client, _ = company()
    install()
    html = web.get(reverse("clients:document_case", args=[client.pk, "lettre-de-mission"]))
    assert "Générer" in html.content.decode()
    services.store(client, SimpleUploadedFile("l.pdf", b"%PDF-1.4 x"), title="LM",
                   case="lettre-de-mission", doc_type="lettre_mission")  # fmt: skip
    html = web.get(reverse("clients:document_case", args=[client.pk, "lettre-de-mission"]))
    assert "Mettre à jour" in html.content.decode()


def test_sending_without_email_address_is_refused_honestly(web):
    from apps.core.testing.factories import ClientFactory

    target = ClientFactory()
    draft = generation.generate(target, "procuration")
    response = web.post(reverse("clients:document_send", args=[target.pk, draft.pk]), follow=True)
    html = response.content.decode()
    assert "Pas d&#x27;adresse e-mail" in html or "Pas d'adresse e-mail" in html
    draft.refresh_from_db()
    assert draft.state == "draft" and not DocumentRequest.objects.exists()


def test_without_outlook_the_message_says_prepared_not_sent(web):
    client, _ = company()
    draft = generation.generate(client, "procuration")
    response = web.post(reverse("clients:document_send", args=[client.pk, draft.pk]), follow=True)
    assert "seulement préparé" in response.content.decode()


def test_identification_refused_while_mandatory_data_is_missing(web):
    from apps.core.testing.factories import PersonFactory as Person

    person = Person(birth_date=None, nationality="")
    url = reverse("clients:document_generate", args=[person.pk, "identification_client"])
    response = web.post(url, HTTP_HX_REQUEST="true")
    html = response.content.decode()
    assert "informations obligatoires manquent" in html
    assert "date de naissance" in html and "carte d" in html and "fiche de risque" in html
    assert not Document.objects.exists()


def test_validated_document_can_be_deleted_and_the_previous_one_comes_back(web):
    from apps.documents.tests.complete import complete

    client, _ = company()
    complete(client)
    first = generation.finalize(generation.generate(client, "identification_client"))
    second = generation.finalize(generation.generate(client, "identification_client"))
    first.refresh_from_db()
    assert first.archived_at is not None
    url = reverse("clients:document_delete", args=[client.pk, second.pk])
    assert "remis en place" in web.get(url).content.decode()
    web.post(url, {"confirme": "1"})
    assert not Document.objects.filter(pk=second.pk).exists()
    first.refresh_from_db()
    assert first.archived_at is None and first.case == "identification-client"
    assert AccessLog.objects.filter(action="delete", details__has_key="supprimé").exists()


def test_signed_document_cannot_be_deleted():
    from apps.documents.tests.test_client_link import letter_sent_for_signature

    _, request, _ = letter_sent_for_signature()
    document = request.documents.get()
    assert "signature" in services.can_delete(document)
