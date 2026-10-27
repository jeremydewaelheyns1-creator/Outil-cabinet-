"""Documents à jour ou non, et suivi automatique de ce qui expire (D-050).

1. **Obsolescence.** Un document produit par l'outil (identification, déclaration UBO, lettre de
   mission…) décrit le dossier tel qu'il était ce jour-là. L'outil garde une empreinte de chaque
   partie utilisée (identité, adresse, mandataires, bénéficiaires…). Si l'une change ensuite,
   la ligne du document passe en orange : « À mettre à jour : adresse modifiée depuis ».
   Les empreintes sont des HMAC (clé du serveur) : elles ne permettent pas de retrouver les
   données, et le numéro national n'y entre pas.
2. **Suivi.** Chaque jour, pour les documents que le cabinet établit lui-même (fiche de risque,
   extrait du registre UBO) et qui expirent bientôt, ou pour un document devenu obsolète, une
   échéance est créée pour le gestionnaire du dossier. Elle se ferme seule quand le document
   est remplacé. Les pièces que le client fournit (carte d'identité) sont demandées au client
   automatiquement (identity.py).
"""

from __future__ import annotations

import hashlib
import hmac
import json
from datetime import date, timedelta
from typing import Any

from django.conf import settings
from django.db import transaction
from django.utils import timezone

from apps.clients.models import Client, Relation
from apps.core import events
from apps.core.models import Event

from . import types
from .models import Document

IDENTITY = ("name", "first_name", "legal_form", "enterprise_number", "birth_date", "nationality")
ADDRESS = ("street", "house_number", "box", "postal_code", "city", "country")
LABELS = {
    "identite": "identité",
    "adresse": "adresse",
    "activite": "activités",
    "mandataires": "mandataires",
    "fonctions": "fonctions",
    "carte": "carte d'identité",
    "beneficiaires": "bénéficiaires effectifs",
    "mission": "conditions de la mission",
}


def _digest(value: Any) -> str:
    raw = json.dumps(value, sort_keys=True, default=str).encode()
    key = settings.SECRET_KEY.encode()
    return hmac.new(key, b"empreinte-document:" + raw, hashlib.sha256).hexdigest()[:24]


def _fields(client: Client, names: tuple[str, ...]) -> list[Any]:
    return [getattr(client, name) for name in names]


def _management(client: Client) -> list[tuple[int, str]]:
    roles = (*Relation.MANAGEMENT_ROLES, Relation.Role.PERMANENT_REPRESENTATIVE)
    current = Relation.objects.current().filter(entity=client, role__in=roles)
    return sorted(current.values_list("person_id", "role"))


def _parts(client: Client, doc_type: str, person: Client | None) -> dict[str, Any]:
    if doc_type == "identification_client":
        return {
            "identite": _fields(client, IDENTITY),
            "adresse": _fields(client, ADDRESS),
            "activite": [c.get("code") if isinstance(c, dict) else c for c in client.nace_codes],
            "mandataires": _management(client),
        }
    if doc_type == "identification_mandataire" and person is not None:
        from .models import IdentityCard

        card = IdentityCard.objects.filter(person=person).order_by("-valid_until").first()
        roles = Relation.objects.current().filter(entity=client, person=person)
        return {
            "identite": _fields(person, IDENTITY),
            "adresse": _fields(person, ADDRESS),
            "fonctions": sorted(roles.values_list("role", flat=True)),
            "carte": card.valid_until if card else None,
        }
    if doc_type in ("declaration_ubo", "extrait_ubo"):
        from apps.clients.services import ubo

        analysis = ubo.analyse(client)
        if doc_type == "extrait_ubo":  # registre UBO : seuls les bénéficiaires comptent (D-078)
            return {"beneficiaires": sorted(
                (c.person.pk, c.basis, str(c.share_percentage), str(c.voting_percentage))
                for c in analysis.candidates
            )}  # fmt: skip
        return {
            "identite": _fields(client, IDENTITY),
            "beneficiaires": sorted(
                (c.person.pk, c.basis, str(c.share_percentage), str(c.voting_percentage))
                for c in analysis.candidates
            ),
        }
    if doc_type in {"lettre_mission", "procuration"}:
        return {
            "identite": _fields(client, IDENTITY),
            "adresse": _fields(client, ADDRESS),
            "mission": [
                client.vat_status, client.vat_periodicity,
                client.fiscal_year_end_month, client.fiscal_year_end_day,
            ] if doc_type == "lettre_mission" else [],
        }  # fmt: skip
    return {}


def fingerprint(client: Client, doc_type: str, person: Client | None = None) -> dict[str, str]:
    """Empreinte de chaque partie du dossier utilisée par ce type de document."""
    return {name: _digest(value) for name, value in _parts(client, doc_type, person).items()}


def changes(document: Document, client: Client | None = None) -> list[str]:
    """Parties du dossier modifiées depuis le document (vide : à jour ou non suivi)."""
    saved = document.data_fingerprint or {}
    if not saved:
        return []
    current = fingerprint(client or document.client, document.doc_type, document.person)
    return [LABELS.get(k, k) for k, v in saved.items() if k in current and current[k] != v]


# --- Suivi quotidien -------------------------------------------------------------------------

KIND_PREFIX = "document:"
# Documents établis par le cabinet lui-même : leur échéance devient une tâche du gestionnaire.
CABINET_SIDE = {
    "fiche_risque": "Réviser la fiche de risque",
    "extrait_ubo": "Consulter le registre UBO et ranger un nouvel extrait",
}
GENERATED = ("identification_client", "identification_mandataire", "declaration_ubo")


def _manager(client: Client) -> Any:
    from apps.clients.models import Assignment

    assignment = client.assignments.filter(role=Assignment.Role.MANAGER).select_related("user")
    first = assignment.first()
    return first.user if first else None


def _key(document: Document) -> str:
    return document.pk.hex[:30]  # tient dans le champ « période » de l'échéance


def _task(client: Client, document: Document, title: str, due: date, slug: str) -> bool:
    from apps.tasks.models import Task

    _, created = Task.objects.get_or_create(
        client=client, kind=f"{KIND_PREFIX}{slug}", period_key=_key(document), generated=True,
        defaults={
            "title": title[:200], "category": Task.Category.AML, "due_date": due,
            "assignee": _manager(client),
            "notes": "",
        },
    )  # fmt: skip
    return created


def close_resolved(client: Client | None = None) -> int:
    """Ferme les tâches dont le document a été remplacé (ou n'est plus en place)."""
    from apps.tasks.models import Task

    tasks = Task.objects.open().filter(kind__startswith=KIND_PREFIX, generated=True)
    if client is not None:
        tasks = tasks.filter(client=client)
    current = {
        _key(d)
        for d in Document.objects.filter(
            client__in={t.client_id for t in tasks}, archived_at__isnull=True
        ).only("pk")
    }
    closed = 0
    for task in tasks:
        if task.period_key not in current:
            task.status = Task.Status.DONE
            task.completed_at = timezone.now()
            task.notes = (task.notes + "\n" if task.notes else "") + "Fermée : document remplacé."
            task.save(update_fields=["status", "completed_at", "notes", "updated_at"])
            closed += 1
    return closed


def refresh_changed(client: Client) -> int:
    """Recalcule « modifié depuis » des documents en place du dossier (D-080). Les tableaux de
    plusieurs dossiers lisent ce résultat au lieu de tout recalculer à l'affichage."""
    updated = 0
    documents = Document.objects.filter(
        client=client, archived_at__isnull=True, state=Document.State.FINAL,
    ).exclude(data_fingerprint={}).select_related("person")  # fmt: skip
    for document in documents:
        found = changes(document, client)
        if found != list(document.changed_parts):
            document.changed_parts = found
            document.save(update_fields=["changed_parts"])
            updated += 1
    return updated


@events.on("client.updated")
@events.on("client.updated_from_bce")
@events.on("relation.saved")
@events.on("relation.deleted")
def refresh_after_change(event: Event) -> None:
    """Fiche ou relations modifiées : « à mettre à jour » se voit aussitôt dans les tableaux."""
    client = Client.objects.filter(pk=event.subject_id).first() if event.subject_id else None
    if client is not None:
        refresh_changed(client)


def follow_client(client: Client, today: date | None = None) -> int:
    today = today or timezone.localdate()
    horizon = today + timedelta(days=types.WARN_DAYS)
    created = 0
    refresh_changed(client)
    documents = Document.objects.filter(
        client=client, archived_at__isnull=True, state=Document.State.FINAL,
        doc_type__in=[*CABINET_SIDE, *GENERATED],
    ).select_related("person")  # fmt: skip
    for document in documents:
        if document.doc_type == "extrait_ubo" and document.changed_parts:
            # Bénéficiaires modifiés : le registre UBO se met à jour dans le mois (D-078).
            created += _task(
                client, document, "Mettre à jour le registre UBO (bénéficiaires modifiés)",
                today + timedelta(days=30), "maj-extrait_ubo",
            )  # fmt: skip
            continue
        if document.doc_type in CABINET_SIDE:
            if document.expires_on and document.expires_on <= horizon:
                created += _task(
                    client, document, CABINET_SIDE[document.doc_type],
                    max(document.expires_on, today), document.doc_type,
                )  # fmt: skip
            continue
        changed = list(document.changed_parts)
        if changed:
            label = types.BY_SLUG[document.doc_type].label
            who = f" — {document.person.display_name}" if document.person else ""
            title = f"Mettre à jour : {label}{who} ({', '.join(changed)} modifié)"
            created += _task(
                client, document, title, today + timedelta(days=30), f"maj-{document.doc_type}"
            )
    return created


def follow_up(today: date | None = None) -> int:
    """Passage quotidien (run_jobs) : tâches créées pour ce qui expire ou n'est plus à jour."""
    close_resolved()
    created = 0
    for client in Client.objects.filter(status=Client.Status.ACTIVE).iterator(chunk_size=200):
        with transaction.atomic():
            created += follow_client(client, today)
    return created
