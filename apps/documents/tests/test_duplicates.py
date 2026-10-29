"""Doublons au dépôt : retenus, comparés côte à côte, l'utilisateur décide (D-099).

Demande de Jeremy : « fais apparaître une vue des deux docs et un petit bouton “Confirmer
l'import” et “Supprimer le doublon” » ; l'outil ne supprime jamais rien de lui-même.
"""

import pytest
from django.core.files.uploadedfile import SimpleUploadedFile
from django.urls import reverse

from apps.core.models import AccessLog
from apps.core.testing.factories import ClientFactory, PortfolioFactory
from apps.core.testing.numbers import enterprise_number
from apps.documents.models import Document, InboxItem
from apps.documents.tests.test_official_files import accounts_xbrl, xbrl_upload

pytestmark = pytest.mark.django_db
PDF = b"%PDF-1.4\n% document fictif\n"


def company(seed=9001, **kwargs):
    return ClientFactory(enterprise_number=enterprise_number(seed), **kwargs)


def deposit(web, *files, panel=False):
    url = reverse("depot:index") + ("?panneau=1" if panel else "")
    return web.post(url, {"files": list(files)})


def accounts(seed=9001, name="comptes.xbrl"):
    return xbrl_upload(name, accounts_xbrl(enterprise_number(seed)))


def test_same_file_twice_is_held_not_filed(web):
    garage = company()
    deposit(web, accounts())
    assert Document.objects.filter(client=garage).count() == 1
    html = deposit(web, accounts(name="copie.xbrl"), panel=True).content.decode()
    assert Document.objects.filter(client=garage).count() == 1  # pas rangé deux fois
    item = InboxItem.objects.get()
    assert item.duplicate_of == Document.objects.get(client=garage)
    assert f"Déjà dans {garage.display_name}" in html
    assert reverse("depot:duplicate", args=[item.pk]) in html
    page = web.get(reverse("depot:index")).content.decode()
    assert "<h2>Doublons à vérifier" in page and "Comparer" in page
    assert "Rien à classer." in page  # pas mélangé avec « À classer »


def test_two_identical_files_in_the_same_drop(web):
    company()
    deposit(web, accounts(name="a.xbrl"), accounts(name="b.xbrl"))
    assert Document.objects.count() == 1 and InboxItem.objects.get().duplicate_of is not None


def test_similar_but_different_file_is_not_a_duplicate(web):
    garage = company()
    deposit(web, accounts())
    changed = accounts_xbrl(enterprise_number(9001)).replace(b"55000.00", b"55000.01")
    deposit(web, xbrl_upload("corrige.xbrl", changed))
    assert Document.objects.filter(client=garage).count() == 2
    assert not InboxItem.objects.exists()


def test_comparison_page_shows_both_and_is_logged(web):
    garage = company()
    deposit(web, accounts())
    deposit(web, accounts(name="copie.xbrl"))
    item = InboxItem.objects.get()
    html = web.get(reverse("depot:duplicate", args=[item.pk])).content.decode()
    assert "Déjà dans l'outil" in html and "Nouveau dépôt" in html
    assert garage.display_name in html and "copie.xbrl" in html
    assert "Archives › Comptes annuels (BNB)" in html
    assert "Confirmer l'import" in html and "Supprimer le doublon" in html
    existing = item.duplicate_of
    assert AccessLog.objects.filter(object_id=str(existing.pk), details__doublon=True).exists()


def test_delete_the_duplicate_keeps_the_filed_document(web):
    company()
    deposit(web, accounts())
    deposit(web, accounts(name="copie.xbrl"))
    item = InboxItem.objects.get()
    kept = item.duplicate_of
    response = web.post(reverse("depot:duplicate_delete", args=[item.pk]))
    assert response.status_code == 302
    assert not InboxItem.objects.exists()
    assert Document.objects.filter(pk=kept.pk).exists()  # jamais touché


def test_confirm_import_files_it_a_second_time(web):
    garage = company()
    deposit(web, accounts())
    deposit(web, accounts(name="copie.xbrl"))
    item = InboxItem.objects.get()
    web.post(reverse("depot:duplicate_confirm", args=[item.pk]))
    assert Document.objects.filter(client=garage, folder="comptes").count() == 2
    assert not InboxItem.objects.exists()


def test_a_pdf_duplicate_shows_its_page(web):
    import shutil

    if not shutil.which("pdftoppm"):
        pytest.skip("poppler absent")
    from weasyprint import HTML

    garage = company()
    content = HTML(string="<p>Facture fictive</p>").write_pdf()
    document_url = reverse("clients:document_upload", args=[garage.pk])
    web.post(document_url, {"file": SimpleUploadedFile("f.pdf", content), "title": "Facture",
                            "folder": "administratif"})  # fmt: skip
    deposit(web, SimpleUploadedFile("encore.pdf", content))
    item = InboxItem.objects.get()
    assert item.duplicate_of.title == "Facture"
    html = web.get(reverse("depot:duplicate", args=[item.pk])).content.decode()
    assert reverse("depot:page", args=[item.pk, 1]) in html
    image = web.get(reverse("depot:page", args=[item.pk, 1]))
    assert image.status_code == 200 and image["Content-Type"] == "image/png"


def test_only_the_uploader_and_only_visible_dossiers(client, web, user, make_user):
    hidden = company(9002, portfolio=PortfolioFactory(is_private=True))
    Document.objects.create(client=hidden, title="Caché", folder="administratif",
                            original_name="c.pdf", content_type="application/pdf",
                            size=len(PDF), sha256=__import__("hashlib").sha256(PDF).hexdigest(),
                            file=SimpleUploadedFile("c.pdf", PDF))  # fmt: skip
    deposit(web, SimpleUploadedFile("c.pdf", PDF))
    item = InboxItem.objects.get()
    assert item.duplicate_of is None  # un document invisible n'est jamais révélé
    company(9003)
    deposit(web, accounts(9003))
    deposit(web, accounts(9003, name="copie.xbrl"))
    held = InboxItem.objects.get(duplicate_of__isnull=False)
    other = make_user(capabilities=["clients.edit"])
    client.force_login(other)
    assert client.get(reverse("depot:duplicate", args=[held.pk])).status_code == 404
    assert client.post(reverse("depot:duplicate_delete", args=[held.pk])).status_code == 404
    assert client.get(reverse("depot:page", args=[held.pk, 1])).status_code == 404
    assert InboxItem.objects.filter(pk=held.pk).exists()


def test_existing_document_removed_meanwhile(web):
    company()
    deposit(web, accounts())
    deposit(web, accounts(name="copie.xbrl"))
    item = InboxItem.objects.get()
    item.duplicate_of.delete()
    item.refresh_from_db()
    assert item.duplicate_of is None
    response = web.get(reverse("depot:duplicate", args=[item.pk]))
    assert response.status_code == 302  # plus rien à comparer : retour au dépôt
    page = web.get(reverse("depot:index")).content.decode()
    assert "copie.xbrl" in page and "<h2>Doublons à vérifier" not in page  # simple « À classer »


def test_confirm_an_unrecognised_file_puts_it_beside_the_original(web):
    """Une facture rangée à la main, redéposée : « Confirmer l'import » la range au même
    endroit au lieu de la renvoyer dans « À classer »."""
    garage = company()
    web.post(reverse("clients:document_upload", args=[garage.pk]),
             {"file": SimpleUploadedFile("f.pdf", PDF), "title": "Facture garage",
              "folder": "administratif"})  # fmt: skip
    deposit(web, SimpleUploadedFile("encore.pdf", PDF))
    item = InboxItem.objects.get()
    web.post(reverse("depot:duplicate_confirm", args=[item.pk]))
    copies = Document.objects.filter(client=garage, folder="administratif", title="Facture garage")
    assert copies.count() == 2
    assert not InboxItem.objects.exists()  # pas renvoyé dans « À classer »
