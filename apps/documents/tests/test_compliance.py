"""Tableau de conformité et demande groupée : un e-mail, un lien, tout ce qui manque (D-051)."""

import pytest
from django.urls import reverse

from apps.clients.models import Assignment
from apps.core.testing.factories import ClientFactory
from apps.documents import compliance, generation, services
from apps.documents.models import DocumentRequest
from apps.documents.tests.letter_fixture import install
from apps.documents.tests.test_client_link import link_of, photo, signature_png
from apps.documents.tests.test_documents import company_with_manager

pytestmark = pytest.mark.django_db


def prepared_company():
    company, manager = company_with_manager()
    install()  # modèle de lettre de mission du cabinet
    generation.generate(company, "lettre_mission")  # brouillon relu, prêt à signer
    return company, manager


def test_overview_lists_what_is_missing_and_what_can_be_asked():
    company, _ = prepared_company()
    found = compliance.overview(company)
    assert found.level == "danger" and found.has_email
    labels = " | ".join(line.label for line in found.lines)
    assert "Lettre de mission" in labels and "Carte d'identité — " in labels
    assert [kind for kind, _ in found.askable] == ["signature", "carte"]
    # La déclaration UBO jamais préparée n'est pas proposée : à générer et relire d'abord.
    assert not any("bénéficiaires" in label for label in found.askable_labels)


def test_one_email_one_link_for_everything(client, settings):
    settings.SITE_URL = "https://outil.example.be"
    company, _manager = prepared_company()
    bundle = compliance.ask_everything(company, None)
    assert bundle.kind == "bundle" and bundle.items.count() == 2
    assert DocumentRequest.objects.filter(kind="bundle").count() == 1
    email = bundle.emails.get()
    assert "Lettre de mission à signer" in email.body and "Carte d'identité de" in email.body
    assert all(not item.emails.exists() for item in bundle.items.all())  # un seul e-mail
    assert all(item.next_reminder_on is None for item in bundle.items.all())  # relance groupée
    # Rien d'autre à demander tant que la demande est en cours.
    assert compliance.overview(company).askable == []
    path = "/" + link_of(bundle)
    page = client.get(path).content.decode()
    assert "2 documents" in page and "Lire et signer" in page and "Déposer" in page
    card = bundle.items.get(kind="identity_card")
    card_path = "/" + link_of_item(card)
    response = client.post(card_path, {"files": [photo("r.png", "red"), photo("v.png", "blue")]})
    assert "Continuer avec les autres documents" in response.content.decode()
    assert "1 document" in client.get(path).content.decode()
    letter = bundle.items.get(kind="signature")
    data = {"signer_name": "Anne Fictif", "signature": signature_png(), "approve": "1"}
    html = client.post("/" + link_of_item(letter), data).content.decode()
    assert "signé" in html and "Continuer" not in html
    bundle.refresh_from_db()
    assert bundle.status == "received"
    assert client.get(path).status_code == 404  # tout est reçu : le lien ne sert plus


def link_of_item(item):
    return services.upload_url(item).split("://", 1)[1].split("/", 1)[1]


def test_reminder_lists_only_what_is_still_missing():
    from datetime import timedelta

    from django.utils import timezone

    company, _ = prepared_company()
    bundle = compliance.ask_everything(company, None)
    services.cancel(bundle.items.get(kind="identity_card"))
    bundle.next_reminder_on = timezone.localdate() - timedelta(days=1)
    bundle.save()
    assert services.send_due_reminders() == 1
    reminder = bundle.emails.get(kind="reminder")
    assert "Lettre de mission" in reminder.body and "Carte d'identité" not in reminder.body


def test_cancelling_the_bundle_cancels_its_items():
    company, _ = prepared_company()
    bundle = compliance.ask_everything(company, None)
    services.cancel(bundle)
    assert set(bundle.items.values_list("status", flat=True)) == {"cancelled"}


def test_board_shows_my_dossiers_and_sends_grouped_requests(web, user):
    mine, _ = prepared_company()
    Assignment.objects.create(client=mine, user=user, role=Assignment.Role.MANAGER)
    other, _ = prepared_company()
    other.name = "Autre Fictive"
    other.save()
    html = web.get(reverse("conformite:board")).content.decode()
    assert mine.display_name in html and "Autre Fictive" not in html
    assert "Autre Fictive" in web.get(reverse("conformite:board") + "?qui=tous").content.decode()
    response = web.post(reverse("conformite:ask"), {"client": [mine.pk, other.pk]})
    assert response.status_code == 302
    assert DocumentRequest.objects.filter(kind="bundle").count() == 2


def test_board_respects_visibility(web):
    from apps.clients.models import ContactPoint
    from apps.core.testing.factories import PersonFactory, PortfolioFactory

    hidden = ClientFactory(name="Dossier Privé", portfolio=PortfolioFactory(is_private=True))
    ContactPoint.objects.create(client=hidden, kind="email", value="prive@fictif.test")
    hidden.relations_as_entity.create(person=PersonFactory(), role="manager")
    assert (
        "Dossier Privé" not in web.get(reverse("conformite:board") + "?qui=tous").content.decode()
    )
    web.post(reverse("conformite:ask"), {"client": [hidden.pk]})
    assert not DocumentRequest.objects.exists()


def test_home_shows_my_compliance_counts(web, user):
    from django.core.cache import cache

    cache.clear()
    mine, _ = prepared_company()
    Assignment.objects.create(client=mine, user=user, role=Assignment.Role.MANAGER)
    html = web.get(reverse("core:today")).content.decode()
    assert "Incomplets (anti-blanchiment)" in html
    assert compliance.summary_for(user) == {"danger": 1, "warning": 0, "askable": 1}


def test_board_loaded_in_bulk_gives_the_same_result_with_few_queries(django_assert_max_num_queries):
    from datetime import date

    from apps.clients.models import Relation
    from apps.core.testing.factories import PersonFactory
    from apps.documents.models import IdentityCard

    dossiers = []
    for i in range(6):
        company, manager = prepared_company()
        partner = PersonFactory(name=f"Associé{i}")
        Relation.objects.create(entity=company, person=partner, role="shareholder")
        if i % 2:  # une carte expirée, une valable
            IdentityCard.objects.create(
                person=manager, valid_until=date(2020, 1, 1), source="manual"
            )
            IdentityCard.objects.create(
                person=partner, valid_until=date(2040, 1, 1), source="manual"
            )
        dossiers.append(company)
    services.create_bundle(dossiers[0], compliance.overview(dossiers[0]).askable, user=None)
    dossiers.append(PersonFactory(name="Particulier"))
    one_by_one = {c.pk: compliance.overview(c) for c in dossiers}
    with django_assert_max_num_queries(25):
        bulk = compliance.board(dossiers)
    assert {r.client.pk for r in bulk} == {
        pk for pk, o in one_by_one.items() if o.lines or o.pending
    }
    for row in bulk:
        alone = one_by_one[row.client.pk]
        assert [(line.label, line.level) for line in row.lines] == [
            (line.label, line.level) for line in alone.lines
        ]
        assert row.askable_labels == alone.askable_labels
        assert (row.pending, row.has_email) == (alone.pending, alone.has_email)


def test_identification_forms_follow_the_itaa_models(user):
    from django.template.loader import render_to_string

    from apps.core.testing.factories import PersonFactory
    from apps.core.testing.numbers import national_number
    from apps.documents.generation import _context

    company, manager = company_with_manager()
    html = render_to_string("documents/modeles/identification_client.html",
                            _context(company, "identification_client", None, user))  # fmt: skip
    parts = (
        "Identification client personne morale",
        "I. Client occasionnel",
        "V. Gestion du client",
        "VI. Nature et objet",
        "personne responsable de l'acceptation",
    )
    for part in parts:
        assert part in html
    person = PersonFactory(national_number=national_number(5))
    html = render_to_string("documents/modeles/identification_client.html",
                            _context(person, "identification_client", None, user))  # fmt: skip
    assert "Identification client personne physique" in html
    assert national_number(5) not in html  # jamais en clair
    context = _context(company, "identification_mandataire", manager, user)
    html = render_to_string("documents/modeles/identification_mandataire.html", context)
    assert (
        "Identification mandataire personne physique" in html
        and "IV. Pouvoirs de représentation" in html
    )
