"""Boîte Outlook (D-044) : connexion, envoi, erreurs. Microsoft est simulé : aucun appel réel."""

import base64
import json
from urllib.parse import parse_qs, urlparse

import httpx
import pytest
from django.urls import reverse

from apps.core.models import AccessLog
from apps.outlook import graph
from apps.outlook.models import MailboxLink

pytestmark = pytest.mark.django_db


@pytest.fixture(autouse=True)
def outlook_settings(settings):
    settings.OUTLOOK_TENANT_ID = "tenant-fictif"
    settings.OUTLOOK_CLIENT_ID = "client-fictif"
    settings.OUTLOOK_CLIENT_SECRET = "secret-fictif"
    settings.MAILBOX_TOKEN_KEY = ""


class FakeMicrosoft:
    """Faux Microsoft : jetons, profil, envoi. Garde les requêtes reçues."""

    def __init__(self, *, scope="offline_access User.Read Mail.Send", refresh_ok=True,
                 send_status=202):  # fmt: skip
        self.scope, self.refresh_ok, self.send_status = scope, refresh_ok, send_status
        self.sent: list[dict] = []
        self.token_requests: list[dict] = []

    def handler(self, request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/oauth2/v2.0/token"):
            form = {k: v[0] for k, v in parse_qs(request.content.decode()).items()}
            self.token_requests.append(form)
            if form["grant_type"] == "refresh_token" and not self.refresh_ok:
                return httpx.Response(400, json={"error": "invalid_grant"})
            refresh = f"renouv-{len(self.token_requests)}"
            return httpx.Response(
                200, json={"access_token": "acces", "scope": self.scope, "refresh_token": refresh}
            )
        if request.url.path.endswith("/me"):
            return httpx.Response(200, json={"mail": "jeremy@cabinet-fictif.test"})
        if request.url.path.endswith("/me/sendMail"):
            self.sent.append(json.loads(request.content))
            return httpx.Response(self.send_status)
        return httpx.Response(404)

    def client(self) -> httpx.Client:
        return httpx.Client(transport=httpx.MockTransport(self.handler))


def test_connect_flow_keeps_only_an_encrypted_token(web, user, monkeypatch):
    fake = FakeMicrosoft()
    monkeypatch.setattr(graph, "_http", fake.client)
    response = web.post(reverse("outlook:connect"))
    url = urlparse(response["Location"])
    params = parse_qs(url.query)
    assert url.netloc == "login.microsoftonline.com" and "tenant-fictif" in url.path
    assert params["scope"] == [graph.SCOPES] and "Mail.Read" not in graph.SCOPES
    assert params["code_challenge_method"] == ["S256"]
    state = params["state"][0]
    web.get(reverse("outlook:callback"), {"state": state, "code": "code-fictif"})
    link = MailboxLink.objects.get(user=user)
    assert link.address == "jeremy@cabinet-fictif.test"
    assert "renouv" not in link.token  # chiffré en base
    assert graph.decrypt(link.token) == "renouv-1"
    assert fake.token_requests[0]["code_verifier"]  # PKCE
    assert AccessLog.objects.filter(object_type="boîte Outlook reliée").exists()


def test_callback_with_a_wrong_state_is_refused(web, user, monkeypatch):
    fake = FakeMicrosoft()
    monkeypatch.setattr(graph, "_http", fake.client)
    web.post(reverse("outlook:connect"))
    web.get(reverse("outlook:callback"), {"state": "pirate", "code": "code-fictif"})
    assert not MailboxLink.objects.exists() and not fake.token_requests


def test_send_permission_is_required(web, user, monkeypatch):
    fake = FakeMicrosoft(scope="offline_access User.Read")
    monkeypatch.setattr(graph, "_http", fake.client)
    response = web.post(reverse("outlook:connect"))
    state = parse_qs(urlparse(response["Location"]).query)["state"][0]
    web.get(reverse("outlook:callback"), {"state": state, "code": "x"})
    assert not MailboxLink.objects.exists()


def link_for(user) -> MailboxLink:
    return MailboxLink.objects.create(user=user, address="jeremy@cabinet-fictif.test",
                                      token=graph.encrypt("renouv-0"))  # fmt: skip


def test_send_goes_through_the_employee_mailbox(user):
    fake = FakeMicrosoft()
    link = link_for(user)
    pdf = graph.Attachment("d.pdf", b"%PDF-1.4")
    graph.send(link, to="client@fictif.test", subject="TVA", body="Bonjour", attachments=[pdf],
               http=fake.client())  # fmt: skip
    [payload] = fake.sent
    assert payload["saveToSentItems"] is True
    message = payload["message"]
    assert message["toRecipients"] == [{"emailAddress": {"address": "client@fictif.test"}}]
    assert base64.b64decode(message["attachments"][0]["contentBytes"]) == b"%PDF-1.4"
    link.refresh_from_db()
    assert graph.decrypt(link.token) == "renouv-1"  # jeton renouvelé et gardé
    assert link.last_used_at is not None


def test_revoked_access_marks_the_mailbox_to_relink(user):
    link = link_for(user)
    with pytest.raises(graph.MailboxError, match="reliée à nouveau"):
        graph.send(link, to="c@fictif.test", subject="x", body="y",
                   http=FakeMicrosoft(refresh_ok=False).client())  # fmt: skip
    link.refresh_from_db()
    assert not link.usable and graph.mailbox_for(user) is None


def test_refused_send_raises(user):
    with pytest.raises(graph.MailboxError, match="pas parti"):
        graph.send(link_for(user), to="c@fictif.test", subject="x", body="y",
                   http=FakeMicrosoft(send_status=403).client())  # fmt: skip


def test_too_large_attachment_is_refused_before_calling_microsoft(user):
    fake = FakeMicrosoft()
    big = graph.Attachment("gros.pdf", b"0" * (graph.MAX_ATTACHMENTS_BYTES + 1))
    with pytest.raises(graph.MailboxError, match="trop lourde"):
        graph.send(link_for(user), to="c@fictif.test", subject="x", body="y",
                   attachments=[big], http=fake.client())  # fmt: skip
    assert not fake.token_requests


def test_disconnect(web, user):
    link_for(user)
    web.post(reverse("outlook:disconnect"))
    assert not MailboxLink.objects.exists()


def test_mailbox_page_without_configuration(web, settings):
    settings.OUTLOOK_CLIENT_SECRET = ""
    html = web.get(reverse("outlook:mailbox")).content.decode()
    assert "pas encore configurée" in html


def test_vat_email_leaves_from_the_outlook_mailbox(web, user, monkeypatch):
    from apps.vat.tests.test_vat import _filed

    fake = FakeMicrosoft()
    monkeypatch.setattr(graph, "_http", fake.client)
    link_for(user)
    company, filing = _filed(user)
    url = reverse("clients:vat_mail", args=[company.pk, filing.pk])
    html = web.get(url, HTTP_HX_REQUEST="true").content.decode()
    assert "jeremy@cabinet-fictif.test" in html
    web.post(url, {"action": "send", "to": "compta@fictif.test", "subject": "TVA",
                   "body": "Bonjour", "attach_pdf": "1"}, HTTP_HX_REQUEST="true")  # fmt: skip
    message = filing.messages.get()
    assert message.delivered and message.sent_from == "jeremy@cabinet-fictif.test"
    assert len(fake.sent) == 1 and fake.sent[0]["message"]["attachments"]


def test_vat_email_is_not_marked_sent_when_microsoft_refuses(web, user, monkeypatch):
    from apps.vat.tests.test_vat import _filed

    monkeypatch.setattr(graph, "_http", FakeMicrosoft(send_status=500).client)
    link_for(user)
    company, filing = _filed(user)
    url = reverse("clients:vat_mail", args=[company.pk, filing.pk])
    html = web.post(url, {"action": "send", "to": "compta@fictif.test", "subject": "x",
                          "body": "y"}, HTTP_HX_REQUEST="true").content.decode()  # fmt: skip
    assert "pas parti" in html
    assert filing.messages.get().sent_at is None
    assert filing.cells.filter(column="client", status="done").count() == 0


# --- Demandes de documents envoyées depuis Outlook, copies archivées (D-045) -------------------


def test_identity_request_leaves_from_outlook_and_is_archived(web, user, monkeypatch):
    from apps.clients.models import Client
    from apps.documents.models import Document, DocumentRequest
    from apps.documents.tests.test_documents import company_with_manager

    fake = FakeMicrosoft()
    monkeypatch.setattr(graph, "_http", fake.client)
    link_for(user)
    company, manager = company_with_manager()
    Client.objects.filter(pk=company.pk).update(contact_title="Madame", contact_name="Fictive")
    web.post(reverse("clients:request_create", args=[company.pk]),
             {"kind": "identity_card", "person": manager.pk})  # fmt: skip
    request = DocumentRequest.objects.get()
    email = request.emails.get()
    assert email.delivered and email.sent_from == "jeremy@cabinet-fictif.test"
    sent = fake.sent[0]["message"]
    assert request.reference in sent["subject"]
    body = sent["body"]["content"]
    assert body.startswith("Bonjour Madame Fictive,") and "recto et du verso" in body
    archived = Document.objects.get(client=company, folder="courriels")
    assert archived.content_type == "application/pdf" and request.reference in archived.title


def test_request_without_linked_mailbox_stays_prepared(web, user):
    from apps.documents.models import Document, DocumentRequest
    from apps.documents.tests.test_documents import company_with_manager

    company, manager = company_with_manager()
    response = web.post(reverse("clients:request_create", args=[company.pk]),
                        {"kind": "identity_card", "person": manager.pk}, follow=True)  # fmt: skip
    assert "pas envoyée" in response.content.decode()
    assert not DocumentRequest.objects.get().emails.get().delivered
    assert not Document.objects.filter(folder="courriels").exists()


def test_automatic_reminder_leaves_from_the_dossier_manager(user, monkeypatch):
    from datetime import timedelta

    from django.utils import timezone

    from apps.clients.models import Assignment
    from apps.documents import services
    from apps.documents.tests.test_documents import company_with_manager

    fake = FakeMicrosoft()
    monkeypatch.setattr(graph, "_http", fake.client)
    company, manager = company_with_manager()
    request = services.create_request(company, "identity_card", person=manager)  # automatique
    assert not request.emails.get().delivered  # personne de l'équipe n'a de boîte reliée
    Assignment.objects.create(client=company, user=user, role="manager")
    link_for(user)
    services.send_due_reminders(timezone.localdate() + timedelta(days=7))
    reminder = request.emails.get(kind="reminder")
    assert reminder.delivered and reminder.subject.startswith("Rappel")


def test_vat_email_copy_is_archived(web, user, monkeypatch):
    from apps.documents.models import Document
    from apps.vat.tests.test_vat import _filed

    monkeypatch.setattr(graph, "_http", FakeMicrosoft().client)
    link_for(user)
    company, filing = _filed(user)
    url = reverse("clients:vat_mail", args=[company.pk, filing.pk])
    web.post(url, {"action": "send", "to": "compta@fictif.test", "subject": "TVA T3",
                   "body": "Bonjour", "attach_pdf": "1"}, HTTP_HX_REQUEST="true")  # fmt: skip
    archived = Document.objects.get(client=company, folder="courriels")
    assert "TVA T3" in archived.title
