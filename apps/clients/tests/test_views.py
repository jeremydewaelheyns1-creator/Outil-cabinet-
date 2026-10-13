"""Écrans clients : droits, journalisation, formulaires."""

import pytest
from django.urls import reverse

from apps.clients.models import Client, Relation
from apps.core.models import AccessLog, Event
from apps.core.testing.factories import ClientFactory, PersonFactory, PortfolioFactory
from apps.core.testing.numbers import enterprise_number, national_number

pytestmark = pytest.mark.django_db


def test_list_and_live_search(web):
    ClientFactory(name="Garage Fictif")
    ClientFactory(name="Boucherie Fictive")
    response = web.get(reverse("clients:list"), {"q": "garage"})
    html = response.content.decode()
    assert "Garage Fictif" in html and "Boucherie" not in html
    partial = web.get(
        reverse("clients:list"), {"q": "garage"}, HTTP_HX_REQUEST="true", HTTP_HX_TARGET="resultats"
    )
    assert "<html" not in partial.content.decode()
    assert "Garage Fictif" in partial.content.decode()


def test_private_client_is_invisible_to_non_members(web):
    secret = ClientFactory(portfolio=PortfolioFactory(is_private=True), name="Dossier Privé")
    assert web.get(reverse("clients:detail", args=[secret.pk])).status_code == 404
    assert (
        "Dossier Privé" not in web.get(reverse("clients:list"), {"statut": "tous"}).content.decode()
    )


def test_viewing_a_client_is_logged(web, user):
    client = ClientFactory()
    assert web.get(reverse("clients:detail", args=[client.pk])).status_code == 200
    entry = AccessLog.objects.get(action=AccessLog.Action.VIEW)
    assert entry.user == user and entry.object_id == str(client.pk)


def test_national_number_is_masked_and_reveal_requires_capability(web, make_user, client):
    number = national_number(7)
    person = PersonFactory(national_number=number)
    html = web.get(reverse("clients:detail", args=[person.pk])).content.decode()
    assert number not in html
    assert "85.07.30-•••.••" in html
    assert web.post(reverse("clients:reveal_nn", args=[person.pk])).status_code == 403

    manager = make_user(capabilities=["clients.edit", "clients.sensitive"])
    client.force_login(manager)
    response = client.post(reverse("clients:reveal_nn", args=[person.pk]))
    assert response.status_code == 200
    assert number[:2] in response.content.decode()
    assert AccessLog.objects.filter(action=AccessLog.Action.REVEAL, user=manager).exists()


def form_data(**overrides):
    data = {
        "kind": "company",
        "status": "active",
        "portfolio": "",
        "language": "fr",
        "name": "Nouvelle Société Fictive",
        "legal_form": "SRL",
        "enterprise_number": f"BE {enterprise_number(77)}",
        "country": "BE",
    }
    data.update(overrides)
    return data


def test_create_client_normalizes_number_and_emits_event(web, django_capture_on_commit_callbacks):
    from apps.core.models import Portfolio

    data = form_data(portfolio=Portfolio.objects.get(name="Cabinet").pk)
    with django_capture_on_commit_callbacks(execute=True):
        response = web.post(reverse("clients:create"), data)
    client = Client.objects.get(name="Nouvelle Société Fictive")
    assert response.status_code == 302 and response.url == client.get_absolute_url()
    assert client.enterprise_number == enterprise_number(77)
    assert Event.objects.filter(type="client.created", subject_id=str(client.pk)).exists()
    assert AccessLog.objects.filter(action=AccessLog.Action.CREATE).exists()


def test_create_rejects_invalid_and_duplicate_numbers(web):
    from apps.core.models import Portfolio

    portfolio = Portfolio.objects.get(name="Cabinet").pk
    response = web.post(
        reverse("clients:create"), form_data(portfolio=portfolio, enterprise_number="0123.456.789")
    )
    assert "Numéro d&#x27;entreprise invalide" in response.content.decode()
    ClientFactory(enterprise_number=enterprise_number(77))
    response = web.post(reverse("clients:create"), form_data(portfolio=portfolio))
    assert response.status_code == 200
    assert Client.objects.filter(enterprise_number=enterprise_number(77)).count() == 1


def test_editing_requires_capability(make_user, client):
    reader = make_user()
    client.force_login(reader)
    target = ClientFactory()
    assert client.get(reverse("clients:edit", args=[target.pk])).status_code == 403
    assert client.get(reverse("clients:create")).status_code == 403


def test_national_number_field_only_for_sensitive_profile(web, make_user, client):
    person = PersonFactory()
    assert (
        "new_national_number"
        not in web.get(reverse("clients:edit", args=[person.pk])).content.decode()
    )
    manager = make_user(capabilities=["clients.edit", "clients.sensitive"])
    client.force_login(manager)
    data = {
        "kind": "person", "status": "active", "portfolio": person.portfolio_id,
        "language": "fr", "name": person.name, "first_name": "Marie", "country": "BE",
        "new_national_number": national_number(9),
    }  # fmt: skip
    response = client.post(reverse("clients:edit", args=[person.pk]), data)
    assert response.status_code == 302
    person.refresh_from_db()
    assert person.national_number == national_number(9)
    log = AccessLog.objects.filter(action=AccessLog.Action.UPDATE).latest("at")
    assert "national_number" in log.details["champs"]
    assert national_number(9) not in str(log.details)


def test_company_cannot_receive_national_number(make_user, client):
    company = ClientFactory()
    manager = make_user(capabilities=["clients.edit", "clients.sensitive"])
    client.force_login(manager)
    data = {
        "kind": "company", "status": "active", "portfolio": company.portfolio_id,
        "language": "fr", "name": company.name, "country": "BE",
        "new_national_number": national_number(11),
    }  # fmt: skip
    response = client.post(reverse("clients:edit", args=[company.pk]), data)
    assert response.status_code == 200
    assert "ne concerne que les personnes" in response.content.decode()


def test_add_shareholder_relation(web):
    company, person = ClientFactory(), PersonFactory(name="Actionnaire")
    url = reverse("clients:relation_add", args=[company.pk])
    picker = web.get(reverse("clients:picker"), {"q": "actionn", "exclure": company.pk})
    assert "Actionnaire" in picker.content.decode()
    response = web.post(url, {"other": person.pk, "role": "shareholder", "share_percentage": "60"})
    assert response.status_code == 302
    relation = Relation.objects.get()
    assert relation.entity == company and relation.person == person
    detail = web.get(reverse("clients:detail", args=[company.pk])).content.decode()
    assert "Actionnaire" in detail
    assert "Bénéficiaires effectifs" in detail


def test_add_mandate_from_person_side(web):
    company, person = ClientFactory(name="Société Gérée"), PersonFactory()
    response = web.post(
        reverse("clients:relation_add", args=[person.pk]),
        {"other": company.pk, "role": "manager", "sens": "mandat"},
    )
    assert response.status_code == 302
    relation = Relation.objects.get()
    assert relation.person == person and relation.entity == company


def test_contacts_and_team(web, user):
    company = ClientFactory()
    web.post(
        reverse("clients:contact_add", args=[company.pk]),
        {"kind": "email", "value": "Compta@Fictif.TEST", "is_primary": "on"},
    )
    assert company.contacts.get().value == "compta@fictif.test"
    web.post(reverse("clients:assignments", args=[company.pk]), {"manager": user.pk})
    assert company.assignments.get().user == user
    home = web.get(reverse("core:home")).content.decode()
    assert company.name in home


def test_export_is_logged_and_requires_capability(web, make_user, client):
    ClientFactory()
    assert web.get(reverse("clients:export")).status_code == 403
    exporter = make_user(capabilities=["data.export"])
    client.force_login(exporter)
    response = client.get(reverse("clients:export"))
    assert response.status_code == 200
    assert response["Content-Type"].startswith("application/vnd.openxmlformats")
    assert AccessLog.objects.filter(action=AccessLog.Action.EXPORT).exists()


def test_history_page_masks_national_number(make_user, client):
    manager = make_user(capabilities=["clients.edit", "clients.sensitive"])
    person = PersonFactory(national_number=national_number(12))
    person.national_number = national_number(13)
    person.save()
    client.force_login(manager)
    html = client.get(reverse("clients:history", args=[person.pk])).content.decode()
    assert national_number(12) not in html and national_number(13) not in html
    assert "•••" in html


def test_demo_command_creates_fictional_data_once():
    from django.core.management import CommandError, call_command

    call_command("demo", stdout=__import__("io").StringIO())
    assert Client.objects.filter(reference="D001").exists()
    with pytest.raises(CommandError):
        call_command("demo")
