"""Onglet « Clôture » du dossier (D-111) et checklists communes (réglages généraux)."""

from __future__ import annotations

from datetime import date, datetime, time, timedelta
from typing import Any

from django.contrib import messages
from django.core.exceptions import PermissionDenied, ValidationError
from django.http import Http404, HttpResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils import timezone
from django.views.decorators.http import require_POST

from apps.clients.models import Client
from apps.clients.views import _get_client, render_section
from apps.core.audit import log_access
from apps.core.capabilities import Capability
from apps.core.http import AppRequest
from apps.core.models import AccessLog, User
from apps.core.permissions import require_capability
from apps.timesheet.models import TimeEntry, hours_label

from . import deposits, services
from .models import ClosingYear, Comment, CommonItem, Deposit, Kind, Part

VIEWS = ("checklist", "configurer", "historique")


def _time_defaults(user: User) -> dict[str, str]:
    """Créneau proposé par « + Temps » : à la suite de ma dernière entrée du jour, 30 minutes."""
    now = timezone.localtime()
    today = now.date()
    last = TimeEntry.objects.filter(user=user, day=today).order_by("-end").first()
    if last is not None:
        start = datetime.combine(today, last.end)
    else:
        start = now.replace(tzinfo=None, second=0, microsecond=0) - timedelta(
            minutes=30 + now.minute % 5
        )
    end = min(start + timedelta(minutes=30), datetime.combine(today, time(23, 55)))
    return {"day": f"{today:%Y-%m-%d}", "start": f"{start:%H:%M}", "end": f"{end:%H:%M}"}


def _rows(client: Client, user: User) -> list[dict[str, Any]]:
    checklists = services.has_checklists(client)  # pas pour un particulier ni un dirigeant
    accounting = services.items_for(client, Part.ACCOUNTING) if checklists else []
    manager = services.items_for(client, Part.MANAGER) if checklists else []
    years = list(
        client.closing_years.select_related(
            "manager", "assistant", "closed_by", "manager_closed_by", "ag_draft"
        )
    )
    services.add_my_time(user, years)
    kinds = deposits.kinds_for(client)
    from apps.documents import letter

    from . import ag

    ag_ready = bool(kinds) and bool(letter.ag_templates(client))
    ipp_kinds = deposits.ipp_kinds_for(client)
    waiting = deposits.waiting_requests(client) if ipp_kinds else 0
    profile = services.profile(client)
    rows = []
    for y in years:
        sheet = services.sheet(y, Part.ACCOUNTING, accounting) if checklists else None
        manager_sheet = services.sheet(y, Part.MANAGER, manager) if checklists else None
        boxes = deposits.boxes(y, kinds)
        ipp_boxes = deposits.boxes(y, ipp_kinds)
        for b in ipp_boxes:
            if b.kind == deposits.Kind.IPP_PIECES and waiting and not b.done_on:
                b.waiting = waiting
        for b in boxes:
            if b.kind == deposits.Kind.AG:
                b.can_prepare = ag_ready
                if not b.done_on and ag.waiting_signature(y):
                    b.note = "à signer"
        closed = sheet is None or (
            manager_sheet is not None and services.finished(sheet, manager_sheet)
        )
        rows.append({
            "year": y, "sheet": sheet, "manager_sheet": manager_sheet, "boxes": boxes,
            "ipp_boxes": ipp_boxes, "checklists": checklists,
            "leader": deposits.leader_fiches(client, y) if profile == "dirigeant" else [],
            "finished": closed and deposits.complete(boxes) and deposits.complete(ipp_boxes),
            # colonnes communes aux lignes (une ligne chacune)
            "cols": max(8, len(boxes), len(ipp_boxes)),  # même taille de case partout
        })  # fmt: skip
    return rows


def _part(part: str) -> str:
    if part not in Part.values:
        raise Http404
    return part


def closing_tab(request: AppRequest, pk: int) -> HttpResponse:
    def build(client: Client) -> dict[str, Any]:
        services.ensure_years(client)
        return {
            "rows": _rows(client, request.user),
            "kind": Kind(services.kind_for(client)).label,
            "checklists": services.has_checklists(client),
            "profile": services.profile(client),
            "profiles": services.PROFILES,
            "auto_profile": services.auto_profile(client) if client.is_person else "",
            "profile_manual": services.manual_profile(client),
            "customised": services.removed_for(client)
            or client.closing_items.filter(active=True).exists()
            or client.closing_changes.exclude(label="", hint="").exists(),
            "time": _time_defaults(request.user),
            "hidden": [(k, Deposit.Kind(k).label) for k in deposits.hidden_for(client)],
        }

    return render_section(request, pk, "closing", "closing/tab.html", build)


def _year(request: AppRequest, pk: int, year_id: int) -> ClosingYear:
    client = _get_client(request, pk)
    return get_object_or_404(ClosingYear, pk=year_id, client=client)


def _row_response(request: AppRequest, year: ClosingYear, error: str = "") -> HttpResponse:
    if not request.htmx:
        if error:
            messages.error(request, error)
        return redirect("clients:closing", pk=year.client_id)
    [row] = [r for r in _rows(year.client, request.user) if r["year"].pk == year.pk]
    context = {
        "row": row,
        "client": year.client,
        "can_edit": request.user.has_capability(Capability.CLIENTS_EDIT),
        "time": _time_defaults(request.user),
        "row_error": error,
    }
    return render(request, "closing/_row.html", context)


def _checklist_response(
    request: AppRequest, year: ClosingYear, part: str, view: str = "checklist", error: str = ""
) -> HttpResponse:
    client = year.client
    if not request.htmx:
        if error:
            messages.error(request, error)
        return redirect("clients:closing", pk=client.pk)
    sheet = services.sheet(year, part)
    keys = {line.item.key for line in sheet.lines}
    manager = part == Part.MANAGER
    context = {
        "client": client,
        "year": year,
        "sheet": sheet,
        "part": part,
        "part_label": "Checklist gestionnaire" if manager else "Checklist",
        "general_remark": year.manager_remark if manager else year.checklist_remark,
        "view": view if view in VIEWS else "checklist",
        "removed": services.removed_for(client, part),
        "comments": [
            c for c in year.comments.select_related("author", "resolved_by") if c.key in keys
        ],
        "ticks": [
            t for t in year.ticks.select_related("by").order_by("-on", "-pk") if t.key in keys
        ],
        "can_edit": request.user.has_capability(Capability.CLIENTS_EDIT),
        "error": error,
        "kind": Kind(services.kind_for(client, part)).label,
    }
    response = render(request, "closing/_checklist.html", context)
    if request.method == "POST":
        response["HX-Trigger"] = "documents-changed"  # la ligne se met à jour à la fermeture
    return response


def checklist(request: AppRequest, pk: int, year_id: int, part: str) -> HttpResponse:
    year = _year(request, pk, year_id)
    log_access(
        request, AccessLog.Action.VIEW, year.client,
        details={"rubrique": "cloture", "exercice": year.label, "checklist": _part(part)},
    )  # fmt: skip
    return _checklist_response(request, year, part, request.GET.get("vue", "checklist"))


def _changed(request: AppRequest, year: ClosingYear, what: str) -> None:
    details = {"rubrique": "cloture", "exercice": year.label, "action": what}
    log_access(request, AccessLog.Action.UPDATE, year.client, details=details)


@require_POST
@require_capability(Capability.CLIENTS_EDIT)
def tick(request: AppRequest, pk: int, year_id: int, part: str, key: str) -> HttpResponse:
    year = _year(request, pk, year_id)
    _part(part)
    error = ""
    try:
        services.set_tick(
            year, services.parse_key(key), request.POST.get("status", ""), request.user
        )
        _changed(request, year, "coche")
    except ValueError as exc:
        error = str(exc)
    return _checklist_response(request, year, part, error=error)


@require_POST
@require_capability(Capability.CLIENTS_EDIT)
def comment_add(request: AppRequest, pk: int, year_id: int, part: str, key: str) -> HttpResponse:
    year = _year(request, pk, year_id)
    _part(part)
    error = ""
    try:
        services.add_comment(
            year, services.parse_key(key), request.POST.get("text", ""), request.user
        )
        _changed(request, year, "commentaire")
    except ValueError as exc:
        error = str(exc)
    return _checklist_response(request, year, part, error=error)


@require_POST
@require_capability(Capability.CLIENTS_EDIT)
def comment_resolve(
    request: AppRequest, pk: int, year_id: int, part: str, comment_id: int
) -> HttpResponse:
    year = _year(request, pk, year_id)
    _part(part)
    comment = get_object_or_404(Comment, pk=comment_id, year=year, resolved_at__isnull=True)
    services.resolve(comment, request.user)
    _changed(request, year, "commentaire réglé")
    return _checklist_response(request, year, part)


@require_POST
@require_capability(Capability.CLIENTS_EDIT)
def checklist_remark(request: AppRequest, pk: int, year_id: int, part: str) -> HttpResponse:
    year = _year(request, pk, year_id)
    field = "manager_remark" if _part(part) == Part.MANAGER else "checklist_remark"
    setattr(year, field, request.POST.get("remark", "").strip()[:4000])
    year.save(update_fields=[field])
    _changed(request, year, "remarque")
    return _checklist_response(request, year, part)


@require_POST
@require_capability(Capability.CLIENTS_EDIT)
def configure(request: AppRequest, pk: int, year_id: int, part: str) -> HttpResponse:
    """Personnaliser la checklist de CE dossier (gardé pour les années suivantes)."""
    year = _year(request, pk, year_id)
    _part(part)
    client = year.client
    action = request.POST.get("action", "")
    error = ""
    try:
        if action == "ajouter":
            services.add(client, request.POST.get("label", ""), request.POST.get("hint", ""), part)
        elif action == "remettre":
            services.restore(client, int(request.POST.get("item", "0") or 0))
        else:
            key = services.parse_key(request.POST.get("key", ""))
            if action == "renommer":
                services.rename(
                    client, key, request.POST.get("label", ""), request.POST.get("hint", ""), part
                )
            elif action == "retirer":
                services.remove(client, key, part)
            elif action in ("monter", "descendre"):
                services.move(client, key, -1 if action == "monter" else 1, part)
            else:
                raise ValueError("Action inconnue.")
        _changed(request, year, f"checklist du dossier : {action}")
    except (ValueError, CommonItem.DoesNotExist):
        error = "Modification refusée : vérifiez le nom du champ."
    return _checklist_response(request, year, part, "configurer", error)


@require_POST
@require_capability(Capability.CLIENTS_EDIT)
def accounting_close(request: AppRequest, pk: int, year_id: int, part: str) -> HttpResponse:
    """Case « Clôture comptable » ou « Clôture gestionnaire » : un clic coche ou décoche."""
    year = _year(request, pk, year_id)
    manager = _part(part) == Part.MANAGER
    current = year.manager_closed_on if manager else year.closed_on
    services.set_closed(year, current is None, request.user, part)
    _changed(request, year, "clôture gestionnaire" if manager else "clôture comptable")
    return _row_response(request, year)


@require_POST
@require_capability(Capability.CLIENTS_EDIT)
def row_remark(request: AppRequest, pk: int, year_id: int) -> HttpResponse:
    year = _year(request, pk, year_id)
    year.remark = request.POST.get("remark", "").strip()[:1000]
    year.save(update_fields=["remark"])
    _changed(request, year, "remarque de la ligne")
    return _row_response(request, year)


@require_POST
def add_time(request: AppRequest, pk: int, year_id: int) -> HttpResponse:
    """« + Temps » : une entrée dans MA journée, rattachée à l'exercice (c'est mon temps)."""
    year = _year(request, pk, year_id)
    entry = TimeEntry(
        user=request.user,
        client=year.client,
        closing_year=year,
        activity=TimeEntry.Activity.CLOSING,
        description=(request.POST.get("description") or f"Clôture {year.label}")[:200],
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
    if not request.htmx and not error:
        messages.success(request, f"Ajouté à ma journée : {hours_label(entry.minutes)}.")
    return _row_response(request, year, error)


# --- Cases de dépôt (D-113) -------------------------------------------------------------------


@require_POST
@require_capability(Capability.CLIENTS_EDIT)
def deposit(request: AppRequest, pk: int, year_id: int, kind: str) -> HttpResponse:
    year = _year(request, pk, year_id)
    if kind not in Deposit.Kind.values:
        raise Http404
    action = request.POST.get("action", "")
    if action in ("cocher", "decocher"):
        deposits.set_done(year, kind, action == "cocher", request.user)
    elif action == "retirer":
        deposits.hide(year.client, kind, True)
    _changed(request, year, f"dépôt {kind} : {action}")
    return _row_response(request, year)


@require_capability(Capability.CLIENTS_EDIT)
def ag_prepare(request: AppRequest, pk: int, year_id: int) -> HttpResponse:
    """Préparer le PV d'AG de l'exercice sur un modèle du cabinet (D-120)."""
    from datetime import date as _date
    from datetime import time as _time

    from apps.documents import letter

    from . import ag

    year = _year(request, pk, year_id)
    client = year.client
    templates = letter.ag_templates(client)
    chosen = next(
        (t for t in templates if str(t.pk) == request.POST.get("modele", "")),
        templates[0] if templates else None,
    )
    questions = letter.questions(chosen) if chosen is not None else []
    saved = year.ag_answers or {}
    errors: list[str] = []
    if request.method == "POST" and chosen is not None:
        answers = {key: request.POST.get(key, "").strip()[:300] for key, _ in questions}
        try:
            day = _date.fromisoformat(request.POST.get("date", ""))
            start = _time.fromisoformat(request.POST.get("debut", ""))
            end = _time.fromisoformat(request.POST.get("fin", ""))
        except ValueError:
            errors.append("la date et les heures de l'AG")
            day, start, end = ag.today(), _time(18), _time(18, 30)
        dividend = request.POST.get("dividende") == "oui"
        skipped = {"sans_dividende"} if dividend else {"dividende"}  # passage retiré du PV
        errors += [
            label
            for key, label in questions
            if key.startswith("trou:")
            and not answers[key]
            and letter.condition_of(chosen, key) not in skipped
        ]
        if errors:
            messages.error(request, "À compléter : " + ", ".join(errors) + ".")
        else:
            ctx = ag.context(year, day, start, end, request.POST.get("dividende") == "oui",
                             request.POST.get("autres", "").strip()[:2000])  # fmt: skip
            document = ag.prepare(year, chosen, answers, ctx, request.user)
            log_access(request, AccessLog.Action.CREATE, document, details={"généré": "pv_ag"})
            return redirect("clients:document_viewer_page", pk=client.pk, document_id=document.pk)
    values = request.POST if request.method == "POST" else {
        **{k: v for k, v in saved.items() if not k.startswith("ctx:")},
        "date": _iso(saved.get("ctx:date", "")) or _deadline(year).isoformat(),
        "debut": saved.get("ctx:debut", "18h00").replace("h", ":"),
        "fin": saved.get("ctx:fin", "18h30").replace("h", ":"),
        "dividende": saved.get("ctx:dividende", "oui" if year.dividend else "non"),
        "autres": saved.get("ctx:autres", ""),
    }  # fmt: skip

    def build(c: Client) -> dict[str, Any]:
        return {
            "year": year, "templates": templates, "chosen": chosen, "questions": questions,
            "values": values, "known": ag.known(c),
            "others": chosen is not None and ag.uses_others(chosen),
            "conditional": {
                key: letter.condition_of(chosen, key) for key, _ in questions
            } if chosen is not None else {},
        }  # fmt: skip

    return render_section(request, pk, "closing", "closing/ag_prepare.html", build)


def _deadline(year: ClosingYear) -> date:
    """Date proposée : le dernier jour du 6e mois après la clôture (délai légal de l'AG)."""
    import calendar

    month = year.end.month + 6
    y, m = year.end.year + (month - 1) // 12, (month - 1) % 12 + 1
    return date(y, m, calendar.monthrange(y, m)[1])


def _iso(day: str) -> str:
    """« 30/06/2026 » → « 2026-06-30 » (champ date du formulaire)."""
    parts = day.split("/")
    return f"{parts[2]}-{parts[1]}-{parts[0]}" if len(parts) == 3 else ""


@require_POST
@require_capability(Capability.CLIENTS_EDIT)
def profile(request: AppRequest, pk: int) -> HttpResponse:
    """Profil IPP d'une personne (D-118) : particulier, indépendant, dirigeant ou automatique."""
    client = _get_client(request, pk)
    if not client.is_person:
        raise Http404
    services.set_profile(client, request.POST.get("profil", ""), request.user)
    details = {"rubrique": "cloture", "profil": request.POST.get("profil", "") or "auto"}
    log_access(request, AccessLog.Action.UPDATE, client, details=details)
    return redirect("clients:closing", pk=client.pk)


@require_POST
@require_capability(Capability.CLIENTS_EDIT)
def dividend(request: AppRequest, pk: int, year_id: int) -> HttpResponse:
    """« Dividende décidé à l'AG ? » (D-115) : oui → case Précompte mobilier."""
    year = _year(request, pk, year_id)
    value = {"oui": True, "non": False}.get(request.POST.get("dividende", ""))
    deposits.set_dividend(year, value, request.user)
    _changed(request, year, f"dividende : {request.POST.get('dividende', '')}")
    return _row_response(request, year)


@require_POST
@require_capability(Capability.CLIENTS_EDIT)
def deposit_file(request: AppRequest, pk: int, year_id: int, kind: str) -> HttpResponse:
    year = _year(request, pk, year_id)
    if kind not in Deposit.Kind.values:
        raise Http404
    upload = request.FILES.get("fichier")
    error = ""
    if upload is None:
        error = "Choisissez un fichier."
    else:
        try:
            deposits.add_file(year, kind, upload, request.user)
            _changed(request, year, f"dépôt {kind} : fichier")
        except ValidationError as exc:
            error = " ".join(exc.messages)
    return _row_response(request, year, error)


@require_POST
@require_capability(Capability.CLIENTS_EDIT)
def deposit_restore(request: AppRequest, pk: int) -> HttpResponse:
    client = _get_client(request, pk)
    kind = request.POST.get("kind", "")
    if kind in Deposit.Kind.values:
        deposits.hide(client, kind, False)
        details = {"rubrique": "cloture", "action": f"case {kind} remise"}
        log_access(request, AccessLog.Action.UPDATE, client, details=details)
    return redirect("clients:closing", pk=client.pk)


# --- Réglages généraux : les checklists communes ------------------------------------------------


def common_lists(request: AppRequest) -> HttpResponse:
    """Les checklists communes à tous les dossiers (administrateurs)."""
    if not request.user.is_staff:
        raise PermissionDenied
    kind = request.GET.get("liste") or request.POST.get("liste") or Kind.VAT
    if kind not in Kind.values:
        kind = Kind.VAT
    if request.method == "POST":
        action = request.POST.get("action", "")
        try:
            if action == "ajouter":
                services.common_add(
                    kind, request.POST.get("label", ""), request.POST.get("hint", "")
                )
            else:
                item = get_object_or_404(
                    CommonItem, pk=int(request.POST.get("item", "0") or 0), kind=kind, active=True
                )
                if action == "renommer":
                    label = request.POST.get("label", "").strip()[:80]
                    if not label:
                        raise ValueError
                    item.label, item.hint = label, request.POST.get("hint", "").strip()[:200]
                    item.save()
                elif action == "supprimer":
                    item.active = False
                    item.save(update_fields=["active"])
                elif action in ("monter", "descendre"):
                    services.common_move(item, -1 if action == "monter" else 1)
            details = {"réglage": "checklist commune", "liste": kind, "action": action}
            log_access(request, AccessLog.Action.UPDATE, request.user, details=details)
        except ValueError:
            messages.error(request, "Modification refusée : le nom du champ est obligatoire.")
        return redirect(f"{reverse('closing:common')}?liste={kind}")
    context = {
        "kinds": Kind.choices,
        "kind": kind,
        "kind_label": Kind(kind).label,
        "items": list(CommonItem.objects.filter(kind=kind, active=True)),
    }
    return render(request, "closing/common.html", context)
