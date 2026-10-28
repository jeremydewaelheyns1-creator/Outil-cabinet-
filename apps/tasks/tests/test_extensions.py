"""Délais prolongés par le SPF : surveillance des flux, encodage, message à l'ouverture (D-089).

Flux et articles fictifs (aucune connexion réelle).
"""

from datetime import date, timedelta

import httpx
import pytest
from django.urls import reverse
from django.utils import timezone

from apps.core.models import Notification
from apps.core.testing.factories import ClientFactory
from apps.tasks import extensions, generator
from apps.tasks.models import DeadlineExtension, DeadlineNotice

pytestmark = pytest.mark.django_db


def rss(*items: tuple[str, str, str]) -> bytes:
    now = timezone.now().strftime("%a, %d %b %Y %H:%M:%S +0100")
    body = "".join(
        f"<item><title>{t}</title><link>{u}</link><description>{d}</description>"
        f"<pubDate>{now}</pubDate></item>"
        for t, u, d in items
    )
    return f'<?xml version="1.0"?><rss version="2.0"><channel>{body}</channel></rss>'.encode()


FEED = rss(
    ("Prolongation du délai de dépôt des déclarations TVA", "https://exemple.test/tva",
     "Le SPF Finances accorde un délai supplémentaire (exemple fictif)."),
    ("Résultats de l'adjudication OLO", "https://exemple.test/olo", "Agence de la Dette."),
    ("Nouvelle campagne de prévention routière", "https://exemple.test/route", "Sécurité."),
)  # fmt: skip


def fake_http(content: bytes = FEED, status: int = 200) -> httpx.Client:
    return httpx.Client(
        transport=httpx.MockTransport(lambda r: httpx.Response(status, content=content))
    )


def test_only_articles_about_tax_deadlines_are_kept():
    assert extensions.mentions_deadline("Report de la date limite de la déclaration IPP")
    assert not extensions.mentions_deadline("Report du match de football")
    assert not extensions.mentions_deadline("Nouvelle déclaration du ministre")
    items = extensions.parse_feed(FEED)
    assert items[0].url == "https://exemple.test/tva"


def test_watch_records_new_articles_once_and_tells_the_admins(settings, make_user):
    settings.DEADLINE_WATCH = True
    settings.DEADLINE_SOURCES = [("Source fictive", "https://flux.exemple.test/rss")]
    admin = make_user(is_staff=True)
    colleague = make_user()
    assert extensions.watch(fake_http()) == 1
    notice = DeadlineNotice.objects.get()
    assert notice.url == "https://exemple.test/tva" and notice.status == "new"
    assert Notification.objects.filter(user=admin, key=f"delais-spf:{notice.pk}").exists()
    assert not Notification.objects.filter(user=colleague).exists()
    assert extensions.watch(fake_http()) == 0  # déjà vu
    assert extensions.watch(fake_http(b"pas du xml", 200)) == 0  # source cassée : pas d'erreur
    assert extensions.watch(fake_http(b"", 503)) == 0


def test_old_articles_are_ignored(settings):
    settings.DEADLINE_WATCH = True
    settings.DEADLINE_SOURCES = [("Source fictive", "https://flux.exemple.test/rss")]
    old = FEED.replace(
        timezone.now().strftime("%a, %d %b %Y").encode(),
        (timezone.now() - timedelta(days=90)).strftime("%a, %d %b %Y").encode(),
    )
    assert extensions.watch(fake_http(old)) == 0


def quarterly(name):
    return ClientFactory(name=name, vat_status="subject", vat_periodicity="quarterly")


def test_extension_moves_every_dossier_and_survives_the_daily_generation(
    django_capture_on_commit_callbacks, make_user
):
    from apps.vat import services

    today = date(2026, 10, 5)
    first, second = quarterly("Fictive Un"), quarterly("Fictive Deux")
    for client in (first, second):
        generator.generate_for_client(client, today)
    filing = services.filing_for(first, services.period(2026, quarter=3))
    deadline = extensions.find("tva_trimestrielle|2026-T3|2026-10-25", today)
    assert deadline is not None and deadline.count == 2
    admin = make_user(is_staff=True)
    with django_capture_on_commit_callbacks(execute=True):
        extension = extensions.create(deadline, date(2026, 11, 10), user=admin)
    for client in (first, second):
        task = client.tasks.get(kind="tva_trimestrielle", period_key="2026-T3")
        assert task.due_date == date(2026, 11, 10)
    filing.refresh_from_db()
    assert filing.due_date == date(2026, 11, 10)  # la ligne TVA suit
    generator.generate_for_client(
        first, today
    )  # la génération quotidienne ne revient pas en arrière
    assert first.tasks.get(period_key="2026-T3", kind="tva_trimestrielle").due_date == date(
        2026, 11, 10
    )
    with django_capture_on_commit_callbacks(execute=True):
        assert extensions.cancel(extension, user=admin) == 2
    assert first.tasks.get(period_key="2026-T3", kind="tva_trimestrielle").due_date == date(
        2026, 10, 25
    )
    with pytest.raises(ValueError, match="après"):
        extensions.create(deadline, date(2026, 10, 1), user=admin)


def test_everyone_sees_the_message_once(client, make_user):
    quarterly("Fictive")
    generator.generate_for_client(ClientFactory._meta.model.objects.get(), timezone.localdate())
    deadline = extensions.deadlines()[0]
    admin = make_user(is_staff=True)
    extension = extensions.create(deadline, deadline.due_date + timedelta(days=15), user=admin)
    colleague = make_user()
    client.force_login(colleague)
    page = client.get(reverse("core:today")).content.decode()
    assert "Délai prolongé par le SPF Finances" in page and extension.label in page
    client.post(reverse("tasks:extension_seen", args=[extension.pk]), {"next": "https://ailleurs"})
    assert "Délai prolongé" not in client.get(reverse("core:today")).content.decode()
    client.force_login(admin)  # celui qui l'a encodée ne reçoit pas le message
    assert "Délai prolongé" not in client.get(reverse("core:today")).content.decode()


def test_admin_screen(client, make_user, web):
    url = reverse("tasks:extensions")
    assert web.get(url).status_code == 403  # réservé aux administrateurs
    quarterly("Fictive")
    generator.generate_for_client(ClientFactory._meta.model.objects.get(), timezone.localdate())
    notice = DeadlineNotice.objects.create(
        source="Source fictive", url="https://exemple.test/a", title="Délai TVA prolongé"
    )
    client.force_login(make_user(is_staff=True))
    page = client.get(url).content.decode()
    assert "Délai TVA prolongé" in page and "Encoder la prolongation" in page
    deadline = extensions.deadlines()[0]
    new = (deadline.due_date + timedelta(days=10)).isoformat()
    data = {"action": "create", "echeance": deadline.value, "nouvelle_date": new,
            "article": notice.pk, "note": "Exemple fictif"}  # fmt: skip
    assert client.post(url, data).status_code == 302
    extension = DeadlineExtension.objects.get()
    assert extension.source_url == "https://exemple.test/a"
    notice.refresh_from_db()
    assert notice.status == "handled"
    assert client.post(url, data).status_code == 302  # deuxième fois : refusé
    assert DeadlineExtension.objects.count() == 1
    other = DeadlineNotice.objects.create(source="x", url="https://exemple.test/b", title="Autre")
    client.post(url, {"action": "dismiss", "article": other.pk})
    other.refresh_from_db()
    assert other.status == "dismissed"
    assert client.post(url, {"action": "dismiss", "article": "abc"}).status_code == 404
