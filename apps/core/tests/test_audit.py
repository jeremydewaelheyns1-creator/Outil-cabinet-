"""Journal des consultations : inaltérable, adresse IP fiable."""

import pytest
from django.db import DatabaseError, connection, transaction
from django.test import RequestFactory, override_settings

from apps.core.audit import client_ip, log_access
from apps.core.models import AccessLog

pytestmark = pytest.mark.django_db


def make_entry() -> AccessLog:
    return log_access(None, AccessLog.Action.VIEW, object_type="test", object_repr="essai")


def test_entry_cannot_be_modified_through_django():
    entry = make_entry()
    entry.object_repr = "falsifié"
    with pytest.raises(PermissionError):
        entry.save()
    with pytest.raises(PermissionError):
        entry.delete()


def test_entry_cannot_be_modified_in_database():
    entry = make_entry()
    with pytest.raises(DatabaseError), transaction.atomic():
        AccessLog.objects.filter(pk=entry.pk).update(object_repr="falsifié")
    with pytest.raises(DatabaseError), transaction.atomic():
        AccessLog.objects.filter(pk=entry.pk)._raw_delete(connection.alias)
    assert AccessLog.objects.get(pk=entry.pk).object_repr == "essai"


def test_legal_purge_must_be_explicitly_enabled():
    entry = make_entry()
    with transaction.atomic():
        with connection.cursor() as cursor:
            cursor.execute("SET LOCAL app.allow_audit_purge = 'on'")
        AccessLog.objects.filter(pk=entry.pk)._raw_delete(connection.alias)
    assert not AccessLog.objects.filter(pk=entry.pk).exists()


@override_settings(TRUSTED_PROXY_COUNT=0)
def test_ip_without_proxy_ignores_forwarded_header():
    request = RequestFactory().get("/", HTTP_X_FORWARDED_FOR="6.6.6.6", REMOTE_ADDR="10.0.0.1")
    assert client_ip(request) == "10.0.0.1"


@override_settings(TRUSTED_PROXY_COUNT=1)
def test_ip_behind_one_proxy_uses_last_entry_not_spoofed_first():
    request = RequestFactory().get(
        "/", HTTP_X_FORWARDED_FOR="6.6.6.6, 81.82.83.84", REMOTE_ADDR="169.254.1.1"
    )
    assert client_ip(request) == "81.82.83.84"


def test_access_log_cannot_be_truncated():
    make_entry()
    with pytest.raises(DatabaseError), transaction.atomic(), connection.cursor() as cursor:
        cursor.execute("TRUNCATE core_accesslog")
    assert AccessLog.objects.exists()
