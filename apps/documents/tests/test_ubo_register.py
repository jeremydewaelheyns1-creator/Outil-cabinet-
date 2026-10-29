"""Registre UBO (MyMinfin) : fiche d'encodage, attestation, mise à jour (D-078)."""

import pytest
from django.core.files.uploadedfile import SimpleUploadedFile
from django.urls import reverse

from apps.clients.models import Relation
from apps.core.testing.factories import PersonFactory
from apps.documents import freshness, services, types
from apps.tasks.models import Task

from .test_ubo_declaration import owned_company

pytestmark = pytest.mark.django_db


def store_extract(company):
    return services.store(company, SimpleUploadedFile("a.pdf", b"%PDF-1.4 x"), title="Attestation",
                          case="ubo", doc_type="extrait_ubo")  # fmt: skip


def test_encoding_sheet_lists_what_to_type(web):
    company, marc, _ = owned_company()
    page = web.get(reverse("clients:ubo", args=[company.pk])).content.decode()
    assert "fiche d&#x27;encodage" in page or "fiche d'encodage" in page
    assert marc.display_name in page and "via Holding Fictive" in page
    assert "pas d&#x27;extrait rangé" in page or "pas d'extrait rangé" in page
    store_extract(company)
    page = web.get(reverse("clients:ubo", args=[company.pk])).content.decode()
    assert "confirmation annuelle à faire avant" in page


def test_new_shareholder_asks_to_update_the_register_within_a_month():
    company, _, _ = owned_company()
    extract = store_extract(company)
    assert extract.expires_on is not None and extract.data_fingerprint
    assert types.rows(company, "ubo")[0].level == "ok"
    newcomer = PersonFactory(name="Nouveau")
    Relation.objects.create(entity=company, person=newcomer, role="shareholder",
                            share_percentage=30)  # fmt: skip
    assert types.rows(company, "ubo")[0].level == "warning"
    freshness.follow_client(company)
    task = Task.objects.get(client=company, kind="document:maj-extrait_ubo")
    assert "registre UBO" in task.title


def test_boards_read_the_stored_result_and_events_refresh_it(django_capture_on_commit_callbacks):
    """D-080 : le tableau de conformité ne recalcule pas les bénéficiaires de chaque dossier ;
    il lit « modifié depuis », remis à jour dès qu'une relation change."""
    from django.db import connection
    from django.test.utils import CaptureQueriesContext

    from apps.core import events
    from apps.documents import compliance

    company, _, _ = owned_company()
    extract = store_extract(company)
    newcomer = PersonFactory(name="Nouveau")
    relation = Relation.objects.create(entity=company, person=newcomer, role="shareholder",
                                       share_percentage=30)  # fmt: skip
    with django_capture_on_commit_callbacks(execute=True):
        events.emit("relation.saved", subject=company, payload={"relation": relation.pk})
    extract.refresh_from_db()
    assert extract.changed_parts == ["bénéficiaires effectifs"]
    lines = " | ".join(
        line.label for line in compliance.overview(company, compliance.load([company])).lines
    )
    assert "À mettre à jour" in lines
    batch = compliance.load([company])
    with CaptureQueriesContext(connection) as ctx:
        compliance.overview(company, batch)
    assert not any("clients_relation" in q["sql"] for q in ctx.captured_queries)


def test_ubo_is_confirmed_in_one_click_once_the_extract_is_filed(web):
    """D-103 : « l'UBO s'est mis dans à confirmer et je ne peux pas le confirmer »."""
    from apps.core.models import AccessLog

    company, marc, sophie = owned_company()
    url = reverse("clients:ubo", args=[company.pk])
    assert "Oui, le registre montre ces personnes" not in web.get(url).content.decode()
    store_extract(company)
    page = web.get(url).content.decode()
    assert "Oui, le registre montre ces personnes" in page
    web.post(reverse("clients:ubo_confirm", args=[company.pk]))
    declared = Relation.objects.filter(entity=company, role=Relation.Role.BENEFICIAL_OWNER)
    assert {r.person_id for r in declared} == {marc.pk, sophie.pk}
    assert AccessLog.objects.filter(details__has_key="registre UBO confirmé").exists()
    page = web.get(url).content.decode()
    assert "conforme aux déclarations" in page
    assert "Oui, le registre montre ces personnes" not in page


def test_ubo_confirm_needs_an_extract(web):
    company, _, _ = owned_company()
    assert web.post(reverse("clients:ubo_confirm", args=[company.pk])).status_code == 404
