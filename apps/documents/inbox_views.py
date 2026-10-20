"""Page « Déposer des documents » : le dépôt unique de tout l'outil (D-041)."""

from __future__ import annotations

from typing import Any

from django.conf import settings
from django.contrib import messages
from django.core.exceptions import PermissionDenied
from django.http import FileResponse, HttpResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.http import require_GET, require_POST

from apps.clients.views import _visible_clients
from apps.core.audit import log_access
from apps.core.capabilities import Capability
from apps.core.http import AppRequest
from apps.core.models import AccessLog
from apps.core.permissions import require_capability
from apps.vat.intervat import IC, KIND_LABELS, VAT
from apps.vat.models import VatPending

from . import inbox
from .models import Document, InboxItem
from .views import SAFE_HEADERS

MAX_FILES = 50


def _items(request: AppRequest) -> list[InboxItem]:
    # Un fichier pas encore classé n'appartient à aucun dossier : seul son auteur le voit.
    return list(InboxItem.objects.filter(uploaded_by=request.user))


@require_capability(Capability.CLIENTS_EDIT)
def index(request: AppRequest) -> HttpResponse:
    if request.method == "POST":
        return _receive(request)
    visible = _visible_clients(request)
    pending = VatPending.objects.filter(document__client__in=visible).select_related(
        "document__client"
    )
    cards = Document.objects.filter(
        client__in=visible, case="pieces-identite", review_needed=True, archived_at__isnull=True
    ).select_related("client", "person")
    context: dict[str, Any] = {
        "items": _items(request),
        "vat_pending": [
            (p, KIND_LABELS.get(p.kind, ""), list(p.document.client.vat_filings.all()))
            for p in pending
        ],
        "cards": list(cards),
        "kinds": [(VAT, KIND_LABELS[VAT]), (IC, KIND_LABELS[IC])],
        "retention": settings.INBOX_RETENTION_DAYS,
        "max_files": MAX_FILES,
    }
    return render(request, "documents/inbox.html", context)


def _receive(request: AppRequest) -> HttpResponse:
    uploads = request.FILES.getlist("files")
    if not uploads:
        messages.error(request, "Aucun fichier choisi.")
        return redirect("depot:index")
    if len(uploads) > MAX_FILES:
        messages.error(request, f"{MAX_FILES} fichiers au maximum à la fois.")
        return redirect("depot:index")
    results = inbox.receive(uploads, clients=_visible_clients(request), user=request.user)
    for result in results:
        if result.client is not None:
            log_access(request, AccessLog.Action.IMPORT, result.client,
                       details={"depot": result.level})  # fmt: skip
        where = f" → {result.client.display_name}" if result.client is not None else ""
        text = f"{result.name} : {result.message}{where}"
        if result.level == inbox.ERROR:
            messages.error(request, text)
        elif result.level in (inbox.DOUBT, inbox.INBOX):
            messages.warning(request, text)
        else:
            messages.success(request, text)
    return redirect("depot:index")


@require_GET
def item_file(request: AppRequest, item_id: str) -> FileResponse:
    if not request.user.has_capability(Capability.CLIENTS_EDIT):
        raise PermissionDenied
    item = get_object_or_404(InboxItem, pk=item_id, uploaded_by=request.user)
    log_access(request, AccessLog.Action.VIEW, None, object_type="document à classer",
               object_repr=str(item.pk))  # fmt: skip
    inline = item.content_type in ("application/pdf", "image/jpeg", "image/png")
    response = FileResponse(
        item.file.open("rb"),
        content_type=item.content_type,
        as_attachment=not inline,
        filename=item.original_name,
    )
    for header, value in SAFE_HEADERS.items():
        response[header] = value
    return response


@require_POST
@require_capability(Capability.CLIENTS_EDIT)
def item_classify(request: AppRequest, item_id: str) -> HttpResponse:
    item = get_object_or_404(InboxItem, pk=item_id, uploaded_by=request.user)
    client = _visible_clients(request).filter(pk=request.POST.get("client") or 0).first()
    if client is None:
        messages.error(request, "Choisis d'abord le dossier.")
        return redirect("depot:index")
    place = request.POST.get("place", "")
    if not place:
        # Dossier choisi : on propose maintenant les endroits de ce dossier.
        return render(
            request,
            "documents/inbox_place.html",
            {"item": item, "client": client, "places": inbox.places(client)},
        )
    try:
        document = inbox.classify(item, client, place, request.POST.get("title", ""),
                                  request.user)  # fmt: skip
    except ValueError:
        messages.error(request, "Endroit inconnu pour ce dossier.")
        return redirect("depot:index")
    log_access(request, AccessLog.Action.CREATE, document, details={"client": client.pk})
    messages.success(request, f"« {document.title} » rangé → {client.display_name}.")
    return redirect("depot:index")


@require_POST
@require_capability(Capability.CLIENTS_EDIT)
def item_delete(request: AppRequest, item_id: str) -> HttpResponse:
    item = get_object_or_404(InboxItem, pk=item_id, uploaded_by=request.user)
    inbox.discard(item)
    messages.success(request, "Fichier supprimé.")
    return redirect("depot:index")
