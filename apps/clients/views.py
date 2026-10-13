"""Écrans des clients : liste, fiche, création, modification, relations, équipe."""

from __future__ import annotations

import io
from typing import Any

from django.contrib import messages
from django.core.exceptions import PermissionDenied
from django.core.paginator import Paginator
from django.db.models import Q, QuerySet
from django.http import HttpResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.views.decorators.http import require_POST
from openpyxl import Workbook

from apps.bce import services as bce
from apps.core import events
from apps.core.audit import log_access
from apps.core.capabilities import Capability
from apps.core.http import AppRequest
from apps.core.models import AccessLog, Portfolio, events_for
from apps.core.permissions import require_capability
from apps.integrations import vies
from apps.integrations.models import VatCheck

from .forms import AssignmentForm, ClientForm, ContactPointForm, RelationForm
from .identifiers import format_enterprise_number
from .models import Client, ClientQuerySet, ContactPoint, Relation
from .services import ubo

PAGE_SIZE = 50
STATUS_FILTERS = {
    "active": Client.Status.ACTIVE,
    "prospect": Client.Status.PROSPECT,
    "former": Client.Status.FORMER,
}


def _visible_clients(request: AppRequest) -> ClientQuerySet:
    return Client.objects.visible_to(request.user)


def _get_client(request: AppRequest, pk: int) -> Client:
    return get_object_or_404(_visible_clients(request).select_related("portfolio"), pk=pk)


def _require(request: AppRequest, capability: Capability) -> None:
    if not request.user.has_capability(capability):
        raise PermissionDenied


# --- Liste ----------------------------------------------------------------------------------


def _filtered(request: AppRequest) -> tuple[ClientQuerySet, dict[str, str]]:
    filters = {
        "q": request.GET.get("q", "").strip(),
        "statut": request.GET.get("statut", "active"),
        "type": request.GET.get("type", ""),
        "portefeuille": request.GET.get("portefeuille", ""),
    }
    clients = _visible_clients(request).select_related("portfolio")
    if filters["q"]:
        clients = clients.search(filters["q"])
    if filters["statut"] in STATUS_FILTERS:
        clients = clients.filter(status=STATUS_FILTERS[filters["statut"]])
    if filters["type"] in Client.Kind.values:
        clients = clients.filter(kind=filters["type"])
    if filters["portefeuille"].isdigit():
        clients = clients.filter(portfolio_id=int(filters["portefeuille"]))
    return clients, filters


def client_list(request: AppRequest) -> HttpResponse:
    clients, filters = _filtered(request)
    page = Paginator(clients, PAGE_SIZE).get_page(request.GET.get("page"))
    context = {
        "page": page,
        "filters": filters,
        "kinds": Client.Kind.choices,
        "portfolios": Portfolio.objects.visible_to(request.user),
        "can_export": request.user.has_capability(Capability.DATA_EXPORT),
        "can_edit": request.user.has_capability(Capability.CLIENTS_EDIT),
    }
    if request.htmx and request.htmx.target == "resultats":
        return render(request, "clients/_list_results.html", context)
    return render(request, "clients/list.html", context)


@require_capability(Capability.DATA_EXPORT)
def client_export(request: AppRequest) -> HttpResponse:
    clients, filters = _filtered(request)
    workbook = Workbook()
    sheet = workbook.active
    assert sheet is not None  # noqa: S101 (classeur neuf : la feuille existe toujours)
    sheet.title = "Clients"
    headers = [
        "Référence",
        "Nom",
        "Prénom",
        "Type",
        "Statut",
        "Portefeuille",
        "N° d'entreprise",
        "Forme juridique",
        "Rue",
        "Numéro",
        "Boîte",
        "Code postal",
        "Localité",
        "Pays",
        "Langue",
        "Statut TVA",
        "Périodicité TVA",
        "Clôture",
    ]
    sheet.append(headers)
    count = 0
    for c in clients.iterator(chunk_size=500):
        sheet.append(
            [
                c.reference or "",
                c.name,
                c.first_name,
                c.get_kind_display(),
                c.get_status_display(),
                c.portfolio.name,
                c.enterprise_number_display,
                c.legal_form,
                c.street,
                c.house_number,
                c.box,
                c.postal_code,
                c.city,
                c.country,
                c.get_language_display(),
                c.get_vat_status_display() if c.vat_status else "",
                c.get_vat_periodicity_display() if c.vat_periodicity else "",
                c.fiscal_year_end_display,
            ]
        )
        count += 1
    buffer = io.BytesIO()
    workbook.save(buffer)
    log_access(
        request,
        AccessLog.Action.EXPORT,
        object_type="clients.client",
        object_repr=f"Export de {count} clients",
        details={"filtres": filters, "lignes": count},
    )
    response = HttpResponse(
        buffer.getvalue(),
        content_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    )
    stamp = timezone.localtime().strftime("%Y-%m-%d")
    response["Content-Disposition"] = f'attachment; filename="clients-{stamp}.xlsx"'
    return response


def client_picker(request: AppRequest) -> HttpResponse:
    """Résultats de recherche à cocher (choix d'une fiche liée)."""
    query = request.GET.get("q", "").strip()
    exclude = request.GET.get("exclure", "")
    results: list[Client] = []
    if len(query) >= 2:
        matches = _visible_clients(request).search(query)
        if exclude.isdigit():
            matches = matches.exclude(pk=int(exclude))
        results = list(matches[:15])
    return render(
        request,
        "clients/_picker_results.html",
        {"results": results, "field_name": request.GET.get("champ", "other"), "query": query},
    )


# --- Fiche ----------------------------------------------------------------------------------


def _split_relations(
    request: AppRequest, relations: QuerySet[Relation], other_side: str
) -> dict[str, Any]:
    visible = set(Portfolio.objects.visible_to(request.user).values_list("pk", flat=True))
    today = timezone.localdate()
    current, past, hidden = [], [], 0
    for relation in relations:
        other: Client = getattr(relation, other_side)
        if other.portfolio_id not in visible:
            hidden += 1
            continue
        if relation.end_date and relation.end_date < today:
            past.append(relation)
        else:
            current.append(relation)
    return {"current": current, "past": past, "hidden": hidden}


def client_detail(request: AppRequest, pk: int) -> HttpResponse:
    client = _get_client(request, pk)
    log_access(request, AccessLog.Action.VIEW, client)
    record = bce.lookup(client.enterprise_number) if client.enterprise_number else None
    context = {
        "client": client,
        "contacts": client.contacts.all(),
        "contact_form": ContactPointForm(),
        "as_entity": _split_relations(
            request, client.relations_as_entity.select_related("person"), "person"
        ),
        "as_person": _split_relations(
            request, client.relations_as_person.select_related("entity"), "entity"
        ),
        "assignments": client.assignments.select_related("user"),
        "ubo": None if client.is_person else ubo.analyse(client),
        "bce_record": record,
        "bce_differences": bce.differences(client, record) if record else [],
        "bce_has_data": bce.has_data(),
        "vat_checks": client.vat_checks.all()[:3],
        "events": events_for(client).select_related("actor")[:10],
        "can_edit": request.user.has_capability(Capability.CLIENTS_EDIT),
        "can_see_sensitive": request.user.has_capability(Capability.CLIENTS_SENSITIVE),
    }
    return render(request, "clients/detail.html", context)


@require_POST
@require_capability(Capability.CLIENTS_SENSITIVE)
def reveal_national_number(request: AppRequest, pk: int) -> HttpResponse:
    client = _get_client(request, pk)
    log_access(request, AccessLog.Action.REVEAL, client, details={"champ": "numéro national"})
    return render(request, "clients/_national_number.html", {"client": client})


def _history_rows(client: Client) -> list[dict[str, Any]]:
    rows = []
    records = list(client.history.select_related("history_user")[:100])
    for record in records:
        changes = []
        previous = record.prev_record
        if previous is not None:
            delta = record.diff_against(previous, excluded_fields=["updated_at", "bce_synced_at"])
            for change in delta.changes:
                field = Client._meta.get_field(change.field)
                old, new = change.old, change.new
                if change.field == "national_number":
                    old = "•••" if old else ""
                    new = "•••" if new else ""
                changes.append(
                    {"label": getattr(field, "verbose_name", change.field), "old": old, "new": new}
                )
        rows.append({"record": record, "changes": changes, "created": previous is None})
    return rows


def client_history(request: AppRequest, pk: int) -> HttpResponse:
    client = _get_client(request, pk)
    return render(
        request, "clients/history.html", {"client": client, "rows": _history_rows(client)}
    )


# --- Création et modification ---------------------------------------------------------------


def _initial_from_bce(number: str) -> dict[str, Any]:
    record = bce.lookup(number)
    if record is None:
        return {"enterprise_number": format_enterprise_number(number)}
    initial: dict[str, Any] = bce.proposed_values(record)
    initial["enterprise_number"] = format_enterprise_number(number)
    initial["kind"] = record.client_kind
    return initial


@require_capability(Capability.CLIENTS_EDIT)
def client_create(request: AppRequest) -> HttpResponse:
    if request.method == "POST":
        form = ClientForm(request.POST, user=request.user)
        if form.is_valid():
            client = form.save()
            log_access(request, AccessLog.Action.CREATE, client)
            events.emit("client.created", subject=client, actor=request.user)
            messages.success(request, f"Fiche « {client} » créée.")
            return redirect(client)
    else:
        number = request.GET.get("bce", "")
        initial = _initial_from_bce(number) if number.isdigit() and len(number) == 10 else {}
        form = ClientForm(initial=initial, user=request.user)
    return render(request, "clients/form.html", {"form": form, "bce_has_data": bce.has_data()})


@require_capability(Capability.CLIENTS_EDIT)
def client_edit(request: AppRequest, pk: int) -> HttpResponse:
    client = _get_client(request, pk)
    previous_number = client.enterprise_number
    if request.method == "POST":
        form = ClientForm(request.POST, instance=client, user=request.user)
        if form.is_valid():
            client = form.save()
            changed = [f for f in form.changed_data if f != "new_national_number"]
            if form.cleaned_data.get("new_national_number"):
                changed.append("national_number")
            log_access(request, AccessLog.Action.UPDATE, client, details={"champs": changed})
            if changed:
                events.emit(
                    "client.updated",
                    subject=client,
                    actor=request.user,
                    payload={"fields": changed},
                )
            if client.enterprise_number and client.enterprise_number != previous_number:
                events.emit("client.enterprise_number_changed", subject=client, actor=request.user)
            messages.success(request, "Modifications enregistrées.")
            return redirect(client)
    else:
        form = ClientForm(
            instance=client,
            initial={"enterprise_number": client.enterprise_number_display},
            user=request.user,
        )
    return render(request, "clients/form.html", {"form": form, "client": client})


# --- Coordonnées ----------------------------------------------------------------------------


@require_POST
@require_capability(Capability.CLIENTS_EDIT)
def contact_add(request: AppRequest, pk: int) -> HttpResponse:
    client = _get_client(request, pk)
    form = ContactPointForm(request.POST, instance=ContactPoint(client=client))
    if form.is_valid():
        contact = form.save()
        if contact.is_primary:
            client.contacts.filter(kind=contact.kind).exclude(pk=contact.pk).update(
                is_primary=False
            )
        messages.success(request, "Coordonnée ajoutée.")
    else:
        errors = "; ".join(str(e) for errs in form.errors.values() for e in errs)
        messages.error(request, f"Coordonnée non ajoutée : {errors}")
    return redirect(client)


@require_POST
@require_capability(Capability.CLIENTS_EDIT)
def contact_delete(request: AppRequest, pk: int, contact_pk: int) -> HttpResponse:
    client = _get_client(request, pk)
    get_object_or_404(client.contacts, pk=contact_pk).delete()
    messages.success(request, "Coordonnée supprimée.")
    return redirect(client)


# --- Relations ------------------------------------------------------------------------------


@require_capability(Capability.CLIENTS_EDIT)
def relation_edit(request: AppRequest, pk: int, relation_pk: int | None = None) -> HttpResponse:
    client = _get_client(request, pk)
    relation = None
    if relation_pk is not None:
        relation = get_object_or_404(
            Relation.objects.filter(Q(entity=client) | Q(person=client)), pk=relation_pk
        )
        as_person = relation.person_id == client.pk
    else:
        as_person = request.GET.get("sens") == "mandat" or request.POST.get("sens") == "mandat"
    form = RelationForm(
        request.POST or None,
        instance=relation,
        client=client,
        as_person=as_person,
        user=request.user,
    )
    if request.method == "POST" and form.is_valid():
        saved = form.save()
        events.emit(
            "relation.saved",
            subject=saved.entity,
            actor=request.user,
            payload={"relation": saved.pk, "role": saved.role},
        )
        messages.success(request, "Relation enregistrée.")
        return redirect(client)
    selected = form["other"].value()
    selected_client = (
        _visible_clients(request).filter(pk=selected).first()
        if str(selected or "").isdigit()
        else None
    )
    return render(
        request,
        "clients/relation_form.html",
        {
            "client": client,
            "form": form,
            "relation": relation,
            "as_person": as_person,
            "selected_client": selected_client,
        },
    )


@require_POST
@require_capability(Capability.CLIENTS_EDIT)
def relation_delete(request: AppRequest, pk: int, relation_pk: int) -> HttpResponse:
    client = _get_client(request, pk)
    relation = get_object_or_404(
        Relation.objects.filter(Q(entity=client) | Q(person=client)), pk=relation_pk
    )
    entity = relation.entity
    relation.delete()
    events.emit("relation.deleted", subject=entity, actor=request.user)
    messages.success(request, "Relation supprimée.")
    return redirect(client)


# --- Équipe ---------------------------------------------------------------------------------


@require_capability(Capability.CLIENTS_EDIT)
def assignments_edit(request: AppRequest, pk: int) -> HttpResponse:
    client = _get_client(request, pk)
    form = AssignmentForm(request.POST or None, client=client)
    if request.method == "POST" and form.is_valid():
        form.save()
        messages.success(request, "Équipe mise à jour.")
        return redirect(client)
    return render(request, "clients/assignments_form.html", {"client": client, "form": form})


# --- BCE et TVA -----------------------------------------------------------------------------


@require_POST
@require_capability(Capability.CLIENTS_EDIT)
def bce_apply(request: AppRequest, pk: int) -> HttpResponse:
    client = _get_client(request, pk)
    applied = bce.apply_differences(client, request.POST.getlist("champs"), request.user)
    if applied:
        log_access(
            request, AccessLog.Action.UPDATE, client, details={"champs": applied, "source": "BCE"}
        )
        messages.success(request, "Données de la BCE appliquées.")
    else:
        messages.info(request, "Aucune donnée sélectionnée.")
    return redirect(client)


@require_POST
@require_capability(Capability.CLIENTS_EDIT)
def bce_refresh(request: AppRequest, pk: int) -> HttpResponse:
    client = _get_client(request, pk)
    if not client.enterprise_number:
        messages.error(request, "Ce client n'a pas de numéro d'entreprise.")
    elif bce.fill_blanks(client) is None:
        messages.warning(request, "Numéro absent de la copie BCE (entreprise radiée ou arrêtée ?).")
    else:
        messages.success(request, "Fiche complétée avec la BCE.")
    return redirect(client)


@require_POST
def vies_check(request: AppRequest, pk: int) -> HttpResponse:
    client = _get_client(request, pk)
    check: VatCheck | None = None
    if client.enterprise_number:
        check = vies.check("BE", client.enterprise_number, client=client, user=request.user)
    if request.htmx:
        return render(request, "clients/_vies_result.html", {"check": check, "client": client})
    return redirect(client)
