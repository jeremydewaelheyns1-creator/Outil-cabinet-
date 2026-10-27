from typing import Any

from django.conf import settings
from django.http import HttpRequest


def app_context(request: HttpRequest) -> dict[str, Any]:
    context: dict[str, Any] = {"CABINET_NAME": settings.CABINET_NAME}
    user = getattr(request, "user", None)
    if user is not None and user.is_authenticated:
        context["unread_notifications"] = user.notifications.filter(read_at__isnull=True).count()
        context["unanswered_requests"] = _unanswered(user)
        context["unread_mails"] = _unread_mails(user)
        from apps.tasks.extensions import unseen_for

        context["deadline_news"] = unseen_for(user)  # délais prolongés par le SPF (D-089)
    return context


def _unanswered(user: Any) -> int:
    """Demandes de mes dossiers restées sans réponse après tous les rappels (D-055)."""
    from apps.clients.models import Client
    from apps.documents.services import unanswered

    mine = Client.objects.visible_to(user).filter(assignments__user=user)
    return int(unanswered().filter(client__in=mine).values("client").distinct().count())


def _unread_mails(user: Any) -> int:
    """E-mails non lus de la boîte de réception (D-060)."""
    from apps.mailbox.models import MailMessage

    return int(
        MailMessage.objects.filter(
            owner=user, folder=MailMessage.Folder.INBOX, classed_at__isnull=True,
            read_at__isnull=True,
        ).count()
    )  # fmt: skip
