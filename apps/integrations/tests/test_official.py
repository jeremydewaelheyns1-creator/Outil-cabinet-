"""Sites officiels (BCE, Moniteur, BNB) avec des pages et réponses fictives, sans réseau."""

from datetime import date, timedelta

import httpx
import pytest
from django.urls import reverse

from apps.clients.models import Client, Relation
from apps.clients.services.alerts import dossier_alerts
from apps.core.models import Event
from apps.core.testing.factories import ClientFactory, PersonFactory, PortfolioFactory
from apps.integrations import official
from apps.integrations.models import OfficialSnapshot
from apps.integrations.official_parsers import parse_kbo_functions, parse_moniteur

pytestmark = pytest.mark.django_db
Source = OfficialSnapshot.Source

# Page fictive inspirée de la mise en page de la BCE publique (tableau, intitulés en h2).
KBO_PAGE = """
<html><body><table>
<tr><td colspan="3"><h2>Généralités</h2></td></tr>
<tr><td class="QL">Numéro d'entreprise:</td><td class="QL">0123.456.749</td></tr>
<tr><td colspan="3"><h2>Fonctions</h2></td></tr>
<tr><td colspan="3"><table id="toonfctie">
  <tr><td class="RL">Gérant</td><td class="RL">Fictif ,&nbsp;Albert </td>
      <td class="RL"><span class="upd">Depuis le 1er mars 2019</span></td></tr>
  <tr><td class="RL">Administrateur</td>
      <td class="RL"><a href="toonondernemingps.html?ondernemingsnummer=0987654394">0987.654.394</a>
      Holding Imaginaire</td><td class="RL">Depuis le 15 août 2021</td></tr>
</table></td></tr>
<tr><td colspan="3"><h2>Capacités entrepreneuriales</h2></td></tr>
<tr><td class="QL">Gestion de base</td><td>Oui</td></tr>
</table></body></html>
"""

MONITEUR_PAGE = """
<html><body><div class="list">
<div class="list-item"><p>SOCIETE FICTIVE</p><p>Rue Imaginaire 1, 5000 Namur</p>
<p>0123.456.749</p><p>DEMISSIONS, NOMINATIONS</p><p>{recent} / 0123456</p>
<a href="/tsv_pdf/2026/10/01/26123456.pdf">Image</a></div>
<div class="list-item"><p>SOCIETE FICTIVE</p><p>0123.456.749</p>
<p>RUBRIQUE CONSTITUTION (NOUVELLE PERSONNE MORALE)</p><p>2019-02-20 / 0034567</p>
<a href="/tsv_pdf/2019/02/20/19034567.pdf">Image</a></div>
</div></body></html>
"""


def recent_day() -> str:
    return (date.today() - timedelta(days=5)).isoformat()


def site(routes: dict[str, httpx.Response]) -> httpx.Client:
    def handler(request: httpx.Request) -> httpx.Response:
        for host, response in routes.items():
            if request.url.host == host:
                return response
        return httpx.Response(404)

    return httpx.Client(transport=httpx.MockTransport(handler))


def company() -> Client:
    return ClientFactory(enterprise_number="0123456749")


# --- Lecture des pages ----------------------------------------------------------------------


def test_kbo_functions_are_read():
    functions = parse_kbo_functions(KBO_PAGE)
    assert functions is not None
    manager, director = functions
    assert (manager.role, manager.name, manager.first_name, manager.since) == (
        "Gérant",
        "Fictif",
        "Albert",
        "2019-03-01",
    )
    assert director.enterprise_number == "0987654394"
    assert director.name == "Holding Imaginaire"
    assert director.since == "2021-08-15"


def test_unknown_page_is_reported_unreadable_not_empty():
    assert parse_kbo_functions("<html><body>Vérification humaine</body></html>") is None
    assert parse_moniteur("<html><body>Erreur</body></html>", "https://x.invalid/") is None


def test_moniteur_publications_are_read():
    publications = parse_moniteur(
        MONITEUR_PAGE.format(recent="2026-10-01"), "https://moniteur.invalid/cgi_tsv/list.pl"
    )
    assert publications is not None
    latest, first = publications
    assert latest.published_on == "2026-10-01"
    assert latest.subject == "DEMISSIONS, NOMINATIONS"
    assert latest.tags == ("Démission", "Nomination")
    assert latest.pdf_url == "https://moniteur.invalid/tsv_pdf/2026/10/01/26123456.pdf"
    assert first.tags == ("Constitution",)


# --- Consultation et relevés ----------------------------------------------------------------


def test_refresh_records_snapshot_and_signals_changes():
    client = company()
    first = official.refresh(
        client, Source.KBO, http=site({"kbo.invalid": httpx.Response(200, text=KBO_PAGE)})
    )
    assert first.ok and len(first.items) == 2
    assert not Event.objects.filter(type="official.changed").exists()  # premier relevé
    page = KBO_PAGE.replace("Fictif ,&nbsp;Albert", "Nouveau ,&nbsp;Bernard")
    official.refresh(client, Source.KBO, http=site({"kbo.invalid": httpx.Response(200, text=page)}))
    assert Event.objects.filter(type="official.changed", payload__source="kbo").exists()


def test_unreachable_site_keeps_previous_data():
    client = company()
    official.refresh(
        client, Source.KBO, http=site({"kbo.invalid": httpx.Response(200, text=KBO_PAGE)})
    )
    failed = official.refresh(client, Source.KBO, http=site({"kbo.invalid": httpx.Response(503)}))
    assert failed.status == OfficialSnapshot.Status.UNAVAILABLE
    assert official.latest(client, Source.KBO, ok_only=True).items


def test_nbb_without_key_is_not_configured(settings):
    settings.NBB_CBSO_KEY = ""
    snapshot = official.refresh(company(), Source.NBB, http=site({}))
    assert snapshot.status == OfficialSnapshot.Status.NOT_CONFIGURED


def test_nbb_filings_are_read_with_the_official_api(settings):
    settings.NBB_CBSO_KEY = "cle-fictive"
    seen = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["path"] = request.url.path
        seen["key"] = request.headers.get("NBB-CBSO-Subscription-Key")
        return httpx.Response(200, json=[
            {"ReferenceNumber": "2025-00000001", "DepositDate": "2025-07-20",
             "ExerciseDates": {"startDate": "2024-01-01", "endDate": "2024-12-31"},
             "ModelType": "m01-f", "DepositType": "Initial", "GeneralAssemblyDate": "2025-06-10"},
        ])  # fmt: skip

    snapshot = official.refresh(
        company(), Source.NBB, http=httpx.Client(transport=httpx.MockTransport(handler))
    )
    assert seen == {"path": "/authentic/legalEntity/0123456749/references", "key": "cle-fictive"}
    assert snapshot.items[0]["exercise_end"] == "2024-12-31"


def test_periodic_refresh_is_off_in_tests_and_limited(settings, monkeypatch):
    assert official.refresh_due() == 0
    settings.OFFICIAL_AUTO_REFRESH = True
    calls = []
    monkeypatch.setattr(official, "refresh_all", lambda client: calls.append(client.pk))
    for _ in range(3):
        ClientFactory()
    PersonFactory()
    assert official.refresh_due(limit=2) == 2
    assert len(calls) == 2


def test_only_last_snapshots_are_kept():
    client = company()
    for _ in range(official.KEEP + 3):
        official.refresh(client, Source.KBO, http=site({}))
    assert client.official_snapshots.count() == official.KEEP


# --- Écrans --------------------------------------------------------------------------------


def snapshot(client: Client, source: str, items: list[dict]) -> OfficialSnapshot:
    return OfficialSnapshot.objects.create(
        client=client, source=source, status=OfficialSnapshot.Status.OK, items=items
    )


FUNCTION = {"role": "Gérant", "name": "Fictif", "first_name": "Albert", "since": "2019-03-01",
            "enterprise_number": ""}  # fmt: skip


def test_bce_functions_are_compared_to_relations(web):
    client = company()
    snapshot(client, Source.KBO, [FUNCTION])
    html = web.get(reverse("clients:public_data", args=[client.pk])).content.decode()
    assert "Ajouter aux relations" in html
    assert any("absents des relations" in a.message for a in dossier_alerts(client, None))

    person = PersonFactory(name="Fictif", first_name="Albert")
    Relation.objects.create(entity=client, person=person, role="shareholder")
    html = web.get(reverse("clients:public_data", args=[client.pk])).content.decode()
    assert "Ajouter aux relations" in html  # actionnaire, pas encore gérant
    Relation.objects.create(entity=client, person=person, role="manager")
    html = web.get(reverse("clients:public_data", args=[client.pk])).content.decode()
    assert "✓ dans les relations" in html


def test_adding_a_bce_function_creates_the_relation(web):
    client = company()
    snapshot(client, Source.KBO, [FUNCTION])
    response = web.post(reverse("clients:official_function_add", args=[client.pk, 0]))
    assert response.status_code == 302
    relation = Relation.objects.get(entity=client)
    assert relation.role == Relation.Role.MANAGER
    assert relation.start_date == date(2019, 3, 1)
    assert relation.person.display_name == "Fictif Albert"
    assert relation.person.status == Client.Status.PROSPECT
    # Une seconde fois : rien de plus (déjà dans les relations).
    web.post(reverse("clients:official_function_add", args=[client.pk, 0]))
    assert Relation.objects.filter(entity=client).count() == 1


def test_adding_reuses_an_existing_record_but_never_a_private_one(web):
    client = company()
    hidden = ClientFactory(
        enterprise_number="0987654394", portfolio=PortfolioFactory(is_private=True)
    )
    item = {**FUNCTION, "name": "Holding Imaginaire", "first_name": "",
            "enterprise_number": hidden.enterprise_number, "role": "Administrateur"}  # fmt: skip
    snapshot(client, Source.KBO, [item])
    web.post(reverse("clients:official_function_add", args=[client.pk, 0]))
    assert not Relation.objects.filter(entity=client).exists()


def test_adding_requires_edit_right(client, make_user):
    client.force_login(make_user())
    web = client
    client = company()
    snapshot(client, Source.KBO, [FUNCTION])
    response = web.post(reverse("clients:official_function_add", args=[client.pk, 0]))
    assert response.status_code == 403
    assert not Relation.objects.exists()


def test_moniteur_tab_lists_publications_and_alerts_recent_ones(web):
    client = company()
    snapshot(client, Source.MONITEUR, [
        {"published_on": recent_day(), "number": "0123456", "subject": "DEMISSIONS, NOMINATIONS",
         "tags": ["Démission", "Nomination"], "pdf_url": "https://moniteur.invalid/a.pdf"},
    ])  # fmt: skip
    html = web.get(reverse("clients:moniteur", args=[client.pk])).content.decode()
    assert "DEMISSIONS, NOMINATIONS" in html
    assert "https://moniteur.invalid/a.pdf" in html
    assert "Ouvrir au Moniteur belge" in html
    messages = [a.message for a in dossier_alerts(client, None)]
    assert any(m.startswith("Publication récente au Moniteur belge") for m in messages)


def test_annual_accounts_tab_explains_missing_key(web):
    client = company()
    OfficialSnapshot.objects.create(
        client=client, source=Source.NBB, status=OfficialSnapshot.Status.NOT_CONFIGURED
    )
    html = web.get(reverse("clients:annual_accounts", args=[client.pk])).content.decode()
    assert "developer.cbso.nbb.be" in html
    assert "consult.cbso.nbb.be/consult-enterprise/0123456749" in html


def test_refresh_button_goes_back_to_the_tab(web, settings):
    client = company()
    response = web.post(reverse("clients:official_refresh", args=[client.pk, "nbb"]))
    assert response.url == reverse("clients:annual_accounts", args=[client.pk])
    assert (
        web.post(reverse("clients:official_refresh", args=[client.pk, "autre"])).status_code == 404
    )


def test_persons_have_no_official_tabs(web):
    person = PersonFactory()
    html = web.get(reverse("clients:identity", args=[person.pk])).content.decode()
    assert reverse("clients:moniteur", args=[person.pk]) not in html


def test_adding_reuses_the_existing_person_record(web):
    client = company()
    person = PersonFactory(name="Fictif", first_name="Albert")
    Relation.objects.create(entity=client, person=person, role="shareholder")
    snapshot(client, Source.KBO, [FUNCTION])
    web.post(reverse("clients:official_function_add", args=[client.pk, 0]))
    assert Relation.objects.get(entity=client, role="manager").person == person
    assert Client.objects.filter(name="Fictif").count() == 1


def test_moniteur_links_are_web_links_only():
    page = '<p>X</p><a href="javascript:alert(1)//tsv_pdf/2020/01/01/1.pdf">Image</a>'
    assert parse_moniteur(page, "https://moniteur.invalid/list.pl") == []
