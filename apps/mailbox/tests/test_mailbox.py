"""« Ma boîte mail » (D-060, D-061). Microsoft est simulé : aucun appel réel, données fictives."""

import base64
import json
import re
from datetime import time, timedelta
from html import unescape
from urllib.parse import parse_qs, urlparse

import httpx
import pytest
from django.urls import reverse
from django.utils import timezone

from apps.clients.models import ContactPoint, Relation
from apps.core.models import AccessLog, Notification
from apps.core.testing.factories import ClientFactory, PersonFactory, PortfolioFactory
from apps.mailbox import sync
from apps.mailbox.models import Awaiting, MailAttachment, MailExclusion, MailMessage
from apps.outlook import graph
from apps.outlook.models import MailboxLink
from apps.tasks import deadlines
from apps.tasks.models import Task

pytestmark = pytest.mark.django_db

PNG = base64.b64decode(
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mP8z8BQDwAEhQGAhKmMIQAAAABJRU5ErkJggg=="
)


@pytest.fixture(autouse=True)
def outlook_settings(settings):
    settings.OUTLOOK_TENANT_ID = "tenant-fictif"
    settings.OUTLOOK_CLIENT_ID = "client-fictif"
    settings.OUTLOOK_CLIENT_SECRET = "secret-fictif"
    settings.MAILBOX_TOKEN_KEY = ""


def mail(graph_id, *, sender="", name="", subject="Objet", body="Bonjour", to=None, when=None,
         attachments=False, conversation="conv-1"):  # fmt: skip
    return {
        "id": graph_id, "conversationId": conversation, "subject": subject,
        "from": {"emailAddress": {"address": sender, "name": name}},
        "toRecipients": [{"emailAddress": {"address": a}} for a in (to or [])],
        "receivedDateTime": when or timezone.now().strftime("%Y-%m-%dT%H:%M:%SZ"),
        "sentDateTime": when or timezone.now().strftime("%Y-%m-%dT%H:%M:%SZ"),
        "hasAttachments": attachments, "body": {"contentType": "text", "content": body},
    }  # fmt: skip


def file_attachment(name):
    return {"@odata.type": "#microsoft.graph.fileAttachment", "name": name,
            "contentBytes": base64.b64encode(PNG).decode(), "isInline": False}  # fmt: skip


class FakeGraph:
    def __init__(self):
        self.inbox: list[dict] = []
        self.sent: list[dict] = []
        self.attachments: dict[str, list[dict]] = {}
        self.replies: list[tuple[str, dict]] = []
        self.sent_mails: list[dict] = []
        self.prefer: list[str] = []

    def handler(self, request: httpx.Request) -> httpx.Response:
        path = request.url.path
        if path.endswith("/oauth2/v2.0/token"):
            form = {k: v[0] for k, v in parse_qs(request.content.decode()).items()}
            return httpx.Response(200, json={"access_token": "acces", "scope": form["scope"],
                                             "refresh_token": "renouv"})  # fmt: skip
        if path.endswith("/me"):
            return httpx.Response(200, json={"mail": "camille@cabinet-fictif.test"})
        if path.endswith("/mailFolders/inbox/messages"):
            self.prefer.append(request.headers.get("Prefer", ""))
            return httpx.Response(200, json={"value": self.inbox})
        if path.endswith("/mailFolders/sentitems/messages"):
            return httpx.Response(200, json={"value": self.sent})
        if path.endswith("/attachments"):
            graph_id = path.split("/")[-2]
            return httpx.Response(200, json={"value": self.attachments.get(graph_id, [])})
        if path.endswith("/reply"):
            self.replies.append((path.split("/")[-2], json.loads(request.content)))
            return httpx.Response(202)
        if path.endswith("/me/sendMail"):
            self.sent_mails.append(json.loads(request.content))
            return httpx.Response(202)
        return httpx.Response(404)

    def client(self):
        return httpx.Client(transport=httpx.MockTransport(self.handler))


@pytest.fixture
def fake(monkeypatch):
    fake = FakeGraph()
    monkeypatch.setattr(graph, "_http", fake.client)
    return fake


@pytest.fixture
def link(user):
    return MailboxLink.objects.create(
        user=user, address="camille@cabinet-fictif.test", token=graph.encrypt("renouv"),
        scopes=graph.READ_SCOPES, read_enabled=True,
        read_since=timezone.now() - timedelta(days=1),
    )  # fmt: skip


@pytest.fixture
def bakery():
    company = ClientFactory(name="Boulangerie Fictive", enterprise_number="0403170701")
    ContactPoint.objects.create(client=company, kind="email", value="compta@boulangerie.test")
    sophie = PersonFactory(name="Lambert", first_name="Sophie")
    ContactPoint.objects.create(client=sophie, kind="email", value="sophie.prive@exemple.test")
    Relation.objects.create(entity=company, person=sophie, role="manager")
    return company, sophie


def inbox_html(web, **params):
    """Texte de la page, sans les balises (pour chercher des phrases)."""
    html = unescape(web.get(reverse("boite:inbox"), params).content.decode())
    return re.sub(r"<[^>]+>", "", html)


# --- Activation ------------------------------------------------------------------------------


def test_reading_is_activated_by_the_employee_with_an_extra_right(web, user, fake):
    page = web.get(reverse("boite:inbox")).content.decode()
    assert "Activer avec Microsoft" in page and "Vous seul" in page
    response = web.post(reverse("outlook:connect"), {"lecture": "1"})
    params = parse_qs(urlparse(response["Location"]).query)
    assert "Mail.Read" in params["scope"][0]
    web.get(reverse("outlook:callback"), {"state": params["state"][0], "code": "code-fictif"})
    link = MailboxLink.objects.get(user=user)
    assert link.read_enabled and link.read_since and "Mail.Read" in link.scopes
    assert AccessLog.objects.filter(object_type="lecture de la boîte").exists()


# --- Relève et suggestions ---------------------------------------------------------------------


def test_sync_copies_new_mails_and_suggests_the_dossier(user, link, fake, bakery):
    company, sophie = bakery
    fake.inbox = [
        mail("m1", sender="compta@boulangerie.test", subject="Factures"),
        mail("m2", sender="sophie.prive@exemple.test", subject="Ma carte", attachments=True),
        mail("m3", sender="info@spf-fictif.test", subject="Demande de renseignements",
             body="Concerne l'entreprise 0403.170.701"),
        mail("m4", sender="inconnu@ailleurs.test"),
    ]  # fmt: skip
    fake.attachments["m2"] = [file_attachment("photo.png")]
    assert sync.sync_link(link) == 4
    assert sync.sync_link(link) == 0  # pas de doublon
    assert fake.prefer[0] == 'outlook.body-content-type="text"'  # texte simple, jamais de HTML
    by_id = {m.graph_id: m for m in MailMessage.objects.all()}
    assert by_id["m1"].suggested_client == company and not by_id["m1"].choice_needed
    assert by_id["m2"].suggested_client == company and by_id["m2"].suggested_person == sophie
    assert by_id["m2"].choice_needed and by_id["m2"].attachments.get().kind == "autre"
    assert by_id["m3"].suggested_client == company and "numéro d'entreprise" in by_id["m3"].reason
    assert by_id["m4"].suggested_client is None
    assert all(m.classed_at is None for m in by_id.values())  # rien n'est classé tout seul


def test_private_mail_is_never_copied_again(user, link, fake):
    fake.inbox = [mail("m1", sender="ami@exemple.test")]
    sync.sync_link(link)
    message = MailMessage.objects.get()
    from apps.mailbox import services

    services.remove_private(message)
    assert not MailMessage.objects.exists() and MailExclusion.objects.exists()
    link.inbox_cursor = None
    link.save()
    sync.sync_link(link)
    assert not MailMessage.objects.exists()


# --- Écran et classement -----------------------------------------------------------------------


def test_inbox_shows_where_each_mail_will_go_then_classify(web, user, link, fake, bakery):
    company, _ = bakery
    fake.inbox = [mail("m1", sender="compta@boulangerie.test", subject="Factures de septembre")]
    sync.sync_link(link)
    message = MailMessage.objects.get()
    html = inbox_html(web)
    assert "Factures de septembre" in html and "→ Boulangerie Fictive" in html
    html = inbox_html(web, message=message.pk)
    assert "Sera classé dans Boulangerie Fictive" in html and "Le dossier en bref" in html
    message.refresh_from_db()
    assert message.read_at is not None
    web.post(reverse("boite:classer", args=[message.pk]))
    message.refresh_from_db()
    assert message.client == company and message.classed_at
    assert "Factures de septembre" not in inbox_html(web)  # a quitté la réception
    tree = inbox_html(web, vue="dossier", dossier=company.pk)
    assert "Factures de septembre" in tree and "Pièces jointes" in tree


def test_private_address_asks_company_or_person_subfolder(web, user, link, fake, bakery):
    company, sophie = bakery
    fake.inbox = [mail("m1", sender="sophie.prive@exemple.test", subject="Question perso")]
    sync.sync_link(link)
    message = MailMessage.objects.get()
    html = inbox_html(web, message=message.pk)
    assert (
        "adresse privée" in html
        and "(personne physique, dans Boulangerie Fictive" in html
        and "(société)" in html
    )
    web.post(reverse("boite:classer", args=[message.pk]))  # sans choix : refusé
    message.refresh_from_db()
    assert message.classed_at is None
    web.post(reverse("boite:classer", args=[message.pk]), {"choix": f"p:{company.pk}:{sophie.pk}"})
    message.refresh_from_db()
    assert message.client == company and message.person == sophie
    html = inbox_html(web, vue="personne", dossier=company.pk, personne=sophie.pk)
    assert "Question perso" in html
    assert "Question perso" not in inbox_html(web, vue="dossier", dossier=company.pk)


def test_reclassify_and_hidden_dossiers_refused(web, user, link, fake, bakery):
    _company, _ = bakery
    other = ClientFactory(name="Brasserie Fictive")
    secret = ClientFactory(portfolio=PortfolioFactory(is_private=True))
    fake.inbox = [mail("m1", sender="inconnu@ailleurs.test", subject="Sans dossier")]
    sync.sync_link(link)
    message = MailMessage.objects.get()
    web.post(reverse("boite:reclasser", args=[message.pk]), {"cible": f"c:{secret.pk}"})
    message.refresh_from_db()
    assert message.client is None
    web.post(reverse("boite:reclasser", args=[message.pk]), {"cible": f"c:{other.pk}"})
    message.refresh_from_db()
    assert message.client == other and message.classed_at


def test_nobody_else_sees_my_mails(web, user, link, fake, client, make_user):
    fake.inbox = [mail("m1", sender="x@y.test", subject="Confidentiel")]
    sync.sync_link(link)
    message = MailMessage.objects.get()
    colleague = make_user(capabilities=["clients.edit"])
    MailboxLink.objects.create(user=colleague, address="c@c.test", token="x", read_enabled=True,
                               read_since=timezone.now())  # fmt: skip
    client.force_login(colleague)
    html = client.get(reverse("boite:inbox"), {"message": message.pk}).content.decode()
    assert "Confidentiel" not in html
    assert client.post(reverse("boite:classer", args=[message.pk])).status_code == 404


# --- Répondre, attendre une réponse ------------------------------------------------------------


def test_reply_written_by_the_employee_stays_until_classified(web, user, link, fake, bakery):
    fake.inbox = [mail("m1", sender="compta@boulangerie.test", subject="Question")]
    sync.sync_link(link)
    message = MailMessage.objects.get()
    web.post(reverse("boite:repondre", args=[message.pk]),
             {"texte": "Bonjour,\n<b>Oui</b> c'est possible.", "attente": "1"})  # fmt: skip
    graph_id, payload = fake.replies[0]
    assert graph_id == "m1" and "&lt;b&gt;Oui&lt;/b&gt;" in payload["comment"]  # échappé
    message.refresh_from_db()
    assert message.replied_at and message.classed_at is None
    assert "répondu ✓" in inbox_html(web)
    waiting = Awaiting.objects.get()
    assert "Question" in inbox_html(web, vue="attente")
    later = (timezone.now() + timedelta(minutes=5)).strftime("%Y-%m-%dT%H:%M:%SZ")
    fake.inbox = [mail("m2", sender="compta@boulangerie.test", subject="Re: Question", when=later)]
    sync.sync_link(link)
    waiting.refresh_from_db()
    assert waiting.done_at is not None  # la réponse est arrivée


def test_new_message_from_the_tool(web, user, link, fake):
    web.post(reverse("boite:nouveau"), {"a": "client@exemple.test", "objet": "Bilan",
                                        "texte": "Bonjour", "attente": "1"})  # fmt: skip
    assert fake.sent_mails[0]["message"]["subject"] == "Bilan"
    assert Awaiting.objects.get().address == "client@exemple.test"


# --- Échéances (clic droit) et agenda -----------------------------------------------------------


def test_deadline_from_a_mail_lands_in_my_agenda_with_a_reminder(web, user, link, fake, bakery):
    company, _ = bakery
    fake.inbox = [mail("m1", sender="compta@boulangerie.test", subject="Rendez-vous ?")]
    sync.sync_link(link)
    message = MailMessage.objects.get()
    raw = web.get(reverse("boite:inbox"), {"message": message.pk, "ouvrir": "echeance"})
    assert 'id="mb-echeance" data-open' in raw.content.decode()
    day = timezone.localdate()
    web.post(reverse("boite:echeance", args=[message.pk]), {
        "jour": day.isoformat(), "heure": "14:30", "fin": "15:30", "dossier": company.pk,
        "commentaire": "Rendez-vous", "rappel": "1"})  # fmt: skip
    task = Task.objects.get(title="Rendez-vous")
    assert task.due_time == time(14, 30) and task.remind and task.assignee == user
    agenda = unescape(web.get(reverse("core:agenda"), {"jour": day.isoformat()}).content.decode())
    assert "14:30–15:30 · Rendez-vous" in agenda and "Rappel d'aujourd'hui" in agenda
    assert deadlines.send_reminders(day) == 1 and deadlines.send_reminders(day) == 0
    assert Notification.objects.get(user=user).title.startswith("Rappel à 14:30")


def test_deadline_from_the_agenda(web, user, bakery):
    company, _ = bakery
    day = timezone.localdate() + timedelta(days=2)
    web.post(reverse("core:agenda_deadline"), {"jour": day.isoformat(), "dossier": company.pk,
                                               "commentaire": "Appeler le SPF"})  # fmt: skip
    task = Task.objects.get()
    assert task.due_time is None and not task.remind
    agenda = web.get(reverse("core:agenda"), {"jour": day.isoformat()}).content.decode()
    assert "Toute la journée" in agenda and "Appeler le SPF" in agenda


def test_add_to_timesheet_prefills_the_agenda(web, user, link, fake, bakery):
    _company, _ = bakery
    fake.inbox = [mail("m1", sender="compta@boulangerie.test", subject="Bilan 2025")]
    sync.sync_link(link)
    message = MailMessage.objects.get()
    response = web.get(reverse("boite:inbox"), {"message": message.pk, "ouvrir": "timesheet"})
    assert response.status_code == 302 and "dossier=" in response["Location"]
    page = web.get(response["Location"]).content.decode()
    assert 'value="Bilan 2025"' in page


# --- Pièces jointes et recherche ---------------------------------------------------------------


def test_attachment_filed_into_the_real_dossier(web, user, link, fake, bakery):
    company, _ = bakery
    fake.inbox = [mail("m1", sender="compta@boulangerie.test", attachments=True)]
    fake.attachments["m1"] = [file_attachment("releve.png")]
    sync.sync_link(link)
    piece = MailAttachment.objects.get()
    web.post(reverse("boite:classer", args=[piece.message.pk]))
    web.post(reverse("boite:ranger_piece", args=[piece.pk]), {"endroit": "folder:administratif"})
    piece.refresh_from_db()
    assert piece.filed_document.client == company and piece.filed_document.folder == "administratif"
    response = web.get(reverse("boite:piece", args=[piece.pk]))
    assert response["X-Content-Type-Options"] == "nosniff"


def test_search_ignores_accents_and_never_injects_html(web, user, link, fake, bakery):
    company, _ = bakery
    fake.inbox = [
        mail("m1", sender="compta@boulangerie.test", subject="Leasing",
             body="Voici le relevé du leasing de la camionnette <script>alert(1)</script>"),
        mail("m2", sender="compta@boulangerie.test", subject="Autre chose", body="Rien à voir"),
    ]  # fmt: skip
    sync.sync_link(link)
    raw = web.get(reverse("boite:inbox"), {"q": "releve camionnette"}).content.decode()
    assert "Leasing" in raw and "Autre chose" not in raw
    assert "<script>" not in raw and "<mark>" in raw
    raw = web.get(reverse("boite:inbox"), {"q": "camionnette", "dossier": company.pk}).content
    assert b"Leasing" in raw


# --- Conservation, désactivation -----------------------------------------------------------


def test_unclassified_copies_are_deleted_after_a_year(user, link, fake):
    fake.inbox = [mail("m1", sender="x@y.test")]
    sync.sync_link(link)
    assert sync.purge(timezone.now() + timedelta(days=400)) == 1
    assert not MailMessage.objects.exists()


def test_deactivate_deletes_every_copy(web, user, link, fake):
    fake.inbox = [mail("m1", sender="x@y.test")]
    sync.sync_link(link)
    web.post(reverse("boite:desactiver"))
    link.refresh_from_db()
    assert not link.read_enabled and not MailMessage.objects.exists()


def test_unread_badge_in_menu(web, user, link, fake):
    fake.inbox = [mail("m1", sender="x@y.test"), mail("m2", sender="x@y.test")]
    sync.sync_link(link)
    html = web.get(reverse("core:home")).content.decode()
    assert 'class="nav-count">2<' in html


def test_recognizes_an_ic_listing_attachment(bakery):
    from apps.clients.models import Client
    from apps.mailbox import recognize

    listing = b"""<?xml version="1.0"?>
<ns2:IntraConsignment xmlns="http://www.minfin.fgov.be/InputCommon"
  xmlns:ns2="http://www.minfin.fgov.be/IntraConsignment" IntraListingsNbr="1">
  <ns2:IntraListing SequenceNumber="1" ClientsNbr="1" AmountSum="100.00">
    <ns2:Declarant><VATNumber>BE0403170701</VATNumber></ns2:Declarant>
    <ns2:Period>332026</ns2:Period>
  </ns2:IntraListing>
</ns2:IntraConsignment>"""
    kind, label = recognize.recognize("ic.xml", listing, "application/xml", Client.objects.all())
    assert kind == "tva" and label.startswith("Listing intracommunautaire")


# --- Mise en forme et envoi programmé ------------------------------------------------------------


def test_formatting_is_kept_and_anything_dangerous_removed(web, user, link, fake):
    from apps.mailbox import richtext

    dirty = (
        '<p><b onclick="x()">Gras</b> <u>souligné</u></p><ul><li>un</li></ul>'
        '<img src=x onerror=alert(1)><a href="javascript:x">lien</a><script>x()</script>'
    )
    html, text = richtext.body(dirty, "")
    assert html == "<p><b>Gras</b> <u>souligné</u></p><ul><li>un</li></ul>lien"
    assert text.startswith("Gras souligné")
    web.post(reverse("boite:nouveau"), {"a": "client@exemple.test", "objet": "Bilan",
                                        "html": dirty, "texte": "ignoré"})  # fmt: skip
    body = fake.sent_mails[0]["message"]["body"]
    assert body["contentType"] == "HTML" and "<u>souligné</u>" in body["content"]
    assert "onclick" not in body["content"] and "script" not in body["content"]


def test_formatted_reply(web, user, link, fake, bakery):
    fake.inbox = [mail("m1", sender="compta@boulangerie.test", subject="Question")]
    sync.sync_link(link)
    message = MailMessage.objects.get()
    web.post(reverse("boite:repondre", args=[message.pk]),
             {"html": "<p>Oui, <strong>demain</strong>.</p>", "texte": "Oui, demain."})  # fmt: skip
    assert fake.replies[0][1]["comment"] == "<p>Oui, <strong>demain</strong>.</p>"


def later(**delta):
    return timezone.localtime(timezone.now() + timedelta(**delta)).strftime("%Y-%m-%dT%H:%M")


def test_scheduled_message_leaves_at_its_time_then_its_content_is_erased(web, user, link, fake):
    from apps.mailbox import services
    from apps.mailbox.models import ScheduledMail

    response = web.post(reverse("boite:nouveau"), {
        "a": "client@exemple.test", "objet": "Rappel bilan", "html": "<p>Bonjour</p>",
        "quand": "plus-tard", "programmer": later(hours=2), "attente": "1"})  # fmt: skip
    assert response.url.endswith("vue=programmes") and not fake.sent_mails
    item = ScheduledMail.objects.get()
    assert item.pending and "Rappel bilan" in inbox_html(web, vue="programmes")
    assert services.send_due() == 0  # pas encore l'heure
    assert services.send_due(timezone.now() + timedelta(hours=3)) == 1
    item.refresh_from_db()
    assert (
        item.sent_at
        and item.html == ""
        and fake.sent_mails[0]["message"]["subject"] == "Rappel bilan"
    )
    assert Awaiting.objects.get().address == "client@exemple.test"
    assert services.send_due(timezone.now() + timedelta(hours=4)) == 0  # jamais deux fois


def test_scheduled_reply_cancel_and_send_now(web, user, link, fake, bakery, make_user):
    from django.test import Client as Browser

    from apps.mailbox.models import ScheduledMail

    fake.inbox = [mail("m1", sender="compta@boulangerie.test", subject="Question")]
    sync.sync_link(link)
    message = MailMessage.objects.get()
    for _ in range(2):
        data = {"texte": "Réponse", "quand": "plus-tard", "programmer": later(days=1)}
        web.post(reverse("boite:repondre", args=[message.pk]), data)
    first, second = ScheduledMail.objects.all()
    assert first.to == "compta@boulangerie.test" and first.subject == "RE: Question"
    # Un collègue ne peut ni annuler ni envoyer mes messages programmés.
    colleague = Browser()
    colleague.force_login(make_user())
    assert colleague.post(reverse("boite:programme_annuler", args=[first.pk])).status_code == 404
    web.post(reverse("boite:programme_annuler", args=[first.pk]))
    first.refresh_from_db()
    assert first.cancelled_at and first.html == ""
    web.post(reverse("boite:programme_envoyer", args=[second.pk]))
    assert len(fake.replies) == 1 and fake.replies[0][0] == "m1"


def test_scheduling_in_the_past_is_refused(web, user, link, fake):
    from apps.mailbox.models import ScheduledMail

    data = {"a": "client@exemple.test", "texte": "Bonjour", "quand": "plus-tard",
            "programmer": later(hours=-1)}  # fmt: skip
    web.post(reverse("boite:nouveau"), data)
    assert not ScheduledMail.objects.exists() and not fake.sent_mails


def test_scheduled_message_given_up_after_three_failures(user, link, fake, monkeypatch):
    from apps.mailbox import services

    item = services.schedule(user, send_at=timezone.now() + timedelta(hours=1), html="<p>x</p>",
                             to="client@exemple.test", subject="Bilan")  # fmt: skip

    def refuse(*args, **kwargs):
        raise graph.MailboxError("Microsoft a refusé l'envoi.")

    monkeypatch.setattr(graph, "send", refuse)
    soon = timezone.now() + timedelta(hours=2)
    for _ in range(3):
        services.send_due(soon)
    item.refresh_from_db()
    assert item.failed_at and item.html == "" and item.attempts == 3
    assert Notification.objects.get(user=user).title == "Message programmé non envoyé : Bilan"
