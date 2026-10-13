"""Travaux de fond du socle (exécutés par le worker procrastinate)."""

from procrastinate.contrib.django import app

from . import events


@app.task(name="core.process_event", queue="events", retry=3)
def process_event(event_id: int) -> None:
    events.process(event_id)


@app.periodic(cron="*/5 * * * *")
@app.task(name="core.retry_pending_events", queue="events")
def retry_pending_events(timestamp: int) -> None:
    events.retry_pending()
