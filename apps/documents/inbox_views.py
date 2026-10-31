"""Page « Déposer des documents » : le dépôt unique de tout l'outil (D-041)."""

from __future__ import annotations

from typing import Any

from django.conf import settings
from django.contrib import messages
from django.core.exceptions import PermissionDenied
from django.http import FileResponse, Http404, HttpResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
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
from .views import SAFE_HEADERS, _place_label

MAX_FILES = 50


def _items(request: AppRequest) -> list[InboxItem]:
    # Un fichier pas encore classé n'appartient à aucun dossier : seul son auteur le voit.
    return list(
        InboxItem.objects.filter(uploaded_by=request.user).select_related("duplicate_of__client")
    )


def _assistant_reads_documents() -> bool:
    from apps.ai import client as ai

    return ai.enabled() and ai.personal_data_allowed()


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
    items = _items(request)
    # Doublon d'un document qu'on ne voit plus (dossier retiré, document supprimé) : à classer.
    seen = set(visible.values_list("pk", flat=True))
    duplicates = [i for i in items if i.duplicate_of and i.duplicate_of.client_id in seen]
    context: dict[str, Any] = {
        "items": [i for i in items if i not in duplicates],
        "duplicates": duplicates,
        "vat_pending": [
            (p, KIND_LABELS.get(p.kind, ""), list(p.document.client.vat_filings.all()))
            for p in pending
        ],
        "cards": list(cards),
        "kinds": [(VAT, KIND_LABELS[VAT]), (IC, KIND_LABELS[IC])],
        "retention": settings.INBOX_RETENTION_DAYS,
        "assistant": _assistant_reads_documents(),
        "max_files": MAX_FILES,
    }
    return render(request, "documents/inbox.html", context)


def _receive(request: AppRequest) -> HttpResponse:
    uploads = request.FILES.getlist("files")
    if request.GET.get("panneau") and not 1 <= len(uploads) <= MAX_FILES:
        return HttpResponse(status=400)
    if not uploads:
        messages.error(request, "Aucun fichier choisi.")
        return redirect("depot:index")
    if len(uploads) > MAX_FILES:
        messages.error(request, f"{MAX_FILES} fichiers au maximum à la fois.")
        return redirect("depot:index")
    started = timezone.now()
    results = inbox.receive(uploads, clients=_visible_clients(request), user=request.user)
    _log_results(request, results)
    _assistant_reads_new(request, started)
    if request.GET.get("panneau"):
        # Panneau de dépôt (D-093) : une ligne par fichier, sans recharger la page.
        return render(request, "documents/_depot_lines.html", {"results": results})
    _announce(request, results)
    return redirect("depot:index")


def _assistant_reads_new(request: AppRequest, since: Any) -> None:
    """En coulisse (D-127) : chaque fichier que l'outil n'a pas su ranger est lu par
    l'assistant IA, qui propose dossier, endroit et titre. Rien n'est rangé sans un clic ;
    s'il ne répond pas, le fichier attend simplement dans « À classer »."""
    from apps.ai import client as ai
    from apps.ai import documents_assist

    if not (ai.enabled() and ai.personal_data_allowed()):
        return
    waiting = InboxItem.objects.filter(
        uploaded_by=request.user, uploaded_at__gte=since, duplicate_of__isnull=True
    )
    for item in waiting[:MAX_FILES]:
        if item.suggestion:
            continue
        try:
            proposal = documents_assist.suggest(item, _visible_clients(request), request.user)
        except ai.Unavailable:
            return  # l'assistant ne répond pas : inutile d'insister pour les suivants
        details = {"assistant IA": "proposition", "dossier": proposal.get("client")}
        log_access(request, AccessLog.Action.VIEW, item, details=details)


def _log_results(request: AppRequest, results: list[inbox.Result]) -> None:
    for result in results:
        if result.client is not None:
            log_access(request, AccessLog.Action.IMPORT, result.client,
                       details={"depot": result.level})  # fmt: skip


def _announce(request: AppRequest, results: list[inbox.Result]) -> None:
    for result in results:
        where = f" → {result.client.display_name}" if result.client is not None else ""
        text = f"{result.name} : {result.message}{where}"
        if result.level == inbox.ERROR:
            messages.error(request, text)
        elif result.level in (inbox.DOUBT, inbox.INBOX, inbox.DUPLICATE):
            messages.warning(request, text)
        else:
            messages.success(request, text)


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
def item_assist(request: AppRequest, item_id: str) -> HttpResponse:
    """« À classer » : l'assistant IA propose dossier, endroit et titre (D-121) ; l'utilisateur
    range d'un clic, ou classe lui-même."""
    from apps.ai import client as ai
    from apps.ai import documents_assist

    item = get_object_or_404(InboxItem, pk=item_id, uploaded_by=request.user)
    try:
        proposal = documents_assist.suggest(item, _visible_clients(request), request.user)
    except ai.Unavailable as error:
        messages.error(request, str(error))
    else:
        details = {"assistant IA": "proposition", "dossier": proposal.get("client")}
        log_access(request, AccessLog.Action.VIEW, item, details=details)
    return redirect("depot:index")


@require_POST
@require_capability(Capability.CLIENTS_EDIT)
def item_delete(request: AppRequest, item_id: str) -> HttpResponse:
    item = get_object_or_404(InboxItem, pk=item_id, uploaded_by=request.user)
    inbox.discard(item)
    messages.success(request, "Fichier supprimé.")
    return redirect("depot:index")


@require_GET
def item_page(request: AppRequest, item_id: str, number: int) -> HttpResponse:
    """Image d'une page d'un fichier à classer (comparaison des doublons, D-099)."""
    from . import preview

    if not request.user.has_capability(Capability.CLIENTS_EDIT):
        raise PermissionDenied
    item = get_object_or_404(InboxItem, pk=item_id, uploaded_by=request.user)
    rendered = preview.render_page(item, number)
    if rendered is None:
        raise Http404
    response = HttpResponse(rendered[0], content_type=rendered[1])
    for header, value in SAFE_HEADERS.items():
        response[header] = value
    return response


# --- Doublons (D-099) ------------------------------------------------------------------------


def _duplicate(request: AppRequest, item_id: str) -> tuple[InboxItem, Document | None]:
    """Le fichier retenu et le document déjà rangé — seulement s'il est encore visible."""
    item = get_object_or_404(InboxItem, pk=item_id, uploaded_by=request.user)
    existing = item.duplicate_of
    if existing is None or not _visible_clients(request).filter(pk=existing.client_id).exists():
        return item, None
    return item, existing


@require_capability(Capability.CLIENTS_EDIT)
@require_GET
def duplicate(request: AppRequest, item_id: str) -> HttpResponse:
    """Les deux documents côte à côte : le déjà rangé et le nouveau dépôt."""
    from . import preview, readable

    item, existing = _duplicate(request, item_id)
    if existing is None:
        messages.info(
            request, "Ce doublon n'est plus à vérifier : le fichier est dans « À classer »."
        )
        return redirect("depot:index")
    log_access(request, AccessLog.Action.VIEW, existing,
               details={"client": existing.client_id, "doublon": True})  # fmt: skip
    context = {
        "item": item,
        "existing": existing,
        "place": _place_label(existing),
        "existing_pages": preview.page_count(existing),
        "item_pages": preview.page_count(item),
        "existing_readable": readable.of(existing),
        "item_readable": readable.of(item),
    }
    return render(request, "documents/duplicate.html", context)


@require_POST
@require_capability(Capability.CLIENTS_EDIT)
def duplicate_confirm(request: AppRequest, item_id: str) -> HttpResponse:
    """« Confirmer l'import » : rangé comme un dépôt normal, en plus du document existant."""
    item = get_object_or_404(InboxItem, pk=item_id, uploaded_by=request.user,
                             duplicate_of__isnull=False)  # fmt: skip
    results = inbox.confirm_duplicate(item, clients=_visible_clients(request), user=request.user)
    _log_results(request, results)
    _announce(request, results)
    return redirect("depot:index")


@require_POST
@require_capability(Capability.CLIENTS_EDIT)
def duplicate_delete(request: AppRequest, item_id: str) -> HttpResponse:
    """« Supprimer le doublon » : seul le fichier qui vient d'être déposé est effacé ; le
    document déjà rangé n'est jamais touché."""
    item = get_object_or_404(InboxItem, pk=item_id, uploaded_by=request.user,
                             duplicate_of__isnull=False)  # fmt: skip
    name = item.original_name
    inbox.discard(item)
    messages.success(request, f"Doublon « {name} » supprimé. Le document déjà rangé est gardé.")
    return redirect("depot:index")
