"""Feuille de temps (D-058). Données fictives."""

from datetime import date, time

import pytest
from django.urls import reverse

from apps.core.models import AccessLog
from apps.core.testing.factories import ClientFactory, PortfolioFactory
from apps.timesheet.models import TimeEntry, hours_label

pytestmark = pytest.mark.django_db

MONDAY = date(2026, 10, 19)


def add(web, **data):
    payload = {"day": "2026-10-20", "start": "09:00", "end": "10:30", "activity": "tva",
               "description": "Encodage", **data}  # fmt: skip
    return web.post(reverse("temps:save"), payload)


def test_add_an_entry_linked_to_a_dossier_and_see_it_in_the_week(web, user):
    client = ClientFactory(name="Boulangerie Fictive")
    response = add(web, client=client.pk)
    assert response.status_code == 302
    entry = TimeEntry.objects.get()
    assert entry.user == user and entry.client == client and entry.minutes == 90
    assert entry.billable
    page = web.get(reverse("temps:week") + "?semaine=2026-10-21").content.decode()
    assert "Boulangerie Fictive" in page and "1 h 30" in page and "09:00–10:30" in page


def test_internal_work_without_dossier_is_not_billable(web):
    add(web, activity="formation")
    assert TimeEntry.objects.get().billable is False


def test_end_before_start_and_overlaps_are_refused(web):
    add(web, start="10:00", end="09:00")
    assert not TimeEntry.objects.exists()
    add(web)
    add(web, start="10:00", end="11:00")  # chevauche 9:00-10:30
    assert TimeEntry.objects.count() == 1


def test_cannot_link_a_dossier_one_cannot_see(web):
    secret = ClientFactory(portfolio=PortfolioFactory(is_private=True))
    add(web, client=secret.pk)
    assert not TimeEntry.objects.exists()


def test_each_one_sees_and_edits_only_his_own(web, make_user, client):
    colleague = make_user(capabilities=["clients.edit"])
    other = TimeEntry.objects.create(user=colleague, day=MONDAY, start=time(8), end=time(9))
    assert web.get(reverse("temps:week") + f"?qui={colleague.pk}").status_code == 403
    assert web.post(reverse("temps:delete", args=[other.pk])).status_code == 404
    boss = make_user(capabilities=["clients.edit", "timesheet.all"])
    client.force_login(boss)
    page = client.get(reverse("temps:week") + f"?semaine=2026-10-19&qui={colleague.pk}")
    assert page.status_code == 200 and "lecture seule" in page.content.decode()
    assert AccessLog.objects.filter(details__has_key="feuille de temps").exists()


def test_edit_and_delete(web, user):
    add(web)
    entry = TimeEntry.objects.get()
    add(web, entry=entry.pk, end="11:00")
    entry.refresh_from_db()
    assert entry.end == time(11) and TimeEntry.objects.count() == 1
    web.post(reverse("temps:delete", args=[entry.pk]))
    assert not TimeEntry.objects.exists()


def test_hours_on_a_dossier_are_for_the_administrator(client, web, user, make_user):
    """D-107 : un employé ne voit pas combien de temps ses collègues passent sur un dossier."""
    dossier = ClientFactory()
    colleague = make_user(capabilities=["clients.edit"])
    TimeEntry.objects.create(user=user, client=dossier, day=MONDAY, start=time(9), end=time(10),
                             activity="tva", description="Ma ligne")  # fmt: skip
    TimeEntry.objects.create(user=colleague, client=dossier, day=MONDAY, start=time(9),
                             end=time(11), activity="cloture", description="Bilan-XYZ")  # fmt: skip
    url = reverse("clients:time_spent", args=[dossier.pk])
    assert web.get(url).status_code == 403
    identity = web.get(reverse("clients:identity", args=[dossier.pk])).content.decode()
    assert "Heures prestées" not in identity
    admin = make_user(capabilities=["clients.edit", "timesheet.all"])
    client.force_login(admin)
    html = client.get(url).content.decode()
    assert "3 h" in html and "Ma ligne" in html and "Bilan-XYZ" in html
    assert (
        "Heures prestées"
        in client.get(reverse("clients:identity", args=[dossier.pk])).content.decode()
    )


def test_hours_label():
    assert hours_label(0) == "0 h" and hours_label(45) == "45 min"
    assert hours_label(90) == "1 h 30" and hours_label(120) == "2 h"


def test_my_agenda_tab_in_my_day(web, user):
    TimeEntry.objects.create(user=user, day=MONDAY, start=time(9), end=time(10, 15),
                             activity="interne", description="Réunion d'équipe")  # fmt: skip
    html = web.get(reverse("core:agenda") + "?jour=2026-10-19").content.decode()
    assert "Mon agenda" in html and "À traiter" in html and "1 h 15" in html
    assert "Réunion d" in html and 'data-ts-day="2026-10-19"' in html
    add(
        web,
        day="2026-10-19",
        start="11:00",
        end="12:00",
        retour="/ma-journee/agenda/?jour=2026-10-19",
    )
    assert TimeEntry.objects.count() == 2


def test_short_slot_is_shown_on_one_line_and_confirmation_only_once(web):
    """Retours de Jeremy (25/10) : un créneau de 30 min était illisible, et « … ajouté »
    s'affichait deux fois."""
    web.post(reverse("temps:save"), {"day": "2026-10-20", "start": "08:30", "end": "09:00",
             "activity": "tva", "description": "Encodage",
             "retour": reverse("core:agenda") + "?jour=2026-10-20"})  # fmt: skip
    page = web.get(reverse("core:agenda") + "?jour=2026-10-20").content.decode()
    assert "is-short" in page
    web.post(reverse("core:agenda_deadline"), {"jour": "2026-10-20", "commentaire": "Appel",
                                               "dossier": ClientFactory().pk})  # fmt: skip
    page = web.get(reverse("core:agenda") + "?jour=2026-10-20").content.decode()
    assert page.count("Échéance ajoutée") == 1


def test_missing_hours_are_refused_without_crashing(web):
    response = add(web, start="", end="")
    assert response.status_code == 302 and not TimeEntry.objects.exists()
