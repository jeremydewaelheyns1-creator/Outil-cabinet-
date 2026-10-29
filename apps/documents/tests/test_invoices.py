"""Factures du cabinet déposées : reconnues et rangées chez le client (D-105). Fictif."""

import shutil

import pytest
from django.urls import reverse

from apps.core.models import CabinetSettings
from apps.core.testing.factories import ClientFactory, PersonFactory
from apps.core.testing.numbers import enterprise_number
from apps.documents.models import Document, InboxItem
from apps.documents.tests.test_official_files import deposit, dotted, pdf

pytestmark = [
    pytest.mark.django_db,
    pytest.mark.skipif(not shutil.which("pdftotext"), reason="poppler absent"),
]


def cabinet(name="Fiduciaire Fictive SRL", number=9501):
    CabinetSettings.objects.update_or_create(
        pk=1, defaults={"name": name, "enterprise_number": dotted(number) if number else ""}
    )


def invoice(*lines, header=""):
    header = header or "Fiduciaire Fictive SRL — TVA BE " + dotted(9501)
    return pdf("facture.pdf", header, "FACTURE n° 2026-041", "Date : 15/10/2026", *lines,
               "Honoraires comptables 3e trimestre : 600,00 EUR HTVA — TVA 21 %")  # fmt: skip


def test_invoice_is_filed_with_the_client_by_enterprise_number(web):
    cabinet()
    garage = ClientFactory(name="Garage Fictif", enterprise_number=enterprise_number(9502))
    deposit(web, invoice(f"Client : Garage Fictif — BE {dotted(9502)}"))
    document = Document.objects.get(client=garage)
    assert document.folder == "factures" and document.title == "Facture 2026-041 du 15/10/2026"
    page = web.get(reverse("clients:archive", args=[garage.pk, "factures"])).content.decode()
    assert "Facture 2026-041" in page
    assert not garage.vat_filings.exists()  # pas prise pour une déclaration TVA


def test_invoice_found_by_the_client_name(web):
    cabinet()
    person = PersonFactory(name="Fictif", first_name="Paulette")
    deposit(web, invoice("Madame Paulette Fictif, Rue Imaginaire 1, 5000 Namur"))
    assert Document.objects.get(client=person).folder == "factures"


def test_credit_note(web):
    cabinet()
    garage = ClientFactory(name="Garage Fictif", enterprise_number=enterprise_number(9503))
    deposit(web, pdf("nc.pdf", "Fiduciaire Fictive SRL", "NOTE DE CRÉDIT n° NC-2026-3",
                     f"Client : BE {dotted(9503)}", "Date : 02/11/2026"))  # fmt: skip
    assert Document.objects.get(client=garage).title == "Note de crédit NC-2026-3 du 02/11/2026"


def test_two_possible_clients_wait_with_the_reason(web):
    cabinet()
    ClientFactory(name="Boulangerie Fictive")
    ClientFactory(name="Garage Fictif")
    deposit(web, invoice("Boulangerie Fictive et Garage Fictif"))
    item = InboxItem.objects.get()
    assert "Facture 2026-041" in item.reason and "plusieurs dossiers" in item.reason


def test_nothing_is_guessed_without_the_cabinet_name(web):
    cabinet(name="", number=None)
    ClientFactory(name="Garage Fictif", enterprise_number=enterprise_number(9504))
    deposit(web, invoice(f"Client : Garage Fictif — BE {dotted(9504)}", header="Cabinet"))
    assert not Document.objects.filter(folder="factures").exists()


def test_a_supplier_invoice_to_a_client_is_not_a_cabinet_invoice(web):
    cabinet()
    ClientFactory(name="Garage Fictif", enterprise_number=enterprise_number(9505))
    deposit(web, invoice(f"Client : Garage Fictif — BE {dotted(9505)}",
                         header="Pneus Imaginaires SA — fournisseur"))  # fmt: skip
    assert not Document.objects.filter(folder="factures").exists()


def test_cabinet_name_in_settings_and_on_documents(client, make_user):
    from apps.core.cabinet import cabinet_name

    admin = make_user(is_staff=True, capabilities=["clients.edit"])
    client.force_login(admin)
    page = client.get(reverse("core:cabinet_settings")).content.decode()
    assert "Identité du cabinet" in page and 'name="name"' in page
    data = {"action": "mandats", "name": "Fiduciaire Test", "enterprise_number": "",
            "spf_mandates_url": "https://example.org/mandats"}  # fmt: skip
    client.post(reverse("core:cabinet_settings"), data)
    assert cabinet_name() == "Fiduciaire Test"
