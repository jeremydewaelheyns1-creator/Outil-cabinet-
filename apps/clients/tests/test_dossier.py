"""Navigation par dossier : client actif en haut de l'écran, rubriques, changement de client."""

import pytest
from django.urls import reverse

from apps.clients.dossier import SESSION_CURRENT
from apps.clients.models import Relation
from apps.clients.services.alerts import dossier_alerts
from apps.core.models import AccessLog
from apps.core.testing.factories import ClientFactory, PersonFactory, PortfolioFactory

pytestmark = pytest.mark.django_db

SECTIONS = ["detail", "identity", "relations", "ubo", "team", "public_data", "history"]


def test_opening_a_client_makes_it_the_active_dossier_everywhere(web):
    client = ClientFactory(name="Dossier Actif Fictif")
    web.get(reverse("clients:detail", args=[client.pk]))
    assert web.session[SESSION_CURRENT] == client.pk
    # Sur un écran général, le dossier reste affiché en haut et son menu à gauche.
    html = web.get(reverse("core:home")).content.decode()
    assert "Dossier Actif Fictif" in html
    assert reverse("clients:relations", args=[client.pk]) in html


@pytest.mark.parametrize("section", SECTIONS)
def test_every_section_renders_and_is_logged(web, section):
    client = ClientFactory()
    response = web.get(reverse(f"clients:{section}", args=[client.pk]))
    assert response.status_code == 200
    entry = AccessLog.objects.get(action=AccessLog.Action.VIEW)
    assert entry.details["rubrique"] == section


def test_person_sections_skip_company_only_ones(web):
    person = PersonFactory()
    html = web.get(reverse("clients:detail", args=[person.pk])).content.decode()
    assert reverse("clients:ubo", args=[person.pk]) not in html
    assert reverse("clients:identity", args=[person.pk]) in html


def test_switching_client_keeps_the_section(web):
    first, second = ClientFactory(), ClientFactory()
    web.get(reverse("clients:relations", args=[first.pk]))
    response = web.get(reverse("clients:open", args=[second.pk]), {"rubrique": "relations"})
    assert response.url == reverse("clients:relations", args=[second.pk])
    # Une rubrique inexistante pour ce type de client renvoie à la synthèse.
    person = PersonFactory()
    response = web.get(reverse("clients:open", args=[person.pk]), {"rubrique": "ubo"})
    assert response.url == reverse("clients:detail", args=[person.pk])
    response = web.get(reverse("clients:open", args=[person.pk]), {"rubrique": "../admin"})
    assert response.url == reverse("clients:detail", args=[person.pk])


def test_switcher_shows_recent_dossiers_then_search_results(web):
    a = ClientFactory(name="Alpha Fictif")
    b = ClientFactory(name="Bravo Fictif")
    ClientFactory(name="Charlie Fictif")
    web.get(reverse("clients:detail", args=[a.pk]))
    web.get(reverse("clients:detail", args=[b.pk]))
    recent = web.get(reverse("clients:switcher")).content.decode()
    assert "Alpha Fictif" in recent and "Bravo Fictif" not in recent  # dossier actif exclu
    assert "Charlie" not in recent
    found = web.get(reverse("clients:switcher"), {"q": "charlie", "rubrique": "team"})
    html = found.content.decode()
    assert "Charlie Fictif" in html and "rubrique=team" in html


def test_switcher_never_shows_private_clients(web):
    ClientFactory(name="Secret Fictif", portfolio=PortfolioFactory(is_private=True))
    html = web.get(reverse("clients:switcher"), {"q": "secret"}).content.decode()
    assert "Secret Fictif" not in html


def test_active_dossier_disappears_when_access_is_lost(web):
    portfolio = PortfolioFactory()
    client = ClientFactory(name="Dossier Retiré", portfolio=portfolio)
    web.get(reverse("clients:detail", args=[client.pk]))
    portfolio.is_private = True
    portfolio.save()
    assert "Dossier Retiré" not in web.get(reverse("core:home")).content.decode()


def test_closing_the_dossier(web):
    client = ClientFactory(name="À Fermer")
    web.get(reverse("clients:detail", args=[client.pk]))
    response = web.post(reverse("clients:close"))
    assert response.url == reverse("core:home")
    assert SESSION_CURRENT not in web.session
    assert "Choisir un client" in web.get(reverse("core:home")).content.decode()


def test_summary_lists_points_of_attention(web):
    company = ClientFactory(vat_status="", bce_juridical_situation="Ouverture de faillite")
    html = web.get(reverse("clients:detail", args=[company.pk])).content.decode()
    assert "Situation à la BCE : Ouverture de faillite" in html
    assert "Statut TVA non renseigné" in html
    assert reverse("clients:public_data", args=[company.pk]) in html


def test_alert_rules():
    company = ClientFactory(vat_status="subject", vat_periodicity="", fiscal_year_end_month=None)
    messages = {a.message for a in dossier_alerts(company, None)}
    assert "Périodicité TVA non renseignée" in messages
    assert "Date de clôture de l'exercice non renseignée" in messages
    assert "Aucune adresse e-mail" in messages
    assert "Aucun collaborateur affecté au dossier" in messages
    person = PersonFactory()
    assert "Numéro national non renseigné" in {a.message for a in dossier_alerts(person, None)}


def test_relation_links_open_the_other_dossier(web):
    company, manager = ClientFactory(), PersonFactory(name="Gérante")
    Relation.objects.create(entity=company, person=manager, role="manager")
    html = web.get(reverse("clients:detail", args=[company.pk])).content.decode()
    assert reverse("clients:detail", args=[manager.pk]) in html
