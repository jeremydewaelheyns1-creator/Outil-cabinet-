"""Création automatique des échéances à partir des règles.

Idempotent : relancer la génération ne crée jamais de doublon (clé client + règle + période).
Pour chaque client et chaque règle :
- client concerné : les tâches manquantes de la fenêtre (passé récent → 12 mois) sont créées ;
- client plus concerné : ses tâches futures encore intactes sont retirées ;
- règle modifiée (ex. date limite déplacée) : chaque tâche prend la nouvelle date limite
  (c'est une date légale, pas un choix) ; « task.rescheduled » prévient les autres modules
  (ligne TVA).
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, timedelta

from django.db import transaction
from django.utils import timezone

from apps.clients.models import Assignment, Client
from apps.core import events
from apps.core.models import User

from .models import GenerationRun, Task, TaskStep
from .rules import Rule, RuleSet, load_rules, rules_hash


@dataclass
class Result:
    created: int = 0
    removed: int = 0
    moved: int = 0

    def __iadd__(self, other: Result) -> Result:
        self.created += other.created
        self.moved += other.moved
        self.removed += other.removed
        return self


def _assignee(client: Client, rule: Rule) -> User | None:
    roles = {a.role: a.user for a in client.assignments.select_related("user")}
    return roles.get(rule.assignee_role) or roles.get(Assignment.Role.MANAGER)


def _remove_untouched(client: Client, rule: Rule, today: date) -> int:
    removed = 0
    candidates = Task.objects.filter(
        client=client, kind=rule.code, generated=True, status=Task.Status.TODO, due_date__gte=today
    )
    for task in candidates:
        if task.is_untouched:
            task.delete()
            removed += 1
    return removed


@transaction.atomic
def generate_for_client(
    client: Client, today: date | None = None, rules: RuleSet | None = None
) -> Result:
    today = today or timezone.localdate()
    rules = rules or load_rules()
    window_start = today - timedelta(days=rules.days_back)
    window_end = today + timedelta(days=31 * rules.months_ahead)
    result = Result()
    for rule in rules.rules:
        if not rule.applies_to(client):
            result.removed += _remove_untouched(client, rule, today)
            continue
        tasks = {
            t.period_key: t
            for t in Task.objects.filter(client=client, kind=rule.code, generated=True)
        }
        existing = set(tasks)
        # Les échéances tombent jusqu'à ~8 mois après la période : on part d'un an plus tôt.
        for period in rule.periods(client, window_start.year - 1, window_end.year):
            if period.key in existing:
                task = tasks[period.key]
                due = rule.due_date(period)
                # Date légale changée (ex. TVA trimestrielle au 25) : l'échéance suit, même
                # commencée, passée ou terminée (c'est un fait, pas un choix du cabinet).
                if due and due != task.due_date:
                    old = task.due_date
                    task.due_date = due
                    task.save(update_fields=["due_date", "updated_at"])
                    events.emit(
                        "task.rescheduled", subject=client,
                        payload={"tache": task.pk, "avant": old.isoformat(),
                                 "apres": due.isoformat()},
                    )  # fmt: skip
                    result.moved += 1
                continue
            due = rule.due_date(period)
            if due is None or not (window_start <= due <= window_end):
                continue
            task = Task.objects.create(
                client=client,
                kind=rule.code,
                title=rule.render_title(period),
                category=rule.category,
                period_key=period.key,
                period_label=period.label,
                period_start=period.start,
                period_end=period.end,
                due_date=due,
                assignee=_assignee(client, rule),
                generated=True,
            )
            TaskStep.objects.bulk_create(
                TaskStep(task=task, label=label, position=index)
                for index, label in enumerate(rule.steps)
            )
            result.created += 1
    return result


def reassign_open_tasks(client: Client) -> int:
    """Après un changement d'équipe : les tâches générées pas encore commencées suivent."""
    rules = load_rules()
    changed = 0
    for task in Task.objects.filter(client=client, generated=True, status=Task.Status.TODO):
        rule = rules.get(task.kind)
        if rule is None:
            continue
        assignee = _assignee(client, rule)
        if assignee is not None and task.assignee_id != assignee.pk:
            task.assignee = assignee
            task.save(update_fields=["assignee", "updated_at"])
            changed += 1
    return changed


def generate_all(today: date | None = None) -> GenerationRun:
    """Tous les clients (les anciens clients et prospects voient leurs tâches futures retirées)."""
    run = GenerationRun.objects.create(rules_hash=rules_hash())
    rules = load_rules()
    total = Result()
    clients = Client.objects.prefetch_related("assignments__user")
    for client in clients.iterator(chunk_size=200):
        total += generate_for_client(client, today, rules)
        run.clients += 1
    run.created, run.removed = total.created, total.removed
    run.finished_at = timezone.now()
    run.save()
    return run


def generate_all_if_due() -> GenerationRun | None:
    """Une génération complète par jour (appelé par `run_jobs` toutes les 5 minutes), et une de
    plus dès que le fichier de règles change (mise à jour de l'outil)."""
    today = timezone.localdate()
    done = GenerationRun.objects.filter(
        started_at__date=today, finished_at__isnull=False, rules_hash=rules_hash()
    )
    if done.exists():  # déjà fait aujourd'hui avec les règles actuelles
        return None
    return generate_all(today)
