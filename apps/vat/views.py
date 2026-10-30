"""Onglet « Déclaration TVA » du dossier : la grille, ses cases, l'import Intervat (D-040)."""

from __future__ import annotations

from datetime import date, datetime, time, timedelta
from decimal import Decimal, InvalidOperation
from typing import Any

from django.contrib import messages
from django.core.exceptions import ValidationError
from django.http import HttpResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils import timezone
from django.views.decorators.http import require_POST

from apps.clients.models import Client
from apps.clients.views import _get_client, render_section
from apps.core import accueil
from apps.core.audit import log_access
from apps.core.capabilities import Capability
from apps.core.http import AppRequest
from apps.core.models import AccessLog, User
from apps.core.permissions import require_capability
from apps.outlook import graph
from apps.timesheet.models import TimeEntry, hours_label

from . import board, importer, mail, services
from .models import COLUMN_HEADERS, Column, Status, VatFiling, VatMessage, VatPending

# Choix proposés en cliquant sur une case (demande de Jeremy). Recliquer sur l'état en cours
# vide la case.
OFFERED = (Status.DONE, Status.IN_PROGRESS, Status.WARNING, Status.NOT_NEEDED)
STATUS_CHOICES = [(s.value, s.label) for s in OFFERED]
ACCEPTED = {*(s.value for s in OFFERED), Status.TODO.value}


def _context(client: Client, user: User) -> dict[str, Any]:
    rows = services.grid(client)
    services.add_my_time(user, [r.filing for r in rows])
    return {
        "rows": rows,
        "headers": [(c.value, c.label, COLUMN_HEADERS[c]) for c in Column],
        "statuses": STATUS_CHOICES,
        "quarterly": any(r.filing.periodicity == VatFiling.Periodicity.QUARTERLY for r in rows),
        "time": _time_defaults(user),
    }


def vat_grid(request: AppRequest, pk: int) -> HttpResponse:
    return render_section(
        request, pk, "vat", "vat/grid.html", lambda client: _context(client, request.user)
    )


def _filing(request: AppRequest, pk: int, filing_id: int) -> VatFiling:
    client = _get_client(request, pk)
    return get_object_or_404(VatFiling, pk=filing_id, client=client)


def _row_response(request: AppRequest, filing: VatFiling) -> HttpResponse:
    if request.POST.get("vue") == "echeances":
        return _card_response(request, filing)
    if not request.htmx:
        return redirect("clients:vat", pk=filing.client_id)
    filing = (
        VatFiling.objects.select_related("manager", "assistant", "xml", "pdf", "ic_xml", "ic_pdf")
        .prefetch_related("cells__by", "messages")
        .get(pk=filing.pk)
    )
    services.add_my_time(request.user, [filing])
    return render(
        request,
        "vat/_row.html",
        {
            "row": services.row_for(filing),
            "client": filing.client,
            "can_edit": request.user.has_capability(Capability.CLIENTS_EDIT),
            "time": _time_defaults(request.user),
            "time_error": getattr(request, "time_error", ""),
            "statuses": STATUS_CHOICES,
            "quarterly": filing.periodicity == VatFiling.Periodicity.QUARTERLY,
        },
    )


@require_POST
@require_capability(Capability.CLIENTS_EDIT)
def vat_cell(request: AppRequest, pk: int, filing_id: int, column: str) -> HttpResponse:
    filing = _filing(request, pk, filing_id)
    status = request.POST.get("status", "")
    if status and status not in ACCEPTED:
        status = ""
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
def vat_confirm(request: AppRequest, pk: int, pending_id: int) -> HttpResponse:
    client = _get_client(request, pk)
    pending = get_object_or_404(VatPending, pk=pending_id, document__client=client)
    if request.POST.get("action") == "laisser":
        pending.delete()
        messages.success(request, "PDF laissé dans les archives TVA.")
        return redirect("depot:index")
    filing = get_object_or_404(VatFiling, pk=request.POST.get("filing") or 0, client=client)
    try:
        importer.confirm(pending, filing, request.POST.get("kind", ""), request.user)
    except ValueError:
        messages.error(request, "Confirmation refusée.")
    else:
        log_access(request, AccessLog.Action.UPDATE, client,
                   details={"rubrique": "tva", "periode": filing.period_key})  # fmt: skip
        messages.success(request, f"PDF rangé : {filing.short_label}.")
    return redirect("depot:index")


def _mail_response(request: AppRequest, filing: VatFiling, message: VatMessage,
                   error: str = "") -> HttpResponse:  # fmt: skip
    response = render(
        request,
        "vat/_mail.html",
        {
            "client": filing.client,
            "filing": filing,
            "message": message,
            "error": error,
            "addresses": mail.addresses(filing),
            "mailbox": graph.mailbox_for(request.user),
            "outlook_configured": graph.configured(),
            "documents": message.kind == VatMessage.Kind.DOCUMENTS,
            "action_url": reverse(
                "clients:vat_docs_mail"
                if message.kind == VatMessage.Kind.DOCUMENTS
                else "clients:vat_mail",
                args=[filing.client_id, filing.pk],
            ),
        },
    )
    if message.sent_at is not None:
        response["HX-Trigger"] = "documents-changed"  # la grille se met à jour à la fermeture
    return response


@require_capability(Capability.CLIENTS_EDIT)
def vat_mail(request: AppRequest, pk: int, filing_id: int) -> HttpResponse:
    """E-mail au client : proposé par l'outil, relu et modifiable, envoyé sur clic (D-042)."""
    return _mail(request, pk, filing_id, VatMessage.Kind.DECLARATION)


@require_capability(Capability.CLIENTS_EDIT)
def vat_docs_mail(request: AppRequest, pk: int, filing_id: int) -> HttpResponse:
    """Demande des documents pas encore reçus : jamais automatique, sur clic (D-088)."""
    return _mail(request, pk, filing_id, VatMessage.Kind.DOCUMENTS)


def _mail(request: AppRequest, pk: int, filing_id: int, kind: str) -> HttpResponse:
    filing = _filing(request, pk, filing_id)
    message = mail.draft(filing, request.user, kind)
    if request.method != "POST":
        log_access(request, AccessLog.Action.VIEW, filing.client,
                   details={"rubrique": "tva", "email": filing.period_key})  # fmt: skip
        return _mail_response(request, filing, message)
    if message.sent_at is None:
        if request.POST.get("action") == "recompose":
            message.subject, message.body = mail.compose(filing, request.user, kind)
        else:
            message.to = request.POST.get("to", "").strip()[:254]
            message.subject = request.POST.get("subject", "").strip()[:255] or message.subject
            message.body = request.POST.get("body", "").strip() or message.body
            message.attach_pdf = request.POST.get("attach_pdf") == "1"
        if message.to and message.to not in mail.addresses(filing):
            message.to = mail.recipient(filing)
            return _mail_response(request, filing, message,
                                  "Cette adresse n'est pas sur la fiche du client.")  # fmt: skip
        message.save()
        if request.POST.get("action") == "send":
            try:
                mail.send(message, request.user)
            except ValueError as error:
                return _mail_response(request, filing, message, str(error))
            log_access(request, AccessLog.Action.UPDATE, filing.client,
                       details={"rubrique": "tva", "email envoyé": filing.period_key})  # fmt: skip
    return _mail_response(request, filing, message)


# --- « Mes déclarations TVA » (D-109) ----------------------------------------------------------


def _time_defaults(user: User) -> dict[str, str]:
    """Créneau proposé par « + Temps » : à la suite de ma dernière entrée du jour, 30 minutes."""
    now = timezone.localtime()
    today = now.date()
    last = TimeEntry.objects.filter(user=user, day=today).order_by("-end").first()
    if last is not None:
        start = datetime.combine(today, last.end)
    else:
        start = now.replace(second=0, microsecond=0) - timedelta(minutes=30 + now.minute % 5)
    end = min(start + timedelta(minutes=30), datetime.combine(today, time(23, 55), start.tzinfo))
    return {"day": f"{today:%Y-%m-%d}", "start": f"{start:%H:%M}", "end": f"{end:%H:%M}"}


def _board_context(request: AppRequest) -> dict[str, Any]:
    return {
        "can_edit": request.user.has_capability(Capability.CLIENTS_EDIT),
        "statuses": STATUS_CHOICES,
        "time": _time_defaults(request.user),
    }


def my_vat(request: AppRequest) -> HttpResponse:
    """La page ouverte par « Ouvrir mes échéances » de l'Accueil pendant le mois TVA."""
    today = timezone.localdate()
    data = board.build(request.user, today)
    wanted = request.GET.get("etat", "")
    if wanted not in board.FILTERS:
        wanted = ""
    context = {
        **_board_context(request),
        "board": data,
        "campaign": data.campaign,
        "wanted": wanted,
        "filters": [(key, label, data.count(key)) for key, label in board.FILTERS.items()],
        "groups": data.groups(wanted),
        "deadline_label": accueil.long_date(data.campaign.deadline) if data.campaign else "",
        "back": request.get_full_path(),
    }
    return render(request, "vat/board.html", context)


def _card_response(request: AppRequest, filing: VatFiling) -> HttpResponse:
    if not request.htmx:
        return redirect("tasks:vat_board")
    filing = (
        VatFiling.objects.select_related(
            "client", "task", "xml", "pdf", "ic_xml", "ic_pdf", "manager", "assistant"
        )
        .prefetch_related("cells__by", "messages")
        .get(pk=filing.pk)
    )
    card = board.card_for(filing, request.user, timezone.localdate())
    back = request.POST.get("retour", "")
    context = {
        **_board_context(request),
        "card": card,
        "time_error": getattr(request, "time_error", ""),
        "back": back if back.startswith("/") and "//" not in back else reverse("tasks:vat_board"),
    }
    return render(request, "vat/_board_card.html", context)


@require_POST
def vat_time(request: AppRequest, pk: int, filing_id: int) -> HttpResponse:
    """« + Temps » sur une ligne TVA : une entrée dans MA journée, rattachée à la déclaration
    (D-110). Pas besoin du droit de modifier la fiche : c'est mon temps."""
    filing = _filing(request, pk, filing_id)
    entry = TimeEntry(
        user=request.user,
        client=filing.client,
        vat_filing=filing,
        activity=TimeEntry.Activity.VAT,
        description=(request.POST.get("description") or f"TVA {filing.short_label}")[:200],
    )
    error = ""
    try:
        entry.day = date.fromisoformat(request.POST.get("day", ""))
        entry.start = time.fromisoformat(request.POST.get("start", ""))
        entry.end = time.fromisoformat(request.POST.get("end", ""))
        entry.full_clean()
        entry.save()
    except ValueError:
        error = "Jour ou heure invalide."
    except ValidationError as exc:
        error = " ".join(exc.messages)
    if not request.htmx:
        if error:
            messages.error(request, f"Rien n'a été enregistré : {error}")
        else:
            messages.success(request, f"Ajouté à ma journée : {hours_label(entry.minutes)}.")
        back = request.POST.get("retour", "")
        if back.startswith("/") and "//" not in back:
            return redirect(back)
        return redirect("clients:vat", pk=filing.client_id)
    request.time_error = error  # type: ignore[attr-defined]
    return _row_response(request, filing)
