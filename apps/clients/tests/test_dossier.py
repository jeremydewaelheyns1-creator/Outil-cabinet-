"""Navigation par dossier : client actif en haut de l'écran, rubriques, changement de client."""

import pytest
from django.urls import reverse

from apps.clients.dossier import SESSION_CURRENT
from apps.clients.models import Relation
from apps.clients.services.alerts import dossier_alerts
from apps.core.models import AccessLog
from apps.core.testing.factories import ClientFactory, PersonFactory, PortfolioFactory

pytestmark = pytest.mark.django_db

SECTIONS = [
    "identity", "mandates", "shareholders", "ubo", "annual_accounts",
    "history",
]  # fmt: skip


def test_opening_a_client_makes_it_the_active_dossier_everywhere(web):
    client = ClientFactory(name="Dossier Actif Fictif")
    web.get(reverse("clients:detail", args=[client.pk]))
    assert web.session[SESSION_CURRENT] == client.pk
    # Sur l'accueil, le dossier reste choisi dans le sélecteur du haut, sans ses onglets.
    html = web.get(reverse("core:home")).content.decode()
    assert "Dossier Actif Fictif" in html
    assert 'class="tabs"' not in html


def test_inside_a_dossier_only_the_dossier_is_shown(web):
    client = ClientFactory(vat_status="subject")
    html = web.get(reverse("clients:identity", args=[client.pk])).content.decode()
    assert 'class="sidebar"' not in html  # pas de menu du cabinet
    assert "⌂ Accueil" in html
    assert "Synthèse" not in html  # supprimée (D-025)
    # En haut : le travail fréquent (D-026).
    urls = [reverse("clients:work", args=[client.pk, "cloture"]),
            reverse("clients:vat", args=[client.pk]),
            reverse("clients:work", args=[client.pk, "versements-anticipes"])]  # fmt: skip
    urls.append(reverse("clients:documents", args=[client.pk]))
    tabs = html[html.index('class="tabs"') :]  # l'en-tête a aussi un lien vers Documents
    positions = [tabs.index(u) for u in urls]
    assert positions == sorted(positions)  # ordre voulu par Jeremy
    assert "time-sheet" not in html
    # Chaque page à un clic depuis la fiche (D-105, D-106 : panneau allégé, liens en bas).
    for name in ("identity", "archives", "documents", "tasks", "history"):
        assert reverse(f"clients:{name}", args=[client.pk]) in html


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


def test_opening_a_dossier_always_shows_identity(web):
    first, second = ClientFactory(), ClientFactory()
    web.get(reverse("clients:shareholders", args=[first.pk]))
    response = web.get(reverse("clients:open", args=[second.pk]), {"rubrique": "shareholders"})
    assert response.url == reverse("clients:identity", args=[second.pk])
    html = web.get(reverse("clients:shareholders", args=[first.pk])).content.decode()
    assert "?rubrique=" not in html


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
    assert "Charlie Fictif" in html and "rubrique=" not in html


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


def test_opening_a_dossier_lands_on_the_fiche(web):
    company = ClientFactory()
    response = web.get(reverse("clients:detail", args=[company.pk]))
    html = response.content.decode()
    assert "Identité et coordonnées" in html
    assert AccessLog.objects.get(action=AccessLog.Action.VIEW).details["rubrique"] == "identity"
    assert company.get_absolute_url() == reverse("clients:identity", args=[company.pk])


def test_points_of_attention_are_still_computed():
    company = ClientFactory(vat_status="", bce_juridical_situation="Ouverture de faillite")
    messages = {a.message for a in dossier_alerts(company, None)}
    assert "Situation à la BCE : Ouverture de faillite" in messages
    assert "Statut TVA non renseigné" in messages


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
    html = web.get(reverse("clients:mandates", args=[company.pk])).content.decode()
    assert reverse("clients:identity", args=[manager.pk]) in html


def test_work_pages_are_placeholders_until_defined(web):
    client = ClientFactory()
    response = web.get(reverse("clients:work", args=[client.pk, "cloture"]))
    html = response.content.decode()
    assert response.status_code == 200
    assert "Page à construire" in html
    assert "aria-current" in html
    assert web.get(reverse("clients:work", args=[client.pk, "inconnu"])).status_code == 404


def test_vat_tab_only_for_vat_subject_clients(web):
    subject = ClientFactory(vat_status="subject")
    exempt = ClientFactory(vat_status="exempt")
    url = reverse("clients:vat", args=[subject.pk])
    assert url in web.get(reverse("clients:identity", args=[subject.pk])).content.decode()
    html = web.get(reverse("clients:identity", args=[exempt.pk])).content.decode()
    assert reverse("clients:vat", args=[exempt.pk]) not in html


def test_relations_are_split_by_kind_with_counts(web):
    company = ClientFactory()
    manager, owner, other = PersonFactory(name="Gérante"), PersonFactory(), PersonFactory()
    Relation.objects.create(entity=company, person=manager, role="manager")
    Relation.objects.create(entity=company, person=owner, role="shareholder", share_percentage=60)
    Relation.objects.create(entity=company, person=other, role="other")
    mandates = web.get(reverse("clients:mandates", args=[company.pk])).content.decode()
    assert "Gérante" in mandates and owner.name not in mandates.split("dossier-content")[1]
    shareholders = web.get(reverse("clients:shareholders", args=[company.pk])).content.decode()
    assert "60 %" in shareholders
    # Une personne voit les sociétés où elle a un mandat.
    html = web.get(reverse("clients:mandates", args=[manager.pk])).content.decode()
    assert company.name in html.split("dossier-content")[1]
    assert "Autres relations" not in mandates  # page supprimée (D-030)
    # L'ancienne adresse « Relations » mène aux mandataires.
    assert web.get(reverse("clients:relations", args=[company.pk])).url == reverse(
        "clients:mandates", args=[company.pk]
    )


def test_saving_a_relation_returns_to_its_page(web):
    company, person = ClientFactory(), PersonFactory()
    response = web.post(
        reverse("clients:relation_add", args=[company.pk]),
        {"other": person.pk, "role": "shareholder", "share_percentage": "10"},
    )
    assert response.url == reverse("clients:shareholders", args=[company.pk])


def test_header_lists_relations_clickable_in_both_directions(web):
    company = ClientFactory(name="Société Fictive")
    manager = PersonFactory(name="Gérante", first_name="Anne")
    Relation.objects.create(entity=company, person=manager, role="manager")
    html = web.get(reverse("clients:identity", args=[company.pk])).content.decode()
    assert 'class="head-relations"' in html
    assert reverse("clients:open", args=[manager.pk]) in html
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


def test_one_archives_entry_on_the_left(web):
    """D-105 : une seule entrée « Archives » (classeur), plus les 8 dossiers de FID-Manager."""
    company, person = ClientFactory(), PersonFactory()
    html = web.get(reverse("clients:identity", args=[company.pk])).content.decode()
    assert reverse("clients:archives", args=[company.pk]) in html
    for slug in ("legal", "isoc", "tva", "administratif", "courriels"):
        assert reverse("clients:archive", args=[company.pk, slug]) not in html
    for hidden in ("Honoraires", ">Historique<", ">Échéances<", ">Mandataires<", ">Actionnaires<"):
        assert hidden not in html.split('class="dossier-side"')[1].split("</aside>")[0]
    assert reverse("clients:archive", args=[company.pk, "factures"]) in html
    assert "Heures prestées" not in html  # réservé à l'administrateur (D-107)
    # En bas de la fiche : l'historique et les échéances restent à un clic.
    assert reverse("clients:history", args=[company.pk]) in html
    assert reverse("clients:tasks", args=[company.pk]) in html
    page = web.get(reverse("clients:archives", args=[company.pk]))
    assert page.status_code == 200 and "Aucun document archivé" in page.content.decode()
    # Les anciennes adresses mènent au bon sujet du classeur.
    old = web.get(reverse("clients:archive", args=[company.pk, "isoc"]))
    assert old.status_code == 302 and old["Location"].endswith("/archives/?sujet=isoc")
    assert web.get(reverse("clients:archive", args=[company.pk, "inconnu"])).status_code == 404
    html = web.get(reverse("clients:archives", args=[person.pk])).content.decode()
    assert "comptes déposés à la Banque Nationale" not in html  # pas pour un particulier


def test_classeur_years_then_subjects(web):
    from django.core.files.uploadedfile import SimpleUploadedFile

    from apps.documents import services

    company = ClientFactory(vat_periodicity="quarterly")
    for title, folder in (("Avertissement-extrait de rôle ISOC — exercice 2025", "isoc"),
                          ("Biztax — exercice 2026", "isoc"), ("Statuts", "legal")):  # fmt: skip
        services.store(company, SimpleUploadedFile("a.pdf", f"%PDF-1.4 {title}".encode()),
                       title=title, folder=folder)  # fmt: skip
    html = web.get(
        reverse("clients:archives", args=[company.pk]), {"sujet": "isoc"}
    ).content.decode()
    assert 'id="annee-2026"' in html and 'id="annee-2025"' in html
    assert html.index('id="annee-2026"') < html.index('id="annee-2025"')  # récente d'abord
    assert 'id="annee-2026-isoc" data-remember style="--subject: #9333ea" open' in html
    assert "Dernier : Biztax — exercice 2026" in html
    assert "Tout ouvrir" in html and "Tout fermer" in html


def test_moniteur_archive_lists_publications(web):
    from apps.integrations.models import OfficialSnapshot

    company = ClientFactory()
    OfficialSnapshot.objects.create(
        client=company, source="moniteur", status="ok",
        items=[{"published_on": "2022-06-20", "number": "1", "subject": "SIEGE SOCIAL",
                "tags": ["Siège"], "pdf_url": ""}],
    )  # fmt: skip
    html = web.get(reverse("clients:archive", args=[company.pk, "moniteur"])).content.decode()
    assert "20/06/2022" in html and "SIEGE SOCIAL" in html
    assert OfficialSnapshot.objects.count() == 1


def test_documents_tab_has_one_rectangle_per_fid_line(web):
    company = ClientFactory()
    html = web.get(reverse("clients:documents", args=[company.pk])).content.decode()
    labels = ("À recevoir", "Lettre de mission", "Cartes d", "Déclaration des bénéficiaires",
              "Identification du client", "Identification des mandataires", "Procuration",
              "Fiche de détermination du niveau de risque", ">UBO<")  # fmt: skip
    positions = [html.index(label) for label in labels]
    assert positions == sorted(positions)  # dans l'ordre de FID
    assert "badge-danger" in html and "problème" in html  # aucun UBO calculé : rouge
    # La case UBO s'ouvre sous l'onglet Documents.
    ubo_page = web.get(reverse("clients:ubo", args=[company.pk])).content.decode()
    assert 'aria-current="page">Documents<' in ubo_page
    case = web.get(reverse("clients:document_case", args=[company.pk, "fiche-risque"]))
    assert case.status_code == 200 and "Manquant" in case.content.decode()
    assert web.get(reverse("clients:document_case", args=[company.pk, "ubo"])).status_code == 404
    # Une personne : ni UBO, ni déclaration, ni mandataires.
    person = PersonFactory()
    html = web.get(reverse("clients:documents", args=[person.pk])).content.decode()
    assert "Déclaration des bénéficiaires" not in html and ">UBO<" not in html
    assert "Identification des mandataires" not in html


def test_documents_tab_gives_direct_access_to_documents(web):
    from django.core.files.uploadedfile import SimpleUploadedFile

    from apps.documents import services

    company = ClientFactory()
    doc = services.store(
        company, SimpleUploadedFile("l.pdf", b"%PDF-1.4 fictif"), title="Lettre de mission 2026",
        case="lettre-de-mission",
    )  # fmt: skip
    html = web.get(reverse("clients:documents", args=[company.pk])).content.decode()
    assert "doc-open" in html
    assert reverse("clients:document_viewer", args=[company.pk, doc.pk]) in html


def test_managers_and_shareholders_are_encoded_from_documents(web):
    """D-106 : plus d'entrée « Organisation » ; on encode depuis l'onglet Documents."""
    company = ClientFactory()
    case = reverse("clients:document_case", args=[company.pk, "identification-mandataires"])
    assert reverse("clients:mandates", args=[company.pk]) in web.get(case).content.decode()
    ubo = web.get(reverse("clients:ubo", args=[company.pk])).content.decode()
    assert reverse("clients:shareholders", args=[company.pk]) in ubo
    page = web.get(reverse("clients:mandates", args=[company.pk])).content.decode()
    assert reverse("clients:documents", args=[company.pk]) in page  # retour à Documents
