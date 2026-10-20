"""Déclaration TVA : grille, cases, import Intervat (XML sûr, PDF prudent). Données fictives."""

from datetime import date
from decimal import Decimal

import pytest
from django.core.files.uploadedfile import SimpleUploadedFile
from django.urls import reverse

from apps.clients.models import Assignment
from apps.core.models import AccessLog
from apps.core.testing.factories import ClientFactory, PortfolioFactory
from apps.documents.models import Document
from apps.tasks.generator import generate_for_client
from apps.tasks.models import Task
from apps.vat import importer, intervat, services
from apps.vat.models import Column, Status, VatCell, VatFiling, VatNever, VatPending

pytestmark = pytest.mark.django_db

TODAY = date(2026, 10, 20)


def vat_xml(number: str, *, quarter: int | None = 3, month: int | None = None,
            year: int = 2026, grids: dict[str, str] | None = None, count: int = 1,
            other: str = "") -> bytes:  # fmt: skip
    """Déclaration Intervat fictive, au format du SPF Finances (espaces de noms compris)."""
    grids = grids if grids is not None else {"00": "1000.00", "54": "210.00", "71": "4272.44"}
    period = (
        f"<ns2:Quarter>{quarter}</ns2:Quarter>" if quarter else f"<ns2:Month>{month}</ns2:Month>"
    )
    amounts = "".join(f'<ns2:Amount GridNumber="{g}">{v}</ns2:Amount>' for g, v in grids.items())
    declarations = ""
    for index, num in enumerate([number, other][:count], start=1):
        declarations += f"""
  <ns2:VATDeclaration SequenceNumber="{index}">
    <ns2:Declarant><VATNumber>{num}</VATNumber><Name>Fictif</Name></ns2:Declarant>
    <ns2:Period>{period}<ns2:Year>{year}</ns2:Year></ns2:Period>
    <ns2:Data>{amounts}</ns2:Data>
  </ns2:VATDeclaration>"""
    return f"""<?xml version="1.0" encoding="UTF-8"?>
<ns2:VATConsignment xmlns="http://www.minfin.fgov.be/InputCommon"
  xmlns:ns2="http://www.minfin.fgov.be/VATConsignment" VATDeclarationsNbr="{count}">
  <ns2:Representative><RepresentativeID identificationType="NVAT" issuedBy="BE">0999999990
  </RepresentativeID></ns2:Representative>{declarations}
</ns2:VATConsignment>""".encode()


def ic_xml(number: str) -> bytes:
    return f"""<?xml version="1.0"?>
<ns2:IntraConsignment xmlns="http://www.minfin.fgov.be/InputCommon"
  xmlns:ns2="http://www.minfin.fgov.be/IntraConsignment" IntraListingsNbr="1">
  <ns2:IntraListing SequenceNumber="1" ClientsNbr="1" AmountSum="100.00">
    <ns2:Declarant><VATNumber>{number}</VATNumber></ns2:Declarant>
    <ns2:Period>332026</ns2:Period>
  </ns2:IntraListing>
</ns2:IntraConsignment>""".encode()


def pdf_with(text: str) -> bytes:
    from weasyprint import HTML

    return bytes(HTML(string=f"<p>{text}</p>").write_pdf())


def upload(name: str, content: bytes) -> SimpleUploadedFile:
    return SimpleUploadedFile(name, content)


def vat_client(**kwargs):
    return ClientFactory(vat_status="subject", vat_periodicity="quarterly", **kwargs)


# --- Lecture des fichiers ---------------------------------------------------------------------


def test_reads_an_intervat_declaration():
    company = vat_client()
    [declaration] = intervat.parse_xml(vat_xml(f"BE{company.enterprise_number}"))
    assert declaration.kind == intervat.VAT
    assert (declaration.enterprise_number, declaration.year, declaration.quarter) == (
        company.enterprise_number, 2026, 3,
    )  # fmt: skip
    assert declaration.grids["71"] == Decimal("4272.44")


def test_reads_a_monthly_declaration_and_an_ic_listing():
    company = vat_client()
    [monthly] = intervat.parse_xml(vat_xml(company.enterprise_number, quarter=None, month=9))
    assert (monthly.month, monthly.quarter) == (9, None)
    [listing] = intervat.parse_xml(ic_xml(company.enterprise_number))
    assert (listing.kind, listing.year, listing.quarter) == (intervat.IC, 2026, 3)


@pytest.mark.parametrize(
    "content",
    [
        b"pas du xml",
        b"<?xml version='1.0'?><Autre/>",
        # Entité externe : refusée (lecture d'un fichier du serveur).
        b'<?xml version="1.0"?><!DOCTYPE x [<!ENTITY e SYSTEM "file:///etc/passwd">]>'
        b"<VATConsignment>&e;</VATConsignment>",
    ],
)
def test_refuses_unreadable_or_dangerous_xml(content):
    with pytest.raises(intervat.IntervatError):
        intervat.parse_xml(content)


def test_invalid_vat_number_is_refused():
    with pytest.raises(intervat.IntervatError):
        intervat.parse_xml(vat_xml("0123456789"))


def test_pdf_clues():
    company = vat_client()
    number = company.enterprise_number
    formatted = f"{number[:4]}.{number[4:7]}.{number[7:]}"
    clues = intervat.read_pdf(pdf_with(f"Déclaration périodique TVA — BE {formatted} — "
                                       "3e trimestre 2026"))  # fmt: skip
    assert clues.numbers == (number,)
    assert (clues.kind, clues.year, clues.quarter) == (intervat.VAT, 2026, 3)


# --- Grille -----------------------------------------------------------------------------------


def test_grid_follows_the_vat_deadlines():
    company = vat_client()
    generate_for_client(company, TODAY)
    rows = services.grid(company, TODAY)
    keys = [r.filing.period_key for r in rows]
    assert "2026-T3" in keys and "2026-T4" in keys  # période commencée
    assert "2027-T1" not in keys  # pas encore commencée
    t3 = next(r for r in rows if r.filing.period_key == "2026-T3")
    assert t3.filing.task is not None and t3.filing.due_date == t3.filing.task.due_date
    assert [c.status for c in t3.cells] == [Status.TODO] * 5


def test_filed_cell_closes_the_deadline_and_reopens_it(make_user):
    company = vat_client()
    generate_for_client(company, TODAY)
    filing = services.grid(company, TODAY)[0].filing
    user = make_user()
    services.set_status(filing, Column.DOCS, Status.DONE, user=user)
    filing.task.refresh_from_db()
    assert filing.task.status == Task.Status.IN_PROGRESS
    services.set_status(filing, Column.FILED, Status.DONE, user=user)
    filing.task.refresh_from_db()
    assert filing.task.status == Task.Status.DONE
    services.set_status(filing, Column.FILED, Status.WARNING, user=user)
    filing.task.refresh_from_db()
    assert filing.task.status == Task.Status.IN_PROGRESS


def test_never_applies_to_the_whole_column():
    company = vat_client()
    generate_for_client(company, TODAY)
    filing = services.grid(company, TODAY)[0].filing
    services.set_status(filing, Column.IC, Status.NEVER)
    rows = services.grid(company, TODAY)
    assert all(r.cells[3].never for r in rows)
    assert VatNever.objects.filter(client=company, column=Column.IC).exists()
    services.set_status(filing, Column.IC, Status.DONE)  # on le réactive
    assert not services.grid(company, TODAY)[1].cells[3].never


def test_cell_view_requires_edit_right_and_returns_the_row(web, client, make_user):
    company = vat_client()
    filing = services.filing_for(company, services.period(2026, quarter=3))
    url = reverse("clients:vat_cell", args=[company.pk, filing.pk, "docs"])
    response = web.post(url, {"status": "warning", "comment": "relancé"}, HTTP_HX_REQUEST="true")
    assert response.status_code == 200 and f'id="vat-{filing.pk}"' in response.content.decode()
    cell = VatCell.objects.get(filing=filing, column="docs")
    assert (cell.status, cell.comment) == ("warning", "relancé")
    web.post(url, {"status": "todo"})  # recliquer sur l'état en cours vide la case
    cell.refresh_from_db()
    assert cell.status == "todo" and cell.on is None
    web.post(url, {"status": "never"})  # état qui n'est plus proposé : ignoré
    assert not VatNever.objects.exists()
    assert AccessLog.objects.filter(action="update", details__rubrique="tva").exists()
    client.force_login(make_user())  # lecture seule
    assert client.post(url, {"status": "done"}).status_code == 403


def test_grid_of_a_private_client_is_unreachable(web):
    hidden = vat_client(portfolio=PortfolioFactory(is_private=True))
    filing = services.filing_for(hidden, services.period(2026, quarter=3))
    assert web.get(reverse("clients:vat", args=[hidden.pk])).status_code == 404
    url = reverse("clients:vat_cell", args=[hidden.pk, filing.pk, "docs"])
    assert web.post(url, {"status": "done"}).status_code == 404


def test_amounts_advances_and_remark(web):
    company = vat_client()
    filing = services.filing_for(company, services.period(2026, quarter=3))
    url = reverse("clients:vat_amounts", args=[company.pk, filing.pk])
    web.post(url, {"grid_71": "1 234,50", "advance_1": "400", "remark": "Mail envoyé"})
    filing.refresh_from_db()
    assert filing.balance == ("71", Decimal("1234.50"))
    assert (filing.advance_1, filing.remark) == (Decimal("400.00"), "Mail envoyé")
    web.post(url, {"grid_71": "abc"})
    filing.refresh_from_db()
    assert filing.grid_71 == Decimal("1234.50")  # montant invalide refusé


def test_grid_page_shows_rows_and_statuses(web):
    company = vat_client()
    Assignment.objects.create(client=company, user=web_user(web), role="manager")
    generate_for_client(company, TODAY)
    html = web.get(reverse("clients:vat", args=[company.pk])).content.decode()
    assert "Déposer des documents" in html
    assert "Avertissement" in html and "Pas nécessaire pour cette période" in html
    assert "Jamais nécessaire" not in html and "En attente" not in html


def web_user(web):
    from django.contrib.auth import get_user

    return get_user(web)


# --- Import -----------------------------------------------------------------------------------


def test_xml_and_pdf_are_classified_in_the_right_dossier(web):
    here = vat_client()
    other = vat_client(name="Garage Fictif SRL")
    number = other.enterprise_number
    files = [
        upload("declaration.xml", vat_xml(f"BE{number}")),
        upload("declaration.pdf", pdf_with(f"Déclaration TVA BE{number} — 3e trimestre 2026")),
    ]
    response = web.post(reverse("depot:index"), {"files": files})
    assert response.status_code == 302
    filing = VatFiling.objects.get(client=other, period_key="2026-T3")
    assert filing.balance == ("71", Decimal("4272.44"))
    assert filing.xml.folder == "tva" and filing.pdf.folder == "tva"
    assert filing.cells.get(column="filed").status == Status.DONE
    assert not VatFiling.objects.filter(client=here).exists()
    assert AccessLog.objects.filter(action="import", object_id=str(other.pk)).exists()


def test_same_file_twice_is_not_stored_twice(user):
    company = vat_client()
    content = vat_xml(company.enterprise_number)
    clients = type(company).objects.all()
    importer.import_files([upload("a.xml", content)], clients=clients, user=user)
    [outcome] = importer.import_files([upload("a.xml", content)], clients=clients, user=user)
    assert outcome.level == importer.SAME
    assert Document.objects.filter(client=company).count() == 1


def test_refund_declaration_shows_grid_72(user):
    company = vat_client()
    content = vat_xml(company.enterprise_number, grids={"72": "812.10"})
    importer.import_files([upload("a.xml", content)], clients=type(company).objects.all(),
                          user=user)  # fmt: skip
    filing = VatFiling.objects.get(client=company)
    assert filing.balance == ("72", Decimal("812.10"))


def test_ic_listing_ticks_the_ic_cell(user):
    company = vat_client()
    importer.import_files([upload("ic.xml", ic_xml(company.enterprise_number))],
                          clients=type(company).objects.all(), user=user)  # fmt: skip
    filing = VatFiling.objects.get(client=company, period_key="2026-T3")
    assert filing.ic_xml is not None
    assert filing.cells.get(column="ic").status == Status.DONE


def test_unknown_or_hidden_client_is_never_filed(user):
    hidden = vat_client(portfolio=PortfolioFactory(is_private=True))
    from apps.clients.models import Client

    visible = Client.objects.visible_to(user)
    [outcome] = importer.import_files([upload("a.xml", vat_xml(hidden.enterprise_number))],
                                      clients=visible, user=user)  # fmt: skip
    assert outcome.level == importer.ERROR
    assert not VatFiling.objects.exists() and not Document.objects.exists()


def test_grouped_file_is_not_stored_in_any_dossier(user):
    first, second = vat_client(), vat_client()
    content = vat_xml(first.enterprise_number, count=2, other=second.enterprise_number)
    [outcome] = importer.import_files([upload("lot.xml", content)],
                                      clients=type(first).objects.all(), user=user)  # fmt: skip
    assert outcome.level == importer.OK
    assert VatFiling.objects.filter(grid_71=Decimal("4272.44")).count() == 2
    assert not Document.objects.exists()


def test_pdf_alone_waits_for_confirmation(web):
    company = vat_client()
    number = company.enterprise_number
    services.filing_for(company, services.period(2026, quarter=3))
    web.post(reverse("depot:index"),
             {"files": [upload("d.pdf", pdf_with(f"Déclaration TVA BE{number}"))]})  # fmt: skip
    pending = VatPending.objects.get()
    assert pending.document.client == company and pending.period_key == ""
    filing = VatFiling.objects.get(client=company)
    html = web.get(reverse("depot:index")).content.decode()
    assert "À confirmer" in html
    web.post(reverse("clients:vat_confirm", args=[company.pk, pending.pk]),
             {"filing": filing.pk, "kind": "vat"})  # fmt: skip
    filing.refresh_from_db()
    assert filing.pdf == pending.document and not VatPending.objects.exists()
    assert filing.cells.get(column="filed").status == Status.DONE


def test_pdf_alone_matching_an_imported_xml_is_attached(user):
    company = vat_client()
    number = company.enterprise_number
    clients = type(company).objects.all()
    importer.import_files([upload("a.xml", vat_xml(number))], clients=clients, user=user)
    [outcome] = importer.import_files(
        [upload("a.pdf", pdf_with(f"BE{number} 3e trimestre 2026"))], clients=clients, user=user
    )
    assert outcome.level == importer.OK
    assert VatFiling.objects.get(client=company).pdf is not None


def test_unrecognised_pdf_is_not_stored(user):
    company = vat_client()
    [outcome] = importer.import_files([upload("x.pdf", pdf_with("rien"))],
                                      clients=type(company).objects.all(), user=user)  # fmt: skip
    assert outcome.level == importer.ERROR and not Document.objects.exists()


def test_other_formats_are_refused(user):
    clients = type(ClientFactory()).objects.all()
    [outcome] = importer.import_files([upload("x.txt", b"bonjour")], clients=clients, user=user)
    assert outcome.level == importer.ERROR
