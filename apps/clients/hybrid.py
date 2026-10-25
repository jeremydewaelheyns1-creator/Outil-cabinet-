"""Gestion hybride des dossiers (D-063).

Option du cabinet, coupée par défaut. Quand elle est activée, le comptable d'un dossier peut
être « Hybride » : pas de comptable fixe. L'expert-comptable (le « Responsable » du dossier)
reste attitré ; un comptable qui a du temps prend le dossier (« Je le prends »), les autres
voient qu'il est pris et ne travaillent pas dessus en même temps. Il le rend quand il a fini.

- Un seul comptable à la fois (contrainte en base).
- Le comptable qui prend le dossier en devient le comptable le temps de la prise en charge :
  les échéances ouvertes sans responsable lui sont attribuées, et lui sont retirées quand il
  le rend.
- Sans temps encodé sur le dossier pendant `hybrid_release_days` jours, le dossier redevient
  libre tout seul et la personne est prévenue dans l'outil (`release_stale`, `run_jobs`).
- Tout est tracé : historique des prises en charge et événements.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, timedelta

from django.db import IntegrityError, transaction
from django.db.models import QuerySet
from django.utils import timezone

from apps.core import events
from apps.core.models import CabinetSettings, Notification, User

from .models import Assignment, Client, HybridClaim

ACCOUNTANT_ROLE = Assignment.Role.ASSISTANT  # le « comptable » du dossier
MAX_FREE_ROWS = 15  # Accueil : les 15 dossiers libres les plus urgents (le total reste affiché)


class HybridError(Exception):
    """Action refusée (message lisible)."""


def enabled() -> bool:
    return CabinetSettings.current().hybrid_management


def is_hybrid(client: Client) -> bool:
    return client.accountant_hybrid and enabled()


def hybrid_clients(user: User) -> QuerySet[Client]:
    """Dossiers hybrides que l'employé peut voir (vide si l'option est coupée)."""
    if not enabled():
        return Client.objects.none()
    return Client.objects.visible_to(user).active().filter(accountant_hybrid=True)


def claimed_by(user: User) -> QuerySet[Client]:
    if not enabled():
        return Client.objects.none()
    return Client.objects.visible_to(user).filter(accountant_hybrid=True, hybrid_claim__user=user)


def set_hybrid(client: Client, value: bool, actor: User) -> None:
    """Passe le comptable du dossier en « Hybride » (ou revient à un comptable fixe)."""
    if value == client.accountant_hybrid:
        return
    with transaction.atomic():
        client.accountant_hybrid = value
        client.save(update_fields=["accountant_hybrid", "updated_at"])
        if value:
            Assignment.objects.filter(client=client, role=ACCOUNTANT_ROLE).delete()
        else:
            claim = HybridClaim.objects.filter(client=client).first()
            if claim is not None:
                _unassign_tasks(client, claim.user)
                claim.delete()
    events.emit("client.hybrid_changed", subject=client, actor=actor, payload={"hybride": value})


def take(client: Client, user: User) -> HybridClaim:
    if not is_hybrid(client):
        raise HybridError("Ce dossier n'est pas en gestion hybride.")
    if not Client.objects.visible_to(user).filter(pk=client.pk).exists():
        raise HybridError("Dossier introuvable.")
    try:
        with transaction.atomic():
            claim = HybridClaim.objects.create(client=client, user=user)
            _assign_tasks(client, user)
    except IntegrityError as exc:
        raise HybridError("Ce dossier vient d'être pris par un collègue.") from exc
    events.emit("hybrid.taken", subject=client, actor=user)
    return claim


def release(client: Client, user: User) -> None:
    """Rendre le dossier libre : par celui qui l'a pris, ou par un administrateur."""
    claim = HybridClaim.objects.filter(client=client).select_related("user").first()
    if claim is None:
        return
    if claim.user_id != user.pk and not user.is_staff:
        raise HybridError(
            "Seul le collègue qui a pris le dossier (ou un administrateur) peut le rendre."
        )
    with transaction.atomic():
        _unassign_tasks(client, claim.user)
        claim.delete()
    events.emit("hybrid.released", subject=client, actor=user)


def release_stale(today: date | None = None) -> int:
    """Dossiers pris sans temps encodé depuis N jours : rendus libres, la personne est prévenue."""
    from apps.timesheet.models import TimeEntry

    if not enabled():
        return 0
    days = CabinetSettings.current().hybrid_release_days
    today = today or timezone.localdate()
    limit = today - timedelta(days=days)
    count = 0
    for claim in HybridClaim.objects.select_related("client", "user").filter(
        since__date__lte=limit
    ):
        worked = TimeEntry.objects.filter(
            user=claim.user, client=claim.client, day__gt=limit
        ).exists()
        if worked:
            continue
        client, owner = claim.client, claim.user
        with transaction.atomic():
            _unassign_tasks(client, owner)
            claim.delete()
        Notification.objects.get_or_create(
            user=owner,
            key=f"hybride:{client.pk}:{today:%Y%m%d}",
            defaults={
                "title": f"Dossier rendu libre : {client.display_name}",
                "lines": [
                    f"Pas de temps encodé dessus depuis {days} jours : un collègue peut le prendre."
                ],
                "link": "/",
            },
        )
        events.emit("hybrid.released", subject=client, payload={"automatique": True})
        count += 1
    return count


def _assign_tasks(client: Client, user: User) -> None:
    client.tasks.open().filter(assignee__isnull=True).update(assignee=user)


def _unassign_tasks(client: Client, user: User) -> None:
    fixed = Assignment.objects.filter(client=client, user=user).exists()
    if not fixed:
        client.tasks.open().filter(assignee=user).update(assignee=None)


@dataclass(frozen=True)
class Row:
    client: Client
    todo: str
    due: date | None
    mine: bool


@dataclass(frozen=True)
class Board:
    rows: list[Row]  # libres puis pris par moi (jamais ceux des collègues)
    free: int
    mine: int
    others: int

    @property
    def hidden(self) -> int:
        """Dossiers libres non listés (seuls les plus urgents le sont)."""
        return self.free - sum(1 for r in self.rows if not r.mine)


def board(user: User) -> Board | None:
    """Le tableau « Dossiers hybrides » de l'Accueil (None si l'option est coupée)."""
    if not enabled():
        return None
    clients = list(
        hybrid_clients(user).select_related("hybrid_claim").order_by("name", "first_name")
    )
    claims = {c.pk: c.hybrid_claim.user_id for c in clients if hasattr(c, "hybrid_claim")}
    free = [c for c in clients if c.pk not in claims]
    mine = [c for c in clients if claims.get(c.pk) == user.pk]
    others = len(clients) - len(free) - len(mine)
    from apps.tasks.models import Task

    first_task: dict[int, Task] = {}
    for task in Task.objects.open().filter(client__in=[*mine, *free]).order_by("due_date", "pk"):
        first_task.setdefault(task.client_id, task)  # une seule requête pour tout le tableau
    rows = []
    for client in [*mine, *free]:
        found = first_task.get(client.pk)
        rows.append(
            Row(
                client,
                found.title if found else "Rien de daté : à voir",
                found.due_date if found else None,
                client.pk in claims,
            )
        )
    rows.sort(key=lambda r: (not r.mine, r.due or date.max))
    shown = [r for r in rows if r.mine] + [r for r in rows if not r.mine][:MAX_FREE_ROWS]
    return Board(shown, len(free), len(mine), others)
