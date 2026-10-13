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
    # Sur l'accueil, le dossier reste choisi dans le sélecteur du haut, sans ses onglets.
    html = web.get(reverse("core:home")).content.decode()
    assert "Dossier Actif Fictif" in html
    assert 'class="tabs"' not in html


def test_inside_a_dossier_only_the_dossier_is_shown(web):
    client = ClientFactory()
    html = web.get(reverse("clients:identity", args=[client.pk])).content.decode()
    assert 'class="sidebar"' not in html  # pas de menu du cabinet
    assert "⌂ Accueil" in html
    for label in ("Synthèse", "Fiche", "Travail", "Documents et conformité", "Facturation"):
        assert label in html
    # Sous-onglets de « Fiche ».
    assert reverse("clients:relations", args=[client.pk]) in html
    assert reverse("clients:public_data", args=[client.pk]) in html


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


def test_upcoming_tab_describes_what_is_coming(web):
    client = ClientFactory()
    response = web.get(reverse("clients:upcoming", args=[client.pk, "documents"]))
    html = response.content.decode()
    assert response.status_code == 200
    assert "Pièces d&#x27;identité" in html or "Pièces d'identité" in html
    assert "aria-current" in html
    assert web.get(reverse("clients:upcoming", args=[client.pk, "inconnu"])).status_code == 404


def test_header_lists_relations_clickable_in_both_directions(web):
    company = ClientFactory(name="Société Fictive")
    manager = PersonFactory(name="Gérante", first_name="Anne")
    Relation.objects.create(entity=company, person=manager, role="manager")
    html = web.get(reverse("clients:identity", args=[company.pk])).content.decode()
    assert 'class="head-relations"' in html
    assert reverse("clients:open", args=[manager.pk]) + "?rubrique=identity" in html
    # Depuis la personne, la société apparaît (« … de »).
    html = web.get(reverse("clients:detail", args=[manager.pk])).content.decode()
    assert reverse("clients:open", args=[company.pk]) in html
    assert "Société Fictive" in html


def test_header_relations_hide_private_clients(web):
    company = ClientFactory()
    hidden = PersonFactory(name="Cachée Fictive", portfolio=PortfolioFactory(is_private=True))
    Relation.objects.create(entity=company, person=hidden, role="manager")
    html = web.get(reverse("clients:detail", args=[company.pk])).content.decode()
    assert reverse("clients:open", args=[hidden.pk]) not in html


def test_header_relations_are_limited():
    from apps.clients.dossier import header_relations
    from apps.core.testing.factories import UserFactory

    company = ClientFactory()
    for _ in range(10):
        Relation.objects.create(entity=company, person=PersonFactory(), role="shareholder")
    links, more = header_relations(company, UserFactory(), limit=8)
    assert (len(links), more) == (8, 2)


def test_type_icons_distinguish_person_and_company(web):
    company, person = ClientFactory(), PersonFactory()
    assert "kind-company" in web.get(reverse("clients:detail", args=[company.pk])).content.decode()
    assert "kind-person" in web.get(reverse("clients:detail", args=[person.pk])).content.decode()


def test_identity_page_links_to_public_sites(web):
    company = ClientFactory()
    html = web.get(reverse("clients:identity", args=[company.pk])).content.decode()
    assert (
        f"kbopub.economie.fgov.be/kbopub/toonondernemingps.html?ondernemingsnummer={company.enterprise_number}"
        in html
    )
    assert f"consult.cbso.nbb.be/consult-enterprise/{company.enterprise_number}" in html
    assert "Ajouté le" in html
    person = PersonFactory()
    html = web.get(reverse("clients:identity", args=[person.pk])).content.decode()
    assert "kbopub" not in html
