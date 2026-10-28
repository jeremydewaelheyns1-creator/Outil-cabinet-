"""Corbeille des dossiers : sélectionner, confirmer, retrouver, réactiver (D-095)."""

from __future__ import annotations

from django.contrib import messages
from django.core.exceptions import PermissionDenied
from django.core.paginator import Paginator
from django.http import HttpResponse
from django.shortcuts import redirect, render
from django.views.decorators.http import require_POST

from apps.core.audit import log_access
from apps.core.http import AppRequest
from apps.core.models import AccessLog

from . import trash
from .models import Client

MAX_AT_ONCE = 200


def _staff(request: AppRequest) -> None:
    if not request.user.is_staff:
        raise PermissionDenied


def _ids(request: AppRequest) -> list[int]:
    return [int(v) for v in request.POST.getlist("client") if v.isdigit()][:MAX_AT_ONCE]


@require_POST
def trash_put(request: AppRequest) -> HttpResponse:
    """1er clic : récapitulatif « êtes-vous sûr ? » ; 2e clic : à la corbeille."""
    _staff(request)
    chosen = list(Client.objects.visible_to(request.user).filter(pk__in=_ids(request)))
    if not chosen:
        messages.error(request, "Cochez d'abord les dossiers à supprimer.")
        return redirect("clients:list")
    if request.POST.get("confirme") != "oui":
        return render(request, "clients/trash_confirm.html", {"chosen": chosen})
    count = trash.to_trash(chosen, user=request.user)
    for client in chosen:
        log_access(request, AccessLog.Action.DELETE, client, details={"corbeille": "mis"})
    them = "les" if count > 1 else "le"
    messages.success(
        request,
        f"{count} dossier{'s' if count > 1 else ''} mis à la corbeille. Vous pouvez {them} "
        f"retrouver et {them} réactiver dans Clients › Corbeille.",
    )
    return redirect("clients:list")


def trash_list(request: AppRequest) -> HttpResponse:
    _staff(request)
    q = request.GET.get("q", "").strip()
    clients = (
        Client.objects.in_trash_visible_to(request.user)
        .select_related("deleted_by", "portfolio")
        .order_by("-deleted_at")
    )
    if q:
        clients = clients.search(q)
    page = Paginator(clients, 50).get_page(request.GET.get("page"))
    return render(request, "clients/trash.html", {"page": page, "q": q})


@require_POST
def trash_restore(request: AppRequest) -> HttpResponse:
    _staff(request)
    chosen = list(Client.objects.in_trash_visible_to(request.user).filter(pk__in=_ids(request)))
    count = trash.restore(chosen, user=request.user)
    for client in chosen:
        log_access(request, AccessLog.Action.UPDATE, client, details={"corbeille": "réactivé"})
    if count:
        messages.success(
            request,
            f"{count} dossier{'s' if count > 1 else ''} réactivé{'s' if count > 1 else ''} : "
            "tout est revenu tel quel.",
        )
    else:
        messages.error(request, "Cochez d'abord les dossiers à réactiver.")
    return redirect("clients:trash")
