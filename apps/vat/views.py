"""Onglet « Déclaration TVA » du dossier : la grille, ses cases, l'import Intervat (D-040)."""

from __future__ import annotations

from datetime import date
from decimal import Decimal, InvalidOperation
from typing import Any

from django.contrib import messages
from django.http import HttpResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.http import require_POST

from apps.clients.models import Client
from apps.clients.views import _get_client, render_section
from apps.core.audit import log_access
from apps.core.capabilities import Capability
from apps.core.http import AppRequest
from apps.core.models import AccessLog
from apps.core.permissions import require_capability

from . import importer, services
from .intervat import IC, KIND_LABELS, VAT
from .models import COLUMN_HEADERS, Column, Status, VatFiling, VatPending

STATUS_CHOICES = list(Status.choices)


def _context(client: Client) -> dict[str, Any]:
    rows = services.grid(client)
    pending = VatPending.objects.filter(document__client=client).select_related("document")
    filings = list(client.vat_filings.order_by("-period_start"))
    return {
        "rows": rows,
        "headers": [(c.value, c.label, COLUMN_HEADERS[c]) for c in Column],
        "statuses": STATUS_CHOICES,
        "quarterly": any(r.filing.periodicity == VatFiling.Periodicity.QUARTERLY for r in rows),
        "pending": [(p, KIND_LABELS.get(p.kind, ""), filings) for p in pending],
        "kinds": [(VAT, KIND_LABELS[VAT]), (IC, KIND_LABELS[IC])],
    }


def vat_grid(request: AppRequest, pk: int) -> HttpResponse:
    return render_section(request, pk, "vat", "vat/grid.html", _context)


def _filing(request: AppRequest, pk: int, filing_id: int) -> VatFiling:
    client = _get_client(request, pk)
    return get_object_or_404(VatFiling, pk=filing_id, client=client)


def _row_response(request: AppRequest, filing: VatFiling) -> HttpResponse:
    if not request.htmx:
        return redirect("clients:vat", pk=filing.client_id)
    filing = (
        VatFiling.objects.select_related("manager", "assistant", "xml", "pdf", "ic_xml", "ic_pdf")
        .prefetch_related("cells__by")
        .get(pk=filing.pk)
    )
    return render(
        request,
        "vat/_row.html",
        {
            "row": services.row_for(filing),
            "client": filing.client,
            "can_edit": True,
            "statuses": STATUS_CHOICES,
            "quarterly": filing.periodicity == VatFiling.Periodicity.QUARTERLY,
        },
    )


@require_POST
@require_capability(Capability.CLIENTS_EDIT)
def vat_cell(request: AppRequest, pk: int, filing_id: int, column: str) -> HttpResponse:
    filing = _filing(request, pk, filing_id)
    status = request.POST.get("status", "")
    try:
        if status:
            on = request.POST.get("on") or ""
            services.set_status(
                filing,
                column,
                status,
                user=request.user,
                on=date.fromisoformat(on) if on else None,
                comment=request.POST.get("comment"),
            )
        else:
            services.set_comment(filing, column, request.POST.get("comment", ""))
    except ValueError:
        messages.error(request, "Modification refusée : case ou date invalide.")
    details = {"rubrique": "tva", "periode": filing.period_key, "case": column}
    log_access(request, AccessLog.Action.UPDATE, filing.client, details=details)
    return _row_response(request, filing)


def _amount(value: str) -> Decimal | None:
    value = value.replace(" ", "").replace(" ", "").replace(",", ".").strip()
    if not value:
        return None
    try:
        amount = Decimal(value).quantize(Decimal("0.01"))
    except InvalidOperation as exc:
        raise ValueError(value) from exc
    if amount < 0 or amount >= Decimal("1e12"):
        raise ValueError(value)
    return amount


@require_POST
@require_capability(Capability.CLIENTS_EDIT)
def vat_amounts(request: AppRequest, pk: int, filing_id: int) -> HttpResponse:
    """Grilles 71/72 (si pas d'import), acomptes et remarque de la ligne."""
    filing = _filing(request, pk, filing_id)
    fields = []
    try:
        for name in ("grid_71", "grid_72", "advance_1", "advance_2"):
            if name in request.POST:
                setattr(filing, name, _amount(request.POST[name]))
                fields.append(name)
    except ValueError:
        messages.error(request, "Montant invalide.")
        return _row_response(request, filing)
    if "remark" in request.POST:
        filing.remark = request.POST["remark"].strip()[:1000]
        fields.append("remark")
    if fields:
        filing.save(update_fields=fields)
        log_access(request, AccessLog.Action.UPDATE, filing.client,
                   details={"rubrique": "tva", "periode": filing.period_key})  # fmt: skip
    return _row_response(request, filing)


@require_POST
@require_capability(Capability.CLIENTS_EDIT)
def vat_import(request: AppRequest, pk: int) -> HttpResponse:
    """Dépôt des fichiers Intervat : chacun va dans son dossier, quel que soit l'onglet ouvert."""
    from apps.clients.views import _visible_clients

    client = _get_client(request, pk)
    uploads = request.FILES.getlist("files")[:50]
    if not uploads:
        messages.error(request, "Aucun fichier choisi.")
        return redirect("clients:vat", pk=client.pk)
    outcomes = importer.import_files(uploads, clients=_visible_clients(request), user=request.user)
    for outcome in outcomes:
        if outcome.client is not None:
            log_access(request, AccessLog.Action.IMPORT, outcome.client,
                       details={"rubrique": "tva", "niveau": outcome.level})  # fmt: skip
        where = ""
        if outcome.client is not None and outcome.client.pk != client.pk:
            where = f" → dossier {outcome.client.display_name}"
        text = f"{outcome.name} : {outcome.message}{where}"
        if outcome.level == importer.ERROR:
            messages.error(request, text)
        elif outcome.level == importer.DOUBT:
            messages.warning(request, text)
        else:
            messages.success(request, text)
    return redirect("clients:vat", pk=client.pk)


@require_POST
@require_capability(Capability.CLIENTS_EDIT)
def vat_confirm(request: AppRequest, pk: int, pending_id: int) -> HttpResponse:
    client = _get_client(request, pk)
    pending = get_object_or_404(VatPending, pk=pending_id, document__client=client)
    if request.POST.get("action") == "laisser":
        pending.delete()
        messages.success(request, "PDF laissé dans les archives TVA.")
        return redirect("clients:vat", pk=client.pk)
    filing = get_object_or_404(VatFiling, pk=request.POST.get("filing") or 0, client=client)
    try:
        importer.confirm(pending, filing, request.POST.get("kind", ""), request.user)
    except ValueError:
        messages.error(request, "Confirmation refusée.")
    else:
        log_access(request, AccessLog.Action.UPDATE, client,
                   details={"rubrique": "tva", "periode": filing.period_key})  # fmt: skip
        messages.success(request, f"PDF rangé : {filing.short_label}.")
    return redirect("clients:vat", pk=client.pk)
