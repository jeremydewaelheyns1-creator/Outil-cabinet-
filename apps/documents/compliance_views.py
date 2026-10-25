"""Écran « Conformité » : tous les dossiers, ce qui manque, demande groupée (D-051)."""

from __future__ import annotations

from django.contrib import messages
from django.core.paginator import Paginator
from django.http import HttpResponse
from django.shortcuts import redirect, render
from django.views.decorators.http import require_POST

from apps.clients.models import Client
from apps.core.audit import log_access
from apps.core.capabilities import Capability
from apps.core.http import AppRequest
from apps.core.models import AccessLog
from apps.core.permissions import require_capability

from . import compliance

PER_PAGE = 50


def _clients(request: AppRequest, who: str) -> list[Client]:
    clients = Client.objects.visible_to(request.user).active()
    if who == "moi":
        clients = clients.filter(assignments__user=request.user).distinct()
    return list(clients.order_by("name", "first_name"))


def board(request: AppRequest) -> HttpResponse:
    who = request.GET.get("qui", "moi")
    who = who if who in {"moi", "tous"} else "moi"
    level = request.GET.get("niveau", "")
    rows = compliance.board(_clients(request, who))
    totals = {
        "danger": sum(1 for r in rows if r.level == "danger"),
        "warning": sum(1 for r in rows if r.level == "warning"),
        "askable": sum(1 for r in rows if r.askable and r.has_email),
    }
    if level in {"danger", "warning"}:
        rows = [r for r in rows if r.level == level]
    page = Paginator(rows, PER_PAGE).get_page(request.GET.get("page"))
    log_access(request, AccessLog.Action.VIEW, None, details={"écran": "conformité", "qui": who})
    return render(
        request,
        "documents/compliance.html",
        {
            "rows": page.object_list,
            "page": page,
            "totals": totals,
            "who": who,
            "level": level,
            "can_edit": request.user.has_capability(Capability.CLIENTS_EDIT),
        },
    )


@require_POST
@require_capability(Capability.CLIENTS_EDIT)
def ask(request: AppRequest) -> HttpResponse:
    """« Demander » : un seul e-mail et un seul lien par client coché."""
    ids = [int(i) for i in request.POST.getlist("client") if i.isdigit()][:200]
    sent, skipped = 0, 0
    for client in Client.objects.visible_to(request.user).filter(pk__in=ids):
        bundle = compliance.ask_everything(client, request.user)
        if bundle is None:
            skipped += 1
            continue
        log_access(request, AccessLog.Action.CREATE, client,
                   details={"demande groupée": bundle.reference})  # fmt: skip
        sent += 1
    if sent:
        messages.success(
            request, f"{sent} demande{'s' if sent > 1 else ''} envoyée{'s' if sent > 1 else ''}"
            " : un seul e-mail et un seul lien par client, relancé automatiquement.",
        )  # fmt: skip
    if skipped:
        messages.warning(request, f"{skipped} dossier(s) sans rien à demander ou sans e-mail.")
    back = request.POST.get("retour", "")
    if back.startswith("/") and "//" not in back:
        return redirect(back)
    return redirect("conformite:board")


def unanswered(request: AppRequest) -> HttpResponse:
    """Demandes restées sans réponse 15 jours après le dernier rappel (D-055)."""
    from .services import unanswered as no_answer

    who = request.GET.get("qui", "moi")
    who = who if who in {"moi", "tous"} else "moi"
    requests = list(
        no_answer()
        .filter(client__in=_clients(request, who))
        .select_related("client", "person")
        .order_by("created_at")
    )
    log_access(request, AccessLog.Action.VIEW, None, details={"écran": "sans réponse"})
    return render(request, "documents/unanswered.html", {"requests": requests, "who": who})
