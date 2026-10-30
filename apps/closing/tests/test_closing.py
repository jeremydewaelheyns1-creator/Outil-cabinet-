"""Onglet Clôture : checklist commune, personnalisation par dossier, coches, commentaires,
clôture comptable, « + Temps » (D-111). Données fictives."""

from datetime import date
from html import unescape

import pytest
from django.urls import reverse

from apps.clients.models import Assignment
from apps.closing import services
from apps.closing.models import ClosingYear, CommonItem, Kind, Part, Tick
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
    sheet, manager = services.sheet(year), services.sheet(year, Part.MANAGER)
    assert sheet.complete and not services.finished(sheet, manager)
    services.set_closed(year, True, user)
    for item in services.items_for(client, Part.MANAGER):
        services.set_tick(year, item.key, "ok", user)
    year.refresh_from_db()
    assert not services.finished(services.sheet(year), services.sheet(year, Part.MANAGER))
    services.set_closed(year, True, user, Part.MANAGER)
    assert services.finished(services.sheet(year), services.sheet(year, Part.MANAGER))


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
    assert "2025" in html and "Checklist comptable" in html and "0 / 16" in html
    year = ClosingYear.objects.get(client=client)
    key = services.items_for(client)[0].key
    url = reverse("clients:closing_tick", args=[client.pk, year.pk, "comptable", key])
    panel = unescape(web.post(url, {"status": "ok"}, **HX).content.decode())
    assert "1 / 16" in panel and Tick.objects.filter(year=year).count() == 1
    url = reverse("clients:closing_comment", args=[client.pk, year.pk, "comptable", key])
    panel = unescape(web.post(url, {"text": "À revoir"}, **HX).content.decode())
    assert "Réglé : cocher la ligne" in panel
    row = web.post(reverse("clients:closing_close", args=[client.pk, year.pk, "comptable"]), **HX)
    assert "cl-close is-done" in row.content.decode()
    assert AccessLog.objects.filter(action="update", details__rubrique="cloture").exists()


def test_read_only_user_cannot_tick(client, make_user):
    target = company()
    year = year_of(target)
    client.force_login(make_user())  # pas le droit de modifier les fiches
    key = services.items_for(target)[0].key
    url = reverse("clients:closing_tick", args=[target.pk, year.pk, "comptable", key])
    assert client.post(url, {"status": "ok"}).status_code == 403


def test_private_dossier_is_unreachable(web):
    hidden = company(portfolio=PortfolioFactory(is_private=True))
    year = year_of(hidden)
    assert web.get(reverse("clients:closing", args=[hidden.pk])).status_code == 404
    url = reverse("clients:closing_checklist", args=[hidden.pk, year.pk, "comptable"])
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


def test_manager_checklist_is_common_and_customisable_per_dossier(web, user):
    client, other = company(), company(vat="not_subject")
    labels = [i.label for i in services.items_for(client, Part.MANAGER)]
    assert labels == [
        "Vérification générale", "Compte courant", "ATN", "Intérêts fictifs",
        "Dette fiscale estimée", "Affectation du résultat N-1", "Provisions",
    ]  # fmt: skip
    assert [i.label for i in services.items_for(other, Part.MANAGER)] == labels  # TVA ou non
    services.add(client, "Leasing", "", Part.MANAGER)
    assert "Leasing" in [i.label for i in services.items_for(client, Part.MANAGER)]
    assert "Leasing" not in [i.label for i in services.items_for(client)]  # pas la comptable
    year = year_of(client)
    key = services.items_for(client, Part.MANAGER)[1].key
    url = reverse("clients:closing_comment", args=[client.pk, year.pk, "gestionnaire", key])
    panel = unescape(web.post(url, {"text": "Solde débiteur à justifier"}, **HX).content.decode())
    assert "Checklist gestionnaire" in panel and "Réglé : cocher la ligne" in panel
    row = web.post(
        reverse("clients:closing_close", args=[client.pk, year.pk, "gestionnaire"]), **HX
    )
    year.refresh_from_db()
    assert year.manager_closed_on is not None and year.closed_on is None
    assert "0 / 8" in unescape(row.content.decode())
    assert (
        web.get(
            reverse("clients:closing_checklist", args=[client.pk, year.pk, "x"]), **HX
        ).status_code
        == 404
    )


# --- Cases de dépôt (D-113) ---------------------------------------------------------------------


def test_deposit_box_ticks_its_deadline_and_back(web, user, django_capture_on_commit_callbacks):
    from apps.closing import deposits
    from apps.tasks.models import Task

    client = company(name="Garage Fictif SA")
    year = year_of(client)
    task = Task.objects.create(
        client=client, kind="comptes_annuels", title="Dépôt BNB", due_date=date(2026, 7, 31),
        period_key="EX-2025-12-31", assignee=user,
    )  # fmt: skip
    url = reverse("clients:closing_deposit", args=[client.pk, year.pk, "bnb"])
    row = unescape(web.post(url, {"action": "cocher"}, **HX).content.decode())
    task.refresh_from_db()
    assert task.status == Task.Status.DONE and "cl-deposit is-done" in row
    web.post(url, {"action": "decocher"}, **HX)
    task.refresh_from_db()
    assert task.status != Task.Status.DONE
    # Terminée dans l'échéancier : la case se coche.
    with django_capture_on_commit_callbacks(execute=True):
        web.post(reverse("tasks:status", args=[task.pk]), {"status": "done"})
    assert year.deposits.get(kind="bnb").done_on is not None
    assert [b.kind for b in deposits.boxes(year, deposits.kinds_for(client))] == [
        "ag", "bnb", "isoc", "270", "281", "listing", "ubo",
    ]  # fmt: skip


def test_file_dropped_in_a_box_is_archived_and_ticks_it(web, user):
    from django.core.files.uploadedfile import SimpleUploadedFile

    from apps.documents.models import Document

    client = company()
    year = year_of(client)
    url = reverse("clients:closing_deposit_file", args=[client.pk, year.pk, "270"])
    upload = SimpleUploadedFile("annexe-270-mlh.pdf", b"%PDF-1.4 annexe fictive\n%%EOF")
    row = unescape(web.post(url, {"fichier": upload}, **HX).content.decode())
    document = Document.objects.get(client=client)
    assert document.folder == "isoc" and "Annexes 270 2025" in document.title
    deposit = year.deposits.get(kind="270")
    assert deposit.done_on is not None and list(deposit.documents.all()) == [document]
    assert "1 fichier" in row


def test_box_can_be_removed_for_a_dossier_and_put_back(web):
    from apps.closing import deposits

    client = company()
    year = year_of(client)
    url = reverse("clients:closing_deposit", args=[client.pk, year.pk, "28150"])
    web.post(url, {"action": "retirer"}, **HX)
    assert "28150" not in deposits.kinds_for(client)
    html = unescape(web.get(reverse("clients:closing", args=[client.pk])).content.decode())
    assert "Fiches 281.50 — remettre" in html
    web.post(reverse("clients:closing_restore", args=[client.pk]), {"kind": "28150"})
    assert "28150" in deposits.kinds_for(client)


def test_row_is_green_only_when_deposits_are_done_too(user):
    from apps.closing import deposits

    client = company(vat="not_subject")
    year = year_of(client)
    for part in (Part.ACCOUNTING, Part.MANAGER):
        for item in services.items_for(client, part):
            services.set_tick(year, item.key, "ok", user)
        services.set_closed(year, True, user, part)
    year.refresh_from_db()
    kinds = deposits.kinds_for(client)
    sheets = services.sheet(year), services.sheet(year, Part.MANAGER)
    assert services.finished(*sheets) and not deposits.complete(deposits.boxes(year, kinds))
    for kind in kinds:
        deposits.set_done(year, kind, True, user)
    assert deposits.complete(deposits.boxes(year, kinds))


def test_bnb_xbrl_dropped_in_the_deposit_page_ticks_the_box(web):
    from apps.documents.tests.test_official_files import accounts_xbrl, xbrl_upload

    client = company()
    year = year_of(client)
    upload = xbrl_upload("comptes.xbrl", accounts_xbrl(client.enterprise_number))
    web.post(reverse("depot:index"), {"files": [upload]})
    deposit = year.deposits.get(kind="bnb")
    assert deposit.done_on is not None and deposit.documents.count() == 1


def _number(client) -> str:
    n = client.enterprise_number
    return f"BE {n[:4]}.{n[4:7]}.{n[7:]}"


@pytest.mark.parametrize(
    ("kind", "name", "paragraphs"),
    [
        ("ag", "pv-ag.pdf", [
            "PROCÈS-VERBAL DE L'ASSEMBLÉE GÉNÉRALE ORDINAIRE DU 30/06/2026",
            "Société fictive, numéro d'entreprise {n}",
            "L'assemblée approuve les comptes annuels de l'exercice clôturé le 31/12/2025.",
        ]),
        ("bnb", "comptes.pdf", [
            "COMPTES ANNUELS ET AUTRES DOCUMENTS À DÉPOSER EN VERTU DU CODE DES SOCIÉTÉS "
            "ET DES ASSOCIATIONS", "Numéro d'entreprise {n}",
            "et relatifs à l'exercice couvrant la période du 01/01/2025 au 31/12/2025",
        ]),
        ("isoc", "biztax.pdf", [
            "Biztax — accusé de réception", "Votre déclaration a bien été déposée.",
            "Impôt des sociétés — exercice d'imposition 2026 — {n}",
        ]),
        ("28150", "belcotax.pdf", [
            "Belcotax-on-web — accusé de réception", "Fiches 281.50 et relevé 325.50",
            "Année de revenus 2025 — débiteur {n}",
        ]),
        ("270", "annexe.pdf", [
            "Annexe 270 MLH à la déclaration — loyers et avantages locatifs",
            "Exercice d'imposition 2026 — {n}",
        ]),
    ],
)  # fmt: skip
def test_documents_read_and_filed_in_their_deposit_box(web, kind, name, paragraphs):
    from apps.documents.tests.test_official_files import pdf

    client = company()
    year = year_of(client)
    upload = pdf(name, *(p.format(n=_number(client)) for p in paragraphs))
    page = unescape(
        web.post(reverse("depot:index"), {"files": [upload]}, follow=True).content.decode()
    )
    deposit = year.deposits.get(kind=kind)
    assert deposit.done_on is not None and deposit.documents.count() == 1
    assert "cochée" in page


def test_biztax_receipt_citing_its_annexes_stays_an_isoc_receipt_and_no_year_no_tick(web):
    from apps.documents import spf_docs
    from apps.documents.models import Document
    from apps.documents.tests.test_official_files import pdf

    text = ("Biztax — accusé de réception. Votre déclaration a bien été déposée. "
            "Annexes jointes : 270 MLH. Exercice d'imposition 2026.")  # fmt: skip
    assert spf_docs.kind_of(text).slug == "biztax"
    client = company()  # pas encore de ligne d'exercice dans l'onglet Clôture
    upload = pdf("annexe.pdf", "Annexe 270 MLH — exercice d'imposition 2026", _number(client))
    web.post(reverse("depot:index"), {"files": [upload]})
    assert Document.objects.get(client=client).folder == "isoc"  # rangé quand même
    assert not ClosingYear.objects.filter(client=client).exists()


def test_each_dossier_only_sees_its_boxes(web, user, django_capture_on_commit_callbacks):
    """D-115 : listing clients seulement si TVA ; précompte mobilier seulement si l'AG a
    décidé un dividende ; 281.20 et 281.50 dans une seule case « Fiches 281 »."""
    from apps.closing import deposits
    from apps.tasks.models import Task

    asbl = company(vat="not_subject", name="ASBL Fictive")
    kinds = [b.kind for b in deposits.boxes(year_of(asbl), deposits.kinds_for(asbl))]
    assert kinds == ["ag", "bnb", "isoc", "270", "281", "ubo"]

    client = company(name="Garage Fictif SA")
    year = year_of(client)
    tab = web.get(reverse("clients:closing", args=[client.pk])).content.decode()
    assert "Listing clients" in tab and "Précompte mobilier ·" not in unescape(tab)
    assert "Dividende décidé ?" in unescape(tab)
    # Dividende : oui → la case Précompte apparaît, avec AG + 15 jours.
    web.post(
        reverse("clients:closing_deposit", args=[client.pk, year.pk, "ag"]), {"action": "cocher"}
    )
    url = reverse("clients:closing_dividend", args=[client.pk, year.pk])
    row = unescape(web.post(url, {"dividende": "oui"}, **HX).content.decode())
    assert "Précompte mobilier ·" in row
    year.refresh_from_db()
    pm = next(b for b in deposits.boxes(year, deposits.kinds_for(client)) if b.kind == "pm")
    assert pm.due == year.deposits.get(kind="ag").done_on + __import__("datetime").timedelta(15)
    web.post(url, {"dividende": "non"}, **HX)
    year.refresh_from_db()
    assert year.dividend is False
    assert "pm" not in [b.kind for b in deposits.boxes(year, deposits.kinds_for(client))]

    # Fiches 281 : orange à moitié, verte quand les deux sont faites.
    fiches_url = reverse("clients:closing_deposit", args=[client.pk, year.pk, "28120"])
    row = unescape(web.post(fiches_url, {"action": "cocher"}, **HX).content.decode())
    assert "cl-deposit is-wip" in row and "1 / 2" in row
    fiche = next(b for b in deposits.boxes(year, deposits.kinds_for(client)) if b.kind == "281")
    assert fiche.done_on is None and fiche.done_count == 1
    web.post(reverse("clients:closing_deposit", args=[client.pk, year.pk, "28150"]),
             {"action": "cocher"})  # fmt: skip
    fiche = next(b for b in deposits.boxes(year, deposits.kinds_for(client)) if b.kind == "281")
    assert fiche.done_on is not None
    # Pas de dirigeant rémunéré : 281.20 retirée, la case garde 281.50 seule.
    web.post(fiches_url, {"action": "retirer"}, **HX)
    fiche = next(b for b in deposits.boxes(year, deposits.kinds_for(client)) if b.kind == "281")
    assert [p.kind for p in fiche.parts] == ["28150"]

    # Listing clients 2025 terminé dans l'échéancier : la case se coche.
    task = Task.objects.create(
        client=client, kind="listing_clients_tva", title="Listing 2025", due_date=date(2026, 3, 31),
        period_key="2025", assignee=user,
    )  # fmt: skip
    with django_capture_on_commit_callbacks(execute=True):
        web.post(reverse("tasks:status", args=[task.pk]), {"status": "done"})
    assert year.deposits.get(kind="listing").done_on is not None


@pytest.mark.parametrize(
    ("text", "kind", "folder"),
    [
        ("Belcotax-on-web — accusé de réception. Fiches 281.20 et relevé 325.20. "
         "Année de revenus 2025.", "28120", "isoc"),
        ("Intervat — accusé de réception. Listing annuel des clients assujettis 2025.",
         "listing", "tva"),
    ],
)  # fmt: skip
def test_belcotax_28120_and_listing_receipts_tick_their_box(web, text, kind, folder):
    from apps.documents.models import Document
    from apps.documents.tests.test_official_files import pdf

    client = company()
    year = year_of(client)
    web.post(reverse("depot:index"), {"files": [pdf("accuse.pdf", text, _number(client))]})
    assert Document.objects.get(client=client).folder == folder
    assert year.deposits.get(kind=kind).done_on is not None
