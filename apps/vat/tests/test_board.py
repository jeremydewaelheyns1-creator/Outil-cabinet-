"""« Mes déclarations TVA » : un cadre par dossier, vert quand tout est fait (D-109). Fictif."""

from datetime import date, time
from html import unescape

import pytest
from django.urls import reverse

from apps.clients.models import Assignment
from apps.core.testing.factories import ClientFactory, PortfolioFactory
from apps.tasks.models import Task
from apps.timesheet.models import TimeEntry
from apps.vat import board, services
from apps.vat.models import Column, Status

pytestmark = pytest.mark.django_db

OCT = date(2026, 10, 14)


def mine(user, name):
    client = ClientFactory(name=name, vat_status="subject", vat_periodicity="quarterly")
    Assignment.objects.create(client=client, user=user, role=Assignment.Role.MANAGER)
    return client


def vat_task(client, due=date(2026, 10, 26), key="2026-T3"):
    return Task.objects.create(
        client=client, kind="tva_trimestrielle", title="TVA T3", due_date=due,
        period_key=key, period_label="3e trimestre 2026", period_start=date(2026, 7, 1),
    )  # fmt: skip


def all_done(client, key="2026-T3"):
    filing = services.filing_for(client, services.period(2026, quarter=int(key[-1])))
    for column in Column:
        status = Status.NOT_NEEDED if column == Column.IC else Status.DONE
        services.set_status(filing, column.value, status)
    return filing


def test_one_card_per_dossier_of_mine_grouped_by_state(user, make_user):
    bakery, garage = mine(user, "Boulangerie Fictive"), mine(user, "Garage Fictif")
    vat_task(bakery), vat_task(garage)
    vat_task(mine(make_user(), "Dossier du Collègue"))  # pas à moi : absent
    all_done(garage)
    data = board.build(user, OCT)
    names = {c.filing.client.name: c for c in data.cards}
    assert set(names) == {"Boulangerie Fictive", "Garage Fictif"}
    assert names["Boulangerie Fictive"].group == "todo"
    assert names["Garage Fictif"].group == "done" and names["Garage Fictif"].row.complete
    assert data.count("deposees") == 1 and data.count("pas-commencees") == 1


def test_late_and_filed_but_not_told_states(user):
    late, filed = mine(user, "Dossier En Retard"), mine(user, "Dossier Déposé")
    vat_task(late, due=date(2026, 10, 10)), vat_task(filed)
    filing = services.filing_for(filed, services.period(2026, quarter=3))
    services.set_status(filing, Column.FILED.value, Status.DONE)
    cards = {c.filing.client.name: c for c in board.build(user, date(2026, 10, 12)).cards}
    assert cards["Dossier En Retard"].tag == "en retard de 2 jours"
    assert cards["Dossier Déposé"].group == "doing"
    assert "informer" in cards["Dossier Déposé"].tag


def test_my_vat_time_on_the_declaration_is_shown(user, make_user):
    bakery = mine(user, "Boulangerie Fictive")
    vat_task(bakery)
    filing = services.filing_for(bakery, services.period(2026, quarter=3))
    TimeEntry.objects.create(user=user, client=bakery, vat_filing=filing, day=date(2026, 10, 5),
                             start=time(9), end=time(10, 30), activity="tva")  # fmt: skip
    colleague = make_user()
    TimeEntry.objects.create(
        user=colleague, client=bakery, vat_filing=filing, day=date(2026, 10, 5), start=time(9),
        end=time(12), activity="tva",
    )  # fmt: skip
    [card] = board.build(user, OCT).cards
    assert card.filing.my_time == "1 h 30"  # seulement mon temps


def test_plus_time_on_a_vat_line_adds_to_my_day(web, user):
    bakery = mine(user, "Boulangerie Fictive")
    filing = services.filing_for(bakery, services.period(2026, quarter=3))
    url = reverse("clients:vat_time", args=[bakery.pk, filing.pk])
    data = {"day": "2026-10-14", "start": "09:00", "end": "09:45", "description": "TVA T3"}
    row = web.post(url, data, HTTP_HX_REQUEST="true").content.decode()
    entry = TimeEntry.objects.get(user=user)
    assert (entry.client, entry.vat_filing, entry.activity) == (bakery, filing, "tva")
    assert "45 min" in row and 'id="vat-' in row
    # Créneau qui chevauche : refusé, avec la raison, rien d'enregistré en plus.
    row = unescape(web.post(url, data, HTTP_HX_REQUEST="true").content.decode())
    assert "chevauche" in row and TimeEntry.objects.count() == 1


def test_plus_time_needs_a_dossier_i_may_see(web, make_user):
    hidden = ClientFactory(name="Dossier Secret", portfolio=PortfolioFactory(is_private=True))
    filing = services.filing_for(hidden, services.period(2026, quarter=3))
    url = reverse("clients:vat_time", args=[hidden.pk, filing.pk])
    response = web.post(url, {"day": "2026-10-14", "start": "09:00", "end": "09:30"})
    assert response.status_code == 404 and not TimeEntry.objects.exists()


def test_vat_tab_columns_order(web, user):
    bakery = mine(user, "Boulangerie Fictive")
    services.filing_for(bakery, services.period(2026, quarter=3))
    html = unescape(web.get(reverse("clients:vat", args=[bakery.pk])).content.decode())
    positions = [html.index(h) for h in (">Acomptes<", ">Solde<", ">Com. client<", ">Mon temps<")]
    assert positions == sorted(positions)


def test_page_and_card_turn_green_when_everything_is_done(web, user, monkeypatch):
    monkeypatch.setattr("apps.vat.views.timezone.localdate", lambda: OCT)
    bakery = mine(user, "Boulangerie Fictive")
    vat_task(bakery)
    html = unescape(web.get(reverse("tasks:vat_board")).content.decode())
    assert "Boulangerie Fictive" in html and "vb-complete" not in html
    filing = all_done(bakery)
    services.set_status(filing, Column.CLIENT.value, "todo")
    url = reverse("clients:vat_cell", args=[bakery.pk, filing.pk, Column.CLIENT.value])
    response = web.post(url, {"status": "done", "vue": "echeances"}, HTTP_HX_REQUEST="true")
    card = response.content.decode()
    assert 'class="card vb-card vb-done vb-complete"' in card
    # Même ligne dans l'onglet « Déclaration TVA » du dossier : verte aussi.
    tab = web.get(reverse("clients:vat", args=[bakery.pk])).content.decode()
    assert "vat-complete" in tab


def test_the_page_only_shows_dossiers_i_may_see(web, user, make_user):
    vat_task(mine(make_user(), "Dossier Secret"))
    html = web.get(reverse("tasks:vat_board")).content.decode()
    assert "Dossier Secret" not in html


def test_accueil_button_opens_the_vat_page_in_the_vat_month(web, user, monkeypatch):
    monkeypatch.setattr("apps.core.views.timezone.localdate", lambda: OCT)
    vat_task(mine(user, "Boulangerie Fictive"))
    html = web.get(reverse("core:home")).content.decode()
    assert reverse("tasks:vat_board") in html
