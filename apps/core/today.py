"""« Ma journée » (D-059) : l'outil vient à vous.

Au lieu d'aller chercher le travail dossier par dossier, l'accueil rassemble pour l'employé :
1. **Prêt à valider** — ce que l'outil a préparé et qui attend un clic (e-mail TVA, carte
   d'identité reçue, PDF à confirmer, risque élevé à valider, fichiers à classer) ;
2. **À faire vous-même** — ses échéances du jour ou en retard, les clients qui ne répondent
   plus malgré les rappels ;
3. **Fait tout seul** — ce que l'outil a fait depuis hier (rappels, demandes, pièces reçues).
Plus, sur le côté : sa semaine, le temps encodé aujourd'hui, l'état de ses dossiers.

Tout passe par `Client.objects.visible_to(user)` ; les dossiers « à moi » sont ceux de son
équipe (tous les dossiers visibles s'il n'est affecté à aucun).
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, time, timedelta
from typing import Any

from django.db.models import Count, QuerySet
from django.urls import reverse
from django.utils import timezone

from apps.clients.models import Client
from apps.core.capabilities import Capability
from apps.core.models import User


@dataclass(frozen=True)
class Item:
    icon: str  # tva / carte / pdf / risque / depot / demande / tache / appel
    title: str
    detail: str
    url: str
    action: str
    tone: str = "primary"  # primary / danger / warning


def my_clients(user: User) -> QuerySet[Client]:
    visible = Client.objects.visible_to(user).active()
    mine = visible.filter(assignments__user=user).distinct()
    return mine if mine.exists() else visible


def _ready(user: User, clients: QuerySet[Client]) -> list[Item]:
    from apps.documents.compliance import summary_for
    from apps.documents.models import Document, InboxItem, RiskAssessment
    from apps.vat.models import FINISHED, Column, Status, VatFiling, VatPending

    items: list[Item] = []
    recent = timezone.localdate() - timedelta(days=90)
    filed = VatFiling.objects.filter(
        client__in=clients, pdf__isnull=False, period_end__gte=recent,
        cells__column=Column.FILED, cells__status=Status.DONE,
    ).exclude(
        cells__column=Column.CLIENT, cells__status__in=FINISHED
    ).exclude(messages__sent_at__isnull=False).select_related("client").distinct()  # fmt: skip
    for filing in filed[:6]:
        items.append(Item(
            "tva", f"{filing.client.display_name} — TVA {filing.period_label}",
            "Déclaration déposée et lue : l'e-mail au client est prêt à relire.",
            reverse("clients:vat", args=[filing.client_id]), "Relire et envoyer",
        ))  # fmt: skip
    pending = VatPending.objects.filter(document__client__in=clients).select_related(
        "document__client"
    )
    for p in pending[:4]:
        client = p.document.client
        items.append(Item(
            "pdf", f"{client.display_name} — PDF TVA à confirmer",
            "L'outil a reconnu une déclaration mais attend votre confirmation pour la ranger.",
            reverse("clients:vat", args=[client.pk]), "Confirmer",
        ))  # fmt: skip
    cards = Document.objects.filter(
        client__in=clients, case="pieces-identite", archived_at__isnull=True, review_needed=True
    ).select_related("client", "person")
    for doc in cards[:6]:
        who = doc.person.display_name if doc.person else doc.client.display_name
        items.append(Item(
            "carte", f"Carte d'identité reçue — {who}",
            f"Dossier {doc.client.display_name} : vérifiez la validité, un clic pour ranger.",
            reverse("clients:document_case", args=[doc.client_id, "pieces-identite"]),
            "Confirmer",
        ))  # fmt: skip
    if user.has_capability(Capability.AML_DECIDE):
        risky = RiskAssessment.objects.filter(
            client__in=Client.objects.visible_to(user), level="high", approved_at__isnull=True
        ).select_related("client")
        for a in risky[:4]:
            items.append(Item(
                "risque", f"{a.client.display_name} — risque élevé à valider",
                "Fiche de risque en attente de l'accord de l'AMLCO.",
                reverse("clients:document_case", args=[a.client_id, "fiche-risque"]),
                "Valider", "warning",
            ))  # fmt: skip
    inbox = InboxItem.objects.filter(uploaded_by=user).count()
    if inbox:
        items.append(Item(
            "depot", f"{inbox} fichier{'s' if inbox > 1 else ''} déposé{'s' if inbox > 1 else ''}"
            " à classer", "L'outil n'a pas su les ranger seul.",
            reverse("depot:index"), "Classer",
        ))  # fmt: skip
    askable = summary_for(user)["askable"]
    if askable:
        items.append(Item(
            "demande", f"{askable} dossier{'s' if askable > 1 else ''} : pièces à demander",
            "Cartes d'identité, documents à signer : un seul e-mail par client, préparé.",
            reverse("conformite:board") + "?qui=moi", "Voir et envoyer",
        ))  # fmt: skip
    return items


def _todo(user: User, clients: QuerySet[Client], today: date) -> list[Item]:
    from apps.documents.services import unanswered
    from apps.tasks.models import Task

    items: list[Item] = []
    tasks = (
        Task.objects.visible_to(user).open().filter(assignee=user, due_date__lte=today)
        .select_related("client").order_by("due_date")
    )  # fmt: skip
    for task in tasks[:8]:
        late = (today - task.due_date).days
        items.append(Item(
            "tache", f"{task.title}",
            f"{task.client.display_name} · "
            + (f"en retard de {late} j" if late else "pour aujourd'hui"),
            reverse("clients:tasks", args=[task.client_id]), "Ouvrir",
            "danger" if late else "primary",
        ))  # fmt: skip
    silent = unanswered().filter(client__in=clients).values("client").annotate(n=Count("pk"))
    names = {c.pk: c for c in Client.objects.filter(pk__in=[s["client"] for s in silent])}
    for s in silent[:5]:
        client = names[s["client"]]
        items.append(Item(
            "appel", f"{client.display_name} ne répond plus",
            "Demande restée sans réponse malgré les 2 rappels : un appel est plus efficace.",
            reverse("clients:document_case", args=[client.pk, "a-recevoir"]), "Voir", "danger",
        ))  # fmt: skip
    return items


def _overnight(clients: QuerySet[Client], since: datetime) -> list[str]:
    from apps.documents.models import DocumentRequest, IdentityCard, OutgoingEmail

    reminders = OutgoingEmail.objects.filter(
        request__client__in=clients, kind=OutgoingEmail.Kind.REMINDER, created_at__gte=since
    ).count()
    asked = DocumentRequest.objects.filter(
        client__in=clients, created_by__isnull=True, created_at__gte=since, bundle__isnull=True
    ).count()
    received = (
        DocumentRequest.objects.filter(
            client__in=clients, status=DocumentRequest.Status.RECEIVED, closed_at__gte=since
        )
        .exclude(kind=DocumentRequest.Kind.BUNDLE)
        .count()
    )
    cards = IdentityCard.objects.filter(
        auto_applied=True, created_at__gte=since, document__client__in=clients
    ).count()
    chips = [
        (reminders, "rappel envoyé", "rappels envoyés"),
        (asked, "demande envoyée seule", "demandes envoyées seules"),
        (received, "pièce reçue d'un client", "pièces reçues des clients"),
        (cards, "carte classée automatiquement", "cartes classées automatiquement"),
    ]
    return [f"{n} {one if n == 1 else many}" for n, one, many in chips if n]


def _week(user: User, today: date) -> list[dict[str, Any]]:
    from apps.tasks.models import Task

    monday = today - timedelta(days=today.weekday())
    days = [monday + timedelta(days=i) for i in range(5)]
    counts = dict(
        Task.objects.visible_to(user).open().filter(assignee=user, due_date__in=days)
        .values_list("due_date").annotate(n=Count("pk"))
    )  # fmt: skip
    peak = max(counts.values(), default=0)
    names = ("lun", "mar", "mer", "jeu", "ven")
    return [
        {"name": names[i], "day": d, "count": counts.get(d, 0), "today": d == today,
         "peak": peak >= 3 and counts.get(d, 0) == peak}
        for i, d in enumerate(days)
    ]  # fmt: skip


def build(user: User) -> dict[str, Any]:
    from apps.documents.compliance import summary_for
    from apps.tasks.models import Task
    from apps.timesheet.models import hours_label
    from apps.timesheet.services import minutes_on

    today = timezone.localdate()
    clients = my_clients(user)
    since = timezone.make_aware(datetime.combine(today - timedelta(days=1), time(0, 0)))
    ready = _ready(user, clients)
    todo = _todo(user, clients, today)
    start_of_day = timezone.make_aware(datetime.combine(today, time(0, 0)))
    done_today = Task.objects.filter(completed_by=user, completed_at__gte=start_of_day).count()
    total = done_today + len(ready) + len(todo)
    week = _week(user, today)
    peak = next((d for d in week if d["peak"] and d["day"] >= today), None)
    return {
        "today": today,
        "ready": ready,
        "count": len(ready) + len(todo),
        "todo": todo,
        "overnight": _overnight(clients, since),
        "done_today": done_today,
        "total_today": total,
        "progress": round(100 * done_today / total) if total else 100,
        "week": week,
        "peak": peak,
        "time_today": hours_label(minutes_on(user, today)),
        "compliance": summary_for(user),
    }
