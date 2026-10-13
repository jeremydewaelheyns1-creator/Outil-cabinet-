"""Journal d'événements : chaque traitement s'exécute une seule fois, les échecs sont rejoués."""

import pytest

from apps.core import events
from apps.core.models import Event, EventHandling

pytestmark = pytest.mark.django_db

calls: list[str] = []


@pytest.fixture(autouse=True)
def isolated_registry(monkeypatch):
    calls.clear()
    monkeypatch.setattr(events, "_handlers", type(events._handlers)(list))


def register(name: str, fail_times: int = 0):
    state = {"failures": 0}

    def handler(event: Event) -> None:
        calls.append(name)
        if state["failures"] < fail_times:
            state["failures"] += 1
            raise RuntimeError("panne simulée")

    handler.__qualname__ = name
    events.on("test.fait")(handler)


def emit_and_process(**kwargs) -> Event:
    event = events.emit("test.fait", **kwargs)
    return events.process(event.pk)


def test_each_handler_runs_once():
    register("a")
    register("b")
    event = emit_and_process()
    assert calls == ["a", "b"]
    assert event.status == Event.Status.PROCESSED
    events.process(event.pk)
    assert calls == ["a", "b"]


def test_failed_handler_is_retried_without_rerunning_successful_ones():
    register("ok")
    register("fragile", fail_times=1)
    event = emit_and_process()
    assert event.status == Event.Status.FAILED
    failed = EventHandling.objects.get(event=event, handler__endswith="fragile")
    assert "panne simulée" in failed.last_error
    event = events.process(event.pk)
    assert event.status == Event.Status.PROCESSED
    assert calls == ["ok", "fragile", "fragile"]


def test_handler_gives_up_after_max_attempts():
    register("toujours_en_panne", fail_times=99)
    event = events.emit("test.fait")
    for _ in range(events.MAX_ATTEMPTS + 3):
        events.process(event.pk)
    assert calls.count("toujours_en_panne") == events.MAX_ATTEMPTS


def test_idempotency_key_prevents_duplicates():
    first = events.emit("test.fait", idempotency_key="mail-123")
    second = events.emit("test.fait", idempotency_key="mail-123")
    assert first.pk == second.pk
    assert Event.objects.filter(idempotency_key="mail-123").count() == 1


def test_failed_handler_does_not_undo_other_work(django_capture_on_commit_callbacks):
    from apps.core.models import Portfolio

    def creates_then_fails(event: Event) -> None:
        Portfolio.objects.create(name="créé puis annulé")
        raise RuntimeError("échec")

    creates_then_fails.__qualname__ = "creates_then_fails"
    events.on("test.fait")(creates_then_fails)
    register("independant")
    emit_and_process()
    assert not Portfolio.objects.filter(name="créé puis annulé").exists()
    assert calls == ["independant"]


def test_emit_processes_after_commit_in_eager_mode(django_capture_on_commit_callbacks):
    register("apres_commit")
    with django_capture_on_commit_callbacks(execute=True):
        events.emit("test.fait")
        assert calls == []
    assert calls == ["apres_commit"]
