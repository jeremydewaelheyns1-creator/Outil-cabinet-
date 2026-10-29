"""Accueil personnel et gestion hybride des dossiers (D-063). Données fictives."""

from datetime import date, time, timedelta
from html import unescape

import pytest
from django.test import Client as Browser
from django.urls import reverse
from django.utils import timezone

from apps.clients import hybrid
from apps.clients.models import Assignment, HybridClaim
from apps.core import accueil
from apps.core.models import CabinetSettings, Notification
from apps.core.testing.factories import ClientFactory
from apps.tasks.models import Task
from apps.timesheet.models import TimeEntry

pytestmark = pytest.mark.django_db

OCT = date(2026, 10, 14)


def task(client, kind, due, status=Task.Status.TODO, label=""):
    return Task.objects.create(client=client, kind=kind, title=f"{kind} {label}", due_date=due,
                               period_label=label, status=status)  # fmt: skip


def mine(user, name="Dossier Fictif", role=Assignment.Role.MANAGER):
    client = ClientFactory(name=name)
    Assignment.objects.create(client=client, user=user, role=role)
    return client


def page(browser) -> str:
    return unescape(browser.get(reverse("core:home")).content.decode())


def enable_hybrid():
    settings = CabinetSettings.current()
    settings.hybrid_management = True
    settings.save()


# --- Les périodes ----------------------------------------------------------------------------


def test_october_is_the_vat_month_for_my_dossiers_only(user, make_user):
    bakery, garage = mine(user, "Boulangerie Fictive"), mine(user, "Garage Fictif")
    task(bakery, "tva_trimestrielle", date(2026, 10, 20), Task.Status.DONE, "3e trimestre 2026")
    task(garage, "tva_mensuelle", date(2026, 10, 20), label="septembre 2026")
    task(
        bakery, "isoc", date(2026, 10, 16), label="exercice 2025"
    )  # plus proche, mais la TVA prime
    colleague = make_user()
    task(mine(colleague, "Dossier du Collègue"), "tva_trimestrielle", date(2026, 10, 20))
    data = accueil.build(user, OCT)
    center = data["center"]
    assert center.family.code == "tva" and (center.done, center.total) == (1, 2)
    assert [line[0] for line in center.lines] == ["Mensuels · septembre 2026",
                                                  "Trimestriels · 3e trimestre 2026"]  # fmt: skip
    assert [r["task"].client for r in center.remaining] == [garage]
    assert data["countdown"] == "6 jours" and data["deadline_short"] == "20 octobre"
    assert [c.family.code for c in data["also"]] == ["isoc"]


def test_a_month_with_only_monthly_vat_is_not_a_big_period(user):
    client = mine(user)
    task(client, "tva_mensuelle", date(2026, 11, 20), label="octobre 2026")
    task(client, "listing_clients_tva", date(2027, 3, 31), label="2026")
    data = accueil.build(user, date(2026, 11, 5))
    assert data["center"] is None
    assert [c.family.code for c in data["also"]] == ["tva"]
    assert data["upcoming"].family.code == "listing" and data["upcoming_switch"] == date(2027, 3, 1)
    assert [r["task"].kind for r in data["todo"]] == ["tva_mensuelle"]


def test_ipp_season_then_annual_accounts_in_july(user):
    person, company = mine(user, "Personne Fictive"), mine(user, "Société Fictive")
    task(person, "ipp", date(2026, 10, 15), label="2025")
    task(company, "comptes_annuels", date(2026, 7, 31), label="exercice 2025")
    assert accueil.build(user, date(2026, 6, 12))["center"].family.code == "ipp"
    july = accueil.build(user, date(2026, 7, 24))
    assert july["center"].family.code == "comptes"
    assert [c.family.code for c in july["also"]] == ["ipp"]


def test_calendar_marks_my_deadlines_of_the_month(user):
    task(mine(user), "tva_trimestrielle", date(2026, 10, 20))
    cal = accueil.month_calendar(OCT, list(Task.objects.all()))
    assert cal["name"] == "octobre 2026"
    # Dates légales toujours montrées (D-094) : mensuelle le 20, trimestrielle le 25 (dimanche).
    # L'IPP des revenus 2025 a été reporté au 16 novembre (SPF, 29/10/2026) : plus en octobre.
    assert cal["legend"] == [
        (20, "TVA mensuelle · TVA trimestrielle"),
        (25, "TVA trimestrielle"),
    ]
    marked = [c["day"] for c in cal["cells"] if c.get("mark")]
    assert marked == [20, 25] and cal["cells"][3]["day"] == 1  # le 1er octobre : un jeudi
    november = accueil.month_calendar(date(2026, 11, 3), [])
    # Pas de trimestrielle en novembre ; l'IPP des revenus 2025, reporté au 16 novembre.
    assert november["legend"] == [(16, "IPP (revenus 2025)"), (20, "TVA mensuelle")]


def test_home_page_renders_and_shows_no_colleague_name(web, user, make_user):
    client = mine(user, "Boulangerie Fictive")
    today = timezone.localdate()
    task(client, "tva_trimestrielle", today + timedelta(days=2), label="période fictive")
    colleague = make_user(first_name="Collègue", last_name="Invisible")
    task(mine(colleague, "Dossier du Collègue"), "tva_trimestrielle", today + timedelta(days=2))
    html = page(web)
    assert "Accueil" in html and "Boulangerie Fictive" in html
    assert ", nous sommes le " in html and "Sites utiles" in html and "MyMinfin" in html
    assert "Dossier du Collègue" not in html and "Invisible" not in html
    assert "Dossiers hybrides" not in html  # option coupée par défaut


def test_home_without_any_dossier_explains(web):
    assert "Aucun dossier ne vous est affecté" in page(web)


def test_my_day_moved_but_still_there(web):
    assert web.get(reverse("core:today")).status_code == 200


def test_switcher_shows_the_last_five_dossiers(web, user):
    clients = [mine(user, f"Dossier {i}") for i in range(7)]
    for client in clients:
        web.get(reverse("clients:open", args=[client.pk]))
    web.post(reverse("clients:close"))
    html = web.get(reverse("clients:switcher")).content.decode()
    assert "Derniers dossiers ouverts" in html
    assert sum(f"Dossier {i}<" in html or f"Dossier {i} " in html for i in range(7)) == 5


# --- Gestion hybride -----------------------------------------------------------------------


def test_hybrid_choice_only_when_the_option_is_on(web, user):
    client = mine(user)
    url = reverse("clients:assignments", args=[client.pk])
    assert "Hybride" not in web.get(url).content.decode()
    enable_hybrid()
    accountant = Assignment.objects.create(client=client, user=user, role=Assignment.Role.ASSISTANT)
    assert "pas de comptable fixe" in web.get(url).content.decode()
    web.post(url, {"manager": user.pk, "hybride": "on"})
    client.refresh_from_db()
    assert client.accountant_hybrid
    assert not Assignment.objects.filter(pk=accountant.pk).exists()
    response = web.post(url, {"manager": user.pk, "assistant": user.pk, "hybride": "on"})
    assert "OU « Hybride »" in unescape(response.content.decode())


def test_take_and_release_a_hybrid_dossier(web, user, make_user):
    enable_hybrid()
    dossier = ClientFactory(name="Menuiserie Fictive", accountant_hybrid=True)
    open_task = task(dossier, "isoc", timezone.localdate() + timedelta(days=20), label="2025")
    colleague = make_user(capabilities=["clients.edit"], first_name="Camille")
    html = page(web)
    assert "Dossiers hybrides" in html and "1 libre" in html and "Je le prends" in html
    web.post(reverse("clients:hybrid_take", args=[dossier.pk]), {"retour": "/"})
    assert HybridClaim.objects.get().user == user
    open_task.refresh_from_db()
    assert open_task.assignee == user  # il devient le comptable le temps de la prise en charge
    assert "1 pris par moi" in page(web)
    assert dossier in accueil.my_clients(user)
    # Le collègue : ni ligne, ni bouton, seulement le compteur ; il ne peut pas le prendre.
    client = Browser()
    client.force_login(colleague)
    other = unescape(client.get(reverse("core:home")).content.decode())
    assert "1 pris par d'autres" in other and "Menuiserie Fictive" not in other
    client.post(reverse("clients:hybrid_take", args=[dossier.pk]))
    assert HybridClaim.objects.get().user == user
    detail = unescape(client.get(reverse("clients:identity", args=[dossier.pk])).content.decode())
    assert "Hybride · pris par" in detail and "Comptable : Hybride · pris par" in detail
    client.post(reverse("clients:hybrid_release", args=[dossier.pk]))
    assert HybridClaim.objects.exists()  # seul celui qui l'a pris (ou un administrateur)
    web.post(reverse("clients:hybrid_release", args=[dossier.pk]))
    assert not HybridClaim.objects.exists()
    open_task.refresh_from_db()
    assert open_task.assignee is None


def test_two_cannot_take_the_same_dossier(user, make_user):
    enable_hybrid()
    dossier = ClientFactory(accountant_hybrid=True)
    hybrid.take(dossier, user)
    with pytest.raises(hybrid.HybridError, match="vient d'être pris"):
        hybrid.take(dossier, make_user())


def test_forgotten_dossier_becomes_free_again(user):
    enable_hybrid()
    dossier = ClientFactory(name="Dossier Oublié", accountant_hybrid=True)
    claim = hybrid.take(dossier, user)
    claim.since = timezone.now() - timedelta(days=20)
    claim.save()
    worked = ClientFactory(name="Dossier Travaillé", accountant_hybrid=True)
    claim2 = hybrid.take(worked, user)
    claim2.since = claim.since
    claim2.save()
    TimeEntry.objects.create(user=user, client=worked, day=timezone.localdate(), start=time(9),
                             end=time(10), activity="compta")  # fmt: skip
    assert hybrid.release_stale() == 1
    assert list(HybridClaim.objects.values_list("client__name", flat=True)) == ["Dossier Travaillé"]
    assert Notification.objects.get(user=user).title.startswith(
        "Dossier rendu libre : Dossier Oublié"
    )


def test_hybrid_off_hides_everything(user):
    dossier = ClientFactory(accountant_hybrid=True)
    assert hybrid.board(user) is None
    with pytest.raises(hybrid.HybridError):
        hybrid.take(dossier, user)


def test_cabinet_settings_are_for_administrators(web, make_user):
    assert web.get(reverse("core:cabinet_settings")).status_code == 403
    admin = make_user(is_staff=True)
    browser = Browser()
    browser.force_login(admin)
    browser.post(reverse("core:cabinet_settings"), {"hybrid_management": "on",
                                                    "hybrid_release_days": "10"})  # fmt: skip
    settings = CabinetSettings.current()
    assert settings.hybrid_management and settings.hybrid_release_days == 10


def test_settings_link_in_the_top_bar_only_for_those_who_can(web, make_user):
    assert ">Paramètres<" not in page(web)
    browser = Browser()
    browser.force_login(make_user(capabilities=["reprise.import"]))
    assert ">Paramètres<" in unescape(browser.get(reverse("core:home")).content.decode())


def test_my_overdue_deadlines_are_signalled(web, user):
    client = mine(user)
    late = task(client, "isoc", timezone.localdate() - timedelta(days=3), label="2025")
    late.assignee = user
    late.save()
    assert "⚠ 1 échéance en retard" in page(web)


def test_first_of_the_month_reads_premier():
    from apps.core.templatetags.app_tags import date_fr

    assert date_fr(date(2027, 1, 1)) == "1er janvier"
    assert date_fr(date(2027, 1, 2), "l j F") == "samedi 2 janvier"


def test_hybrid_board_lists_only_the_most_urgent_free_dossiers(user, django_assert_max_num_queries):
    enable_hybrid()
    for i in range(hybrid.MAX_FREE_ROWS + 5):
        dossier = ClientFactory(name=f"Hybride {i:02d}", accountant_hybrid=True)
        task(dossier, "isoc", OCT + timedelta(days=i), label="2025")
    with django_assert_max_num_queries(8):
        board = hybrid.board(user)
    assert board.free == hybrid.MAX_FREE_ROWS + 5 and board.hidden == 5
    assert board.rows[0].client.name == "Hybride 00"


def test_pages_forbid_inline_scripts_and_framing(web):
    policy = web.get(reverse("core:home"))["Content-Security-Policy"]
    assert "script-src 'self'" in policy and "frame-ancestors 'none'" in policy


def test_dates_in_words_are_in_belgian_time():
    from datetime import UTC, datetime

    from django.template import Context, Template

    winter = datetime(2026, 10, 28, 8, 0, tzinfo=UTC)  # 9 h à Bruxelles
    html = Template('{{ d|date_fr:"j F à H:i" }}').render(Context({"d": winter}))
    assert html == "28 octobre à 09:00"


def test_vat_deadline_opens_the_vat_tab(user):
    client = mine(user)
    vat = task(client, "tva_trimestrielle", OCT, label="3e trimestre 2026")
    other = task(client, "isoc", OCT, label="2025")
    assert vat.work_url == reverse("clients:vat", args=[client.pk])
    assert other.work_url == reverse("clients:tasks", args=[client.pk])


def test_calendar_shows_ipp_even_without_dossier_and_follows_the_spf(user):
    """D-102 : la date publiée (revenus 2025 : 16 novembre, après le report) ; l'année d'après,
    « provisoire » jusqu'à ce que le SPF publie, puis la date confirmée par un administrateur."""
    from apps.tasks.models import DeadlineExtension

    november = accueil.month_calendar(date(2026, 10, 29), [], date(2026, 11, 1))
    assert (16, "IPP (revenus 2025)") in november["legend"]
    october_2027 = accueil.month_calendar(date(2027, 10, 1), [])
    assert (16, "IPP (revenus 2026) — date provisoire") in october_2027["legend"]
    DeadlineExtension.objects.create(kind="ipp", period_key="2026", label="IPP revenus 2026",
                                     previous_date=date(2027, 10, 16),
                                     new_date=date(2027, 10, 21))  # fmt: skip
    moved = accueil.month_calendar(date(2027, 10, 1), [])
    assert (21, "IPP (revenus 2026)") in moved["legend"]
    assert all(day != 16 for day, _ in moved["legend"])


def test_calendar_arrows_go_from_month_to_month(web, user):
    """D-104 : « deux petites flèches pour naviguer de mois en mois »."""
    from django.urls import reverse

    page = web.get(reverse("core:home")).content.decode()
    assert 'aria-label="Mois suivant"' in page and 'aria-label="Mois précédent"' in page
    task(mine(user), "isoc", date(2027, 1, 31), label="exercice 2026")
    january = web.get(reverse("core:home_calendar"), {"mois": "2027-01"}).content.decode()
    assert "Janvier 2027" in january and "ISOC" in january and "Aujourd'hui" in january
    assert "?mois=2026-12" in january and "?mois=2027-02" in january
    # Sans JavaScript : l'Accueil affiche le mois demandé.
    assert "Janvier 2027" in web.get(reverse("core:home"), {"mois": "2027-01"}).content.decode()
    assert web.get(reverse("core:home_calendar"), {"mois": "n'importe"}).status_code == 200
