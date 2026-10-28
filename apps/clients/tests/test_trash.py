"""Corbeille des dossiers : sélectionner, confirmer, retrouver, réactiver (D-095)."""

from datetime import date

import pytest
from django.urls import reverse

from apps.clients.models import Client
from apps.clients.tests.test_views import form_data
from apps.core.models import AccessLog
from apps.core.testing.factories import ClientFactory, PortfolioFactory
from apps.core.testing.numbers import enterprise_number

pytestmark = pytest.mark.django_db


@pytest.fixture
def admin(client, make_user):
    user = make_user(is_staff=True, capabilities=["clients.edit"])
    client.force_login(user)
    return user


def quarterly(name="Garage Fictif"):
    return ClientFactory(name=name, vat_status="subject", vat_periodicity="quarterly")


def test_select_confirm_then_trash(client, admin, django_capture_on_commit_callbacks):
    from apps.documents.models import DocumentRequest
    from apps.tasks.generator import generate_for_client

    garage, other = quarterly(), ClientFactory(name="Boulangerie Fictive")
    generate_for_client(garage, date.today())
    assert garage.tasks.filter(status="todo", due_date__gte=date.today()).exists()
    request = DocumentRequest.objects.create(client=garage, kind="identity_card", title="Carte")
    listing = client.get(reverse("clients:list")).content.decode()
    assert 'name="client"' in listing and "Supprimer la sélection" in listing
    url = reverse("clients:trash_put")
    # 1er clic : on demande si on est bien sûr, rien ne bouge.
    page = client.post(url, {"client": [garage.pk]}).content.decode()
    assert "Êtes-vous sûr" in page and "Garage Fictif" in page and "Corbeille" in page
    garage.refresh_from_db()
    assert garage.deleted_at is None
    # 2e clic : à la corbeille.
    with django_capture_on_commit_callbacks(execute=True):
        response = client.post(url, {"client": [garage.pk], "confirme": "oui"})
    assert response.status_code == 302
    garage.refresh_from_db()
    assert garage.deleted_at is not None and garage.deleted_by == admin
    assert not Client.objects.visible_to(admin).filter(pk=garage.pk).exists()
    assert client.get(reverse("clients:detail", args=[garage.pk])).status_code == 404
    assert "Garage Fictif" not in client.get(reverse("clients:list")).content.decode()
    request.refresh_from_db()
    assert request.status == "cancelled"  # plus aucune relance au client
    assert not garage.tasks.filter(status="todo", due_date__gte=date.today()).exists()
    assert AccessLog.objects.filter(action="delete", details__corbeille="mis").exists()
    other.refresh_from_db()
    assert other.deleted_at is None  # seul le dossier coché


def test_find_and_reactivate(client, admin, django_capture_on_commit_callbacks):
    garage = quarterly()
    with django_capture_on_commit_callbacks(execute=True):
        client.post(reverse("clients:trash_put"), {"client": [garage.pk], "confirme": "oui"})
    page = client.get(reverse("clients:trash")).content.decode()
    assert "Garage Fictif" in page and "Réactiver" in page
    assert "Corbeille (1)" in client.get(reverse("clients:list")).content.decode()
    with django_capture_on_commit_callbacks(execute=True):
        client.post(reverse("clients:trash_restore"), {"client": [garage.pk]})
    garage.refresh_from_db()
    assert garage.deleted_at is None
    assert client.get(reverse("clients:detail", args=[garage.pk])).status_code == 200
    assert garage.tasks.filter(kind="tva_trimestrielle").exists()  # échéances revenues
    assert AccessLog.objects.filter(action="update", details__corbeille="réactivé").exists()


def test_only_administrators_and_only_visible_dossiers(client, make_user, admin):
    hidden = ClientFactory(name="Dossier Privé", portfolio=PortfolioFactory(is_private=True))
    client.post(reverse("clients:trash_put"), {"client": [hidden.pk], "confirme": "oui"})
    hidden.refresh_from_db()
    assert hidden.deleted_at is None  # pas visible : rien ne se passe
    colleague = make_user(capabilities=["clients.edit"])
    client.force_login(colleague)
    garage = quarterly()
    assert "Supprimer la sélection" not in client.get(reverse("clients:list")).content.decode()
    response = client.post(reverse("clients:trash_put"), {"client": [garage.pk], "confirme": "oui"})
    assert response.status_code == 403
    assert client.get(reverse("clients:trash")).status_code == 403


def test_a_trashed_number_is_not_duplicated_silently(client, admin):
    from apps.core.models import Portfolio

    ClientFactory(enterprise_number=enterprise_number(77), name="Ancien Fictif")
    Client.objects.filter(enterprise_number=enterprise_number(77)).update(
        deleted_at="2026-10-01T10:00Z"
    )
    portfolio = Portfolio.objects.get(name="Cabinet").pk
    page = client.post(reverse("clients:create"), form_data(portfolio=portfolio)).content.decode()
    assert "dans la corbeille" in page
