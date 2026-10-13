"""Import des archives BCE et exploitation de la copie (données fictives)."""

import pytest
from django.urls import reverse

from apps.bce import services
from apps.bce.models import Activity, Denomination, Enterprise, ImportRun
from apps.bce.opendata import OpenDataError, import_archive
from apps.clients.models import Client
from apps.core.models import Event
from apps.core.testing.factories import ClientFactory
from apps.core.testing.numbers import enterprise_number

from .archives import build, company_rows, dotted, merge

pytestmark = pytest.mark.django_db

RESTO = enterprise_number(101)
ASBL = enterprise_number(102)


@pytest.fixture
def full_import(tmp_path):
    tables = merge(
        company_rows(RESTO, "Le Bistrot Fictif"),
        company_rows(ASBL, "Les Amis Fictifs", form="017"),
        # Unité d'établissement : doit être ignorée.
        {"denomination": [["2.123.456.789", "1", "001", "Établissement"]]},
    )
    return import_archive(build(tmp_path / "full.zip", kind="full", number=140, tables=tables))


def test_full_import_loads_only_useful_rows(full_import):
    assert full_import.status == ImportRun.Status.SUCCESS
    assert Enterprise.objects.count() == 2
    assert not Denomination.objects.filter(name="Établissement").exists()
    # Seules les activités principales sont gardées.
    assert Activity.objects.filter(entity_number=RESTO).count() == 2


def test_lookup_builds_a_readable_record(full_import):
    record = services.lookup(RESTO)
    assert record is not None
    assert record.name == "Le Bistrot Fictif"
    assert record.legal_form == "SRL"
    assert record.address is not None and record.address.city == "Namur"
    assert record.address.box == "3"
    assert [(a.code, a.version) for a in record.activities] == [("56111", "2025")]
    assert record.activities[0].label == "Restauration à service complet"
    assert record.client_kind == Client.Kind.COMPANY
    assert services.lookup(ASBL).client_kind == Client.Kind.NONPROFIT
    assert services.lookup(enterprise_number(999)) is None


def test_search_by_name_and_number(full_import, user):
    assert [h.number for h in services.search("bistrot fictif", user)] == [RESTO]
    assert [h.number for h in services.search(dotted(RESTO), user)] == [RESTO]
    assert [h.number for h in services.search(RESTO[1:], user)] == [RESTO]  # 9 chiffres
    assert services.search("ab", user) == []


def test_search_does_not_link_to_private_clients(full_import, user):
    from apps.core.testing.factories import PortfolioFactory

    ClientFactory(enterprise_number=RESTO, portfolio=PortfolioFactory(is_private=True))
    hit = services.search("bistrot", user)[0]
    assert hit.registered and hit.client_id is None


def test_full_import_resyncs_clients_out_of_date(
    full_import, tmp_path, django_capture_on_commit_callbacks
):
    client = ClientFactory(enterprise_number=RESTO, bce_status="AC", bce_juridical_situation="")
    gone = ClientFactory(enterprise_number=ASBL, bce_status="AC")
    tables = company_rows(RESTO, "Le Bistrot Fictif", situation="012")
    with django_capture_on_commit_callbacks(execute=True):
        run = import_archive(build(tmp_path / "f2.zip", kind="full", number=141, tables=tables))
    assert run.changed_enterprises == 2
    client.refresh_from_db()
    gone.refresh_from_db()
    assert client.bce_juridical_situation == "Ouverture de faillite"
    assert gone.bce_status == "absent"
    history_count = client.history.count()
    services.sync_public_fields(client, services.lookup(RESTO))
    assert client.history.count() == history_count  # rien n'a changé : pas d'historique


def test_new_client_is_completed_without_overwriting(
    full_import, django_capture_on_commit_callbacks
):
    with django_capture_on_commit_callbacks(execute=True):
        client = ClientFactory(enterprise_number=RESTO, name="Nom saisi", street="", city="")
        from apps.core import events

        events.emit("client.created", subject=client)
    client.refresh_from_db()
    assert client.name == "Nom saisi"  # jamais écrasé
    assert client.street == "Rue Fictive" and client.city == "Namur"
    assert client.nace_codes[0]["code"] == "56111"
    assert client.bce_status == "AC"
    assert {c.value for c in client.contacts.all()} == {"info@fictif.test", "081 00 00 00"}
    differences = services.differences(client, services.lookup(RESTO))
    assert [d.field for d in differences] == ["name"]


def test_update_replaces_changed_enterprises_and_notifies_clients(
    full_import, tmp_path, django_capture_on_commit_callbacks
):
    client = ClientFactory(enterprise_number=RESTO)
    tables = company_rows(RESTO, "Le Bistrot Fictif", city="Liège", situation="012")
    update = build(
        tmp_path / "update.zip",
        kind="update",
        number=141,
        tables=tables,
        deletes={name: [RESTO] for name in tables},
    )
    with django_capture_on_commit_callbacks(execute=True):
        run = import_archive(update)
    assert run.changed_enterprises == 1
    record = services.lookup(RESTO)
    assert record.address.city == "Liège"
    assert record.juridical_situation_label == "Ouverture de faillite"
    assert Denomination.objects.filter(entity_number=RESTO).count() == 2  # pas de doublon
    event = Event.objects.get(type="bce.enterprise_changed")
    assert event.subject_id == str(client.pk)
    client.refresh_from_db()
    assert client.bce_juridical_situation == "Ouverture de faillite"


def test_update_already_applied_or_without_full_is_refused(tmp_path):
    update = build(tmp_path / "u.zip", kind="update", number=5, tables={})
    with pytest.raises(OpenDataError, match="export complet"):
        import_archive(update)
    import_archive(build(tmp_path / "f.zip", kind="full", number=10, tables={}))
    with pytest.raises(OpenDataError, match="déjà appliquée"):
        import_archive(update)


def test_gap_in_updates_is_reported(tmp_path):
    import_archive(build(tmp_path / "f.zip", kind="full", number=10, tables={}))
    run = import_archive(build(tmp_path / "u.zip", kind="update", number=13, tables={}))
    assert "manquantes" in run.notes


def test_failed_import_keeps_previous_data(full_import, tmp_path):
    import zipfile

    source = build(tmp_path / "source.zip", kind="full", number=150, tables={})
    broken = tmp_path / "broken.zip"
    with zipfile.ZipFile(source) as original, zipfile.ZipFile(broken, "w") as copy:
        for name in original.namelist():
            content = original.read(name)
            if name == "enterprise.csv":
                content = b"EnterpriseNumber,Status\n0200.000.000,AC\n"
            copy.writestr(name, content)
    with pytest.raises(Exception):  # noqa: B017 (colonne manquante)
        import_archive(broken)
    assert Enterprise.objects.count() == 2
    assert ImportRun.objects.filter(status=ImportRun.Status.FAILED).count() == 1


def test_not_a_bce_archive(tmp_path):
    path = tmp_path / "x.zip"
    path.write_bytes(b"pas un zip")
    with pytest.raises(OpenDataError):
        import_archive(path)


def test_search_view_and_prefilled_creation(full_import, web):
    response = web.get(reverse("bce:search"), {"q": "bistrot"})
    assert "Le Bistrot Fictif" in response.content.decode()
    response = web.get(reverse("clients:create"), {"bce": RESTO})
    html = response.content.decode()
    assert 'value="Le Bistrot Fictif"' in html
    assert 'value="Rue Fictive"' in html


def test_import_command(tmp_path, capsys):
    from django.core.management import call_command

    full = build(tmp_path / "f.zip", kind="full", number=20, tables=company_rows(RESTO, "X"))
    update = build(tmp_path / "u.zip", kind="update", number=21, tables={})
    call_command("import_bce", str(update), str(full))  # remis dans l'ordre des numéros
    assert ImportRun.objects.filter(status=ImportRun.Status.SUCCESS).count() == 2
