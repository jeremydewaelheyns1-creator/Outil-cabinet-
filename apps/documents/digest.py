"""Résumé mensuel pour chaque employé, sous forme de notification dans l'outil (D-052).

Deux notifications le premier jour du mois (passage quotidien de run_jobs), pour les dossiers
dont l'employé fait partie de l'équipe :
1. **Conformité** : combien de dossiers incomplets, combien à revoir bientôt ;
2. **Ce que l'outil a fait seul le mois passé** : demandes envoyées, rappels, documents reçus,
   demandes restées sans réponse.
Rien n'est envoyé par e-mail : seulement des nombres et un lien vers l'écran Conformité.
"""

from __future__ import annotations

from datetime import date, timedelta

from django.db.models import QuerySet
from django.urls import reverse
from django.utils import timezone

from apps.clients.models import Client
from apps.core.models import Notification, User

from . import compliance
from .models import DocumentRequest, OutgoingEmail

MONTHS = (
    "janvier", "février", "mars", "avril", "mai", "juin", "juillet", "août", "septembre",
    "octobre", "novembre", "décembre",
)  # fmt: skip


def _plural(count: int, word: str, plural: str = "") -> str:
    return f"{count} {word if count == 1 else plural or word + 's'}"


def _my_clients(user: User) -> QuerySet[Client]:
    return Client.objects.visible_to(user).active().filter(assignments__user=user).distinct()


def _conformity(user: User, clients: list[Client], month: str) -> None:
    rows = compliance.board(clients)
    incomplete = sum(1 for r in rows if r.level == "danger")
    soon = sum(1 for r in rows if r.level == "warning")
    askable = sum(1 for r in rows if r.askable and r.has_email)
    if incomplete or soon:
        title = f"{_plural(incomplete + soon, 'dossier')} à mettre en ordre"
        lines = [
            f"{_plural(incomplete, 'dossier incomplet', 'dossiers incomplets')}",
            f"{_plural(soon, 'dossier', 'dossiers')} à revoir bientôt",
        ]
        if askable:
            lines.append(f"{askable} peuvent être demandés aux clients en un clic")
    else:
        title, lines = "Tous vos dossiers sont en ordre ✓", []
    Notification.objects.get_or_create(
        user=user, key=f"conformite:{month}",
        defaults={"title": title, "lines": lines,
                  "link": reverse("conformite:board") + "?qui=moi"},
    )  # fmt: skip


def _activity(user: User, clients: list[Client], month: str, start: date, end: date) -> None:
    requests = DocumentRequest.objects.filter(client__in=clients)
    sent = (
        requests.filter(created_at__date__gte=start, created_at__date__lt=end, bundle__isnull=True)
        .exclude(status=DocumentRequest.Status.CANCELLED)
        .count()
    )
    reminders = OutgoingEmail.objects.filter(
        request__client__in=clients, kind=OutgoingEmail.Kind.REMINDER,
        created_at__date__gte=start, created_at__date__lt=end,
    ).count()  # fmt: skip
    received = (
        requests.filter(status=DocumentRequest.Status.RECEIVED,
                        closed_at__date__gte=start, closed_at__date__lt=end)
        .exclude(kind=DocumentRequest.Kind.BUNDLE)
        .count()
    )  # fmt: skip
    from .services import unanswered as no_answer

    unanswered = no_answer().filter(client__in=clients).count()
    lines = [
        f"{_plural(sent, 'demande envoyée', 'demandes envoyées')} aux clients",
        f"{_plural(reminders, 'rappel envoyé', 'rappels envoyés')}",
        f"{_plural(received, 'document reçu', 'documents reçus')}",
    ]
    if unanswered:
        lines.append(
            f"{_plural(unanswered, 'demande', 'demandes')} sans réponse après les rappels : "
            "à relancer vous-même"
        )
    Notification.objects.get_or_create(
        user=user, key=f"activite:{month}",
        defaults={"title": f"Ce que l'outil a fait en {MONTHS[start.month - 1]}",
                  "lines": lines, "link": reverse("conformite:board") + "?qui=moi"},
    )  # fmt: skip


def monthly(today: date | None = None) -> int:
    """Crée les deux résumés du mois pour chaque employé (une seule fois par mois)."""
    today = today or timezone.localdate()
    month = f"{today:%Y-%m}"
    end = today.replace(day=1)
    start = (end - timedelta(days=1)).replace(day=1)
    count = 0
    for user in User.objects.filter(is_active=True, assignments__isnull=False).distinct():
        if Notification.objects.filter(user=user, key=f"conformite:{month}").exists():
            continue
        clients = list(_my_clients(user))
        if not clients:
            continue
        _conformity(user, clients, month)
        _activity(user, clients, month, start, end)
        count += 1
    return count
