"""Onglet Clôture : checklist commune, personnalisation par dossier, coches, commentaires,
clôture comptable, « + Temps » (D-111). Données fictives."""

from datetime import date
from html import unescape

import pytest
from django.urls import reverse

from apps.clients.models import Assignment
from apps.closing import services
from apps.closing.models import ClosingYear, CommonItem, Kind, Tick
from apps.core.models import AccessLog
from apps.core.testing.factories import ClientFactory, PortfolioFactory
from apps.timesheet.models import TimeEntry

pytestmark = pytest.mark.django_db

TODAY = date(2026, 10, 30)
HX = {"HTTP_HX_REQUEST": "true"}


def company(vat="subject", **kwargs):
    return ClientFactory(vat_status=vat, fiscal_year_end_month=12, fiscal_year_end_day=31, **kwargs)


def year_of(client):
    services.ensure_years(client, TODAY)
    return ClosingYear.objects.get(client=client)


def test_common_checklists_come_from_jeremy():
    assert CommonItem.objects.filter(kind=Kind.VAT, active=True).count() == 16
    assert CommonItem.objects.filter(kind=Kind.NO_VAT, active=True).count() == 11
    no_vat = [i.label for i in services.items_for(company(vat="not_subject"))]
    assert "Ventes" not in no_vat and "Listing clients" not in no_vat
    assert no_vat[0] == "Achats" and "Compte d'attente (499)" in no_vat
    vat = [i.label for i in services.items_for(company())]
    assert {"Ventes", "Comptes TVA", "Clients ouverts", "Listing clients"} <= set(vat)


def test_last_ended_exercise_gets_a_line_with_the_team(user):
    client = company()
    Assignment.objects.create(client=client, user=user, role=Assignment.Role.MANAGER)
    year = year_of(client)
    assert (year.start, year.end, year.manager) == (date(2025, 1, 1), date(2025, 12, 31), user)
    assert year.label == "2025" and services.deposit(year) == "BNB pour le 31/07/2026"
    services.ensure_years(client, TODAY)  # pas de doublon
    assert client.closing_years.count() == 1


def test_open_comment_keeps_the_line_orange_until_resolved(user):
    client = company()
    year = year_of(client)
    key = next(i.key for i in services.items_for(client) if i.label.startswith("Compte d'attente"))
    services.set_tick(year, key, "ok", user)
    comment = services.add_comment(year, key, "Il reste 1 245 € au 499.", user)
    sheet = services.sheet(year)
    line = next(line for line in sheet.lines if line.item.key == key)
    assert line.state == "wip" and not Tick.objects.filter(year=year, key=key).exists()
    with pytest.raises(ValueError, match="commentaire est ouvert"):
        services.set_tick(year, key, "ok", user)
    services.resolve(comment, user)
    assert Tick.objects.get(year=year, key=key).status == "ok"


def test_line_turns_green_when_checklist_complete_and_closed(user):
    client = company(vat="not_subject")
    year = year_of(client)
    for item in services.items_for(client):
        services.set_tick(year, item.key, "ok", user)
    sheet = services.sheet(year)
    assert sheet.complete and not sheet.finished
    services.set_closed(year, True, user)
    assert services.sheet(year).finished


def test_dossier_customisation_is_kept_and_survives_common_changes(user):
    client, other = company(), company()
    items = services.items_for(client)
    sales = next(i for i in items if i.label == "Ventes")
    services.remove(client, sales.key)
    services.rename(client, items[0].key, "Achats et frais", "Y compris les tickets")
    leasing = services.add(client, "Leasing", "Tableau du leasing concordant")
    services.move(client, leasing.key, -1)
    labels = [i.label for i in services.items_for(client)]
    assert "Ventes" not in labels and labels[0] == "Achats et frais" and "Leasing" in labels
    assert labels.index("Leasing") == len(labels) - 2
    assert next(i.label for i in services.items_for(other)) == "Achats"  # l'autre reste
    # Un champ ajouté à la checklist commune arrive partout, sans défaire la personnalisation.
    services.common_add(Kind.VAT, "Stock", "Inventaire reçu")
    labels = [i.label for i in services.items_for(client)]
    assert "Stock" in labels and "Ventes" not in labels and labels[0] == "Achats et frais"
    assert "Stock" in [i.label for i in services.items_for(other)]
    services.restore(client, int(sales.key[1:]))
    assert "Ventes" in [i.label for i in services.items_for(client)]


def test_tab_checklist_and_close_through_the_pages(web, user):
    client = company(name="Garage Fictif SA")
    html = unescape(web.get(reverse("clients:closing", args=[client.pk])).content.decode())
    assert "2025" in html and "Checklist · 0 / 16" in html
    year = ClosingYear.objects.get(client=client)
    key = services.items_for(client)[0].key
    url = reverse("clients:closing_tick", args=[client.pk, year.pk, key])
    panel = unescape(web.post(url, {"status": "ok"}, **HX).content.decode())
    assert "1 / 16" in panel and Tick.objects.filter(year=year).count() == 1
    url = reverse("clients:closing_comment", args=[client.pk, year.pk, key])
    panel = unescape(web.post(url, {"text": "À revoir"}, **HX).content.decode())
    assert "Réglé : cocher la ligne" in panel
    row = web.post(reverse("clients:closing_close", args=[client.pk, year.pk]), **HX)
    assert "cl-close is-done" in row.content.decode()
    assert AccessLog.objects.filter(action="update", details__rubrique="cloture").exists()


def test_read_only_user_cannot_tick(client, make_user):
    target = company()
    year = year_of(target)
    client.force_login(make_user())  # pas le droit de modifier les fiches
    key = services.items_for(target)[0].key
    url = reverse("clients:closing_tick", args=[target.pk, year.pk, key])
    assert client.post(url, {"status": "ok"}).status_code == 403


def test_private_dossier_is_unreachable(web):
    hidden = company(portfolio=PortfolioFactory(is_private=True))
    year = year_of(hidden)
    assert web.get(reverse("clients:closing", args=[hidden.pk])).status_code == 404
    url = reverse("clients:closing_checklist", args=[hidden.pk, year.pk])
    assert web.get(url, **HX).status_code == 404


def test_plus_time_on_an_exercise_is_mine(web, user, make_user):
    client = company()
    year = year_of(client)
    url = reverse("clients:closing_time", args=[client.pk, year.pk])
    data = {"day": "2026-10-14", "start": "09:00", "end": "10:30"}
    row = web.post(url, data, **HX).content.decode()
    entry = TimeEntry.objects.get(user=user)
    assert (entry.closing_year, entry.activity) == (year, "cloture") and "1 h 30" in row
    TimeEntry.objects.create(user=make_user(), client=client, closing_year=year,
                             day=date(2026, 10, 14), start=entry.start, end=entry.end)  # fmt: skip
    services.add_my_time(user, [year])
    assert year.my_time == "1 h 30"  # pas le temps du collègue


def test_common_lists_are_for_administrators(web, client, make_user):
    assert web.get(reverse("closing:common")).status_code == 403
    admin = make_user(is_staff=True)
    client.force_login(admin)
    page = unescape(client.get(reverse("closing:common") + "?liste=sans_tva").content.decode())
    assert "Compte d'attente (499)" in page and "Listing clients" not in page
    client.post(
        reverse("closing:common"), {"liste": "sans_tva", "action": "ajouter", "label": "Stock"}
    )
    assert CommonItem.objects.filter(kind=Kind.NO_VAT, label="Stock").exists()
