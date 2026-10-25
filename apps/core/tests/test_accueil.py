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
    assert cal["name"] == "octobre 2026" and cal["legend"] == [(20, "TVA")]
    marked = [c["day"] for c in cal["cells"] if c.get("mark")]
    assert marked == [20] and cal["cells"][3]["day"] == 1  # le 1er octobre 2026 est un jeudi


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
