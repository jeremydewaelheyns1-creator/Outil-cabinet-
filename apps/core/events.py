"""Journal d'événements : émettre un fait, y abonner des traitements, le traiter une seule fois.

Utilisation :

    from apps.core import events

    @events.on("client.created")
    def enrich_from_bce(event: Event) -> None:
        ...

    events.emit("client.created", subject=client, actor=request.user)

Règles (voir docs/CONVENTIONS.md) :
- un traitement doit être idempotent : il peut être relancé après une panne ;
- un traitement ne fait pas d'appel externe long lui-même : il programme un travail de fond ;
- l'événement est enregistré dans la même transaction que la modification qu'il décrit,
  et traité seulement après validation de cette transaction.
"""

from __future__ import annotations

import logging
import traceback
from collections import defaultdict
from collections.abc import Callable
from datetime import timedelta
from typing import Any

from django.conf import settings
from django.contrib.contenttypes.models import ContentType
from django.db import IntegrityError, models, transaction
from django.utils import timezone

from .models import Event, EventHandling, User

logger = logging.getLogger(__name__)

Handler = Callable[[Event], None]

_handlers: dict[str, list[tuple[str, Handler]]] = defaultdict(list)

MAX_ATTEMPTS = 5


def on(event_type: str) -> Callable[[Handler], Handler]:
    """Abonne un traitement à un type d'événement."""

    def decorator(func: Handler) -> Handler:
        name = f"{func.__module__}.{func.__qualname__}"
        if name not in {n for n, _ in _handlers[event_type]}:
            _handlers[event_type].append((name, func))
        return func

    return decorator


def handlers_for(event_type: str) -> list[tuple[str, Handler]]:
    return list(_handlers.get(event_type, []))


def emit(
    event_type: str,
    *,
    subject: models.Model | None = None,
    actor: User | Any | None = None,
    payload: dict[str, Any] | None = None,
    idempotency_key: str | None = None,
    process_now: bool = True,
) -> Event:
    """Enregistre un événement et programme son traitement après la transaction.

    `process_now=False` (imports en masse) : l'événement reste en attente et sera traité par
    le passage périodique de `run_jobs`, pour ne pas allonger la requête.
    """
    fields: dict[str, Any] = {
        "type": event_type,
        "payload": payload or {},
        "actor": actor if isinstance(actor, User) else None,
    }
    if subject is not None:
        fields["subject_type"] = ContentType.objects.get_for_model(subject)
        fields["subject_id"] = str(subject.pk)
    if idempotency_key:
        existing = Event.objects.filter(idempotency_key=idempotency_key).first()
        if existing is not None:
            return existing
        fields["idempotency_key"] = idempotency_key
        try:
            with transaction.atomic():
                event = Event.objects.create(**fields)
        except IntegrityError:
            return Event.objects.get(idempotency_key=idempotency_key)
    else:
        event = Event.objects.create(**fields)
    if process_now:
        transaction.on_commit(lambda: schedule(event.pk))
    return event


def schedule(event_id: int) -> None:
    if settings.JOBS_MODE == "eager":
        process(event_id)
        return
    from .tasks import process_event

    process_event.defer(event_id=event_id)


def process(event_id: int) -> Event:
    """Exécute les traitements abonnés qui n'ont pas encore réussi pour cet événement."""
    with transaction.atomic():
        event = Event.objects.select_for_update().get(pk=event_id)
        all_done = True
        for name, handler in handlers_for(event.type):
            handling, _ = EventHandling.objects.get_or_create(
                event=event, handler=name, defaults={"status": EventHandling.Status.FAILED}
            )
            if handling.status == EventHandling.Status.DONE:
                continue
            if handling.attempts >= MAX_ATTEMPTS:
                all_done = False
                continue
            handling.attempts += 1
            try:
                with transaction.atomic():
                    handler(event)
            except Exception as exc:
                all_done = False
                handling.status = EventHandling.Status.FAILED
                handling.last_error = "".join(traceback.format_exception(exc))[-4000:]
                logger.exception("Échec du traitement %s pour l'événement %s", name, event.pk)
            else:
                handling.status = EventHandling.Status.DONE
                handling.last_error = ""
                handling.finished_at = timezone.now()
            handling.save()
        event.status = Event.Status.PROCESSED if all_done else Event.Status.FAILED
        event.processed_at = timezone.now()
        event.save(update_fields=["status", "processed_at"])
    return event


def retry_pending(older_than_seconds: int = 120) -> int:
    """Rattrape les événements restés en attente ou en échec (appelé périodiquement)."""
    limit = timezone.now() - timedelta(seconds=older_than_seconds)
    ids = list(
        Event.objects.filter(
            status__in=[Event.Status.PENDING, Event.Status.FAILED], occurred_at__lt=limit
        )
        .exclude(handlings__attempts__gte=MAX_ATTEMPTS)
        .values_list("pk", flat=True)[:500]
    )
    for event_id in ids:
        process(event_id)
    return len(ids)
