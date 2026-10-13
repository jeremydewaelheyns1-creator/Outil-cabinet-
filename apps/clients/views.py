"""Écrans des clients : liste, fiche, création, modification, relations, équipe."""

from __future__ import annotations

import io
from collections.abc import Callable
from typing import Any

from django.contrib import messages
from django.core.exceptions import ValidationError
from django.core.paginator import Paginator
from django.db import IntegrityError, transaction
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

from . import dossier
from .forms import AssignmentForm, ClientForm, ContactPointForm, RelationForm
from .identifiers import format_enterprise_number, normalize_national_number
from .models import Client, ClientQuerySet, ContactPoint, Relation
from .services import ubo
from .services.alerts import dossier_alerts

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


def _visible_portfolio_ids(request: AppRequest) -> set[int]:
    return set(Portfolio.objects.visible_to(request.user).values_list("pk", flat=True))


def _get_relation(request: AppRequest, client: Client, relation_pk: int) -> Relation:
    """Relation du client dont les deux côtés sont visibles par l'utilisateur."""
    visible = _visible_clients(request)
    return get_object_or_404(
        Relation.objects.filter(entity__in=visible, person__in=visible).filter(pk=relation_pk),
        Q(entity=client) | Q(person=client),
    )


def _masked_query(text: str) -> str:
    """Une recherche qui contient un numéro national ne va pas en clair au journal."""
    return "(numéro masqué)" if sum(c.isdigit() for c in text) >= 11 else text


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
        "can_see_sensitive": request.user.has_capability(Capability.CLIENTS_SENSITIVE),
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
        details={"filtres": {**filters, "q": _masked_query(filters["q"])}, "lignes": count},
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


@require_POST
@require_capability(Capability.CLIENTS_SENSITIVE)
def national_number_lookup(request: AppRequest) -> HttpResponse:
    """Retrouver une fiche par numéro national (requête POST : le numéro n'apparaît ni dans
    l'adresse de la page, ni dans les journaux du serveur). Chaque recherche est journalisée."""
    try:
        number = normalize_national_number(request.POST.get("numero", ""))
    except ValidationError:
        messages.error(request, "Numéro national invalide.")
        return redirect("clients:list")
    client = _visible_clients(request).filter(national_number=number).first() if number else None
    log_access(
        request,
        AccessLog.Action.VIEW,
        client,
        object_type="clients.client",
        object_repr="" if client else "Recherche par numéro national sans résultat",
        details={"recherche": "numéro national", "résultat": client is not None},
    )
    if client is None:
        messages.info(request, "Aucune fiche visible ne porte ce numéro national.")
        return redirect("clients:list")
    return redirect(client)


def _split_relations(
    request: AppRequest, relations: QuerySet[Relation], other_side: str
) -> dict[str, Any]:
    visible = _visible_portfolio_ids(request)
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


def _open(request: AppRequest, pk: int) -> Client:
    """Client demandé, devenu le dossier actif (en haut de l'écran)."""
    client = _get_client(request, pk)
    dossier.activate(request, client)
    return client


def _section(
    request: AppRequest,
    pk: int,
    section: str,
    template: str,
    build: Callable[[Client], dict[str, Any]] | None = None,
) -> HttpResponse:
    """Affiche une rubrique du dossier : ouvre le dossier, journalise, rend le gabarit."""
    client = _open(request, pk)
    log_access(request, AccessLog.Action.VIEW, client, details={"rubrique": section})
    context: dict[str, Any] = {
        "client": client,
        "section": section,
        "can_edit": request.user.has_capability(Capability.CLIENTS_EDIT),
        "can_see_sensitive": request.user.has_capability(Capability.CLIENTS_SENSITIVE),
    }
    if build is not None:
        context.update(build(client))
    return render(request, template, context)


def _ubo(request: AppRequest, client: Client) -> ubo.UboAnalysis | None:
    if client.is_person:
        return None
    return ubo.analyse(client).redact(_visible_portfolio_ids(request))


def client_detail(request: AppRequest, pk: int) -> HttpResponse:
    """Synthèse du dossier : l'essentiel et les points d'attention."""

    def build(client: Client) -> dict[str, Any]:
        analysis = _ubo(request, client)
        relations = _split_relations(
            request, client.relations_as_entity.select_related("person"), "person"
        )
        return {
            "alerts": dossier_alerts(client, analysis),
            "ubo": analysis,
            "managers": [r for r in relations["current"] if r.role in Relation.MANAGEMENT_ROLES],
            "mandates": [
                r
                for r in _split_relations(
                    request, client.relations_as_person.select_related("entity"), "entity"
                )["current"]
                if r.role in Relation.MANAGEMENT_ROLES
            ],
            "primary_contacts": _primary_contacts(client),
            "assignments": client.assignments.select_related("user"),
            "events": events_for(client).select_related("actor")[:8],
        }

    return _section(request, pk, "detail", "clients/sections/summary.html", build)


def _primary_contacts(client: Client) -> list[ContactPoint]:
    """Une coordonnée par type : la principale, à défaut la première."""
    chosen: dict[str, ContactPoint] = {}
    for contact in client.contacts.order_by("kind", "-is_primary", "value"):
        chosen.setdefault(contact.kind, contact)
    return list(chosen.values())


def client_identity(request: AppRequest, pk: int) -> HttpResponse:
    return _section(
        request,
        pk,
        "identity",
        "clients/sections/identity.html",
        lambda client: {"contacts": client.contacts.all(), "contact_form": ContactPointForm()},
    )


def client_relations(request: AppRequest, pk: int) -> HttpResponse:
    return _section(
        request,
        pk,
        "relations",
        "clients/sections/relations.html",
        lambda client: {
            "as_entity": _split_relations(
                request, client.relations_as_entity.select_related("person"), "person"
            ),
            "as_person": _split_relations(
                request, client.relations_as_person.select_related("entity"), "entity"
            ),
        },
    )


def client_ubo(request: AppRequest, pk: int) -> HttpResponse:
    return _section(
        request,
        pk,
        "ubo",
        "clients/sections/ubo.html",
        lambda client: {"ubo": _ubo(request, client)},
    )


def client_team(request: AppRequest, pk: int) -> HttpResponse:
    return _section(
        request,
        pk,
        "team",
        "clients/sections/team.html",
        lambda client: {"assignments": client.assignments.select_related("user")},
    )


def client_public_data(request: AppRequest, pk: int) -> HttpResponse:
    def build(client: Client) -> dict[str, Any]:
        record = bce.lookup(client.enterprise_number) if client.enterprise_number else None
        return {
            "bce_record": record,
            "bce_differences": bce.differences(client, record) if record else [],
            "bce_has_data": bce.has_data(),
            "vat_checks": client.vat_checks.select_related("checked_by")[:10],
        }

    return _section(request, pk, "public_data", "clients/sections/public_data.html", build)


# --- Dossier actif --------------------------------------------------------------------------


def dossier_switcher(request: AppRequest) -> HttpResponse:
    """Résultats du sélecteur de client (en haut de l'écran) : recherche ou derniers dossiers."""
    query = request.GET.get("q", "").strip()
    section = request.GET.get("rubrique", "detail")
    current = dossier.current(request)
    if len(query) >= 2:
        results = list(_visible_clients(request).search(query).select_related("portfolio")[:12])
        title = ""
    else:
        results = dossier.recent(request, exclude=current)
        title = "Derniers dossiers ouverts"
    return render(
        request,
        "clients/_switcher_results.html",
        {"results": results, "title": title, "query": query, "section": section},
    )


def dossier_open(request: AppRequest, pk: int) -> HttpResponse:
    """Change de dossier en restant, si possible, sur la même rubrique."""
    client = _open(request, pk)
    section = request.GET.get("rubrique", "detail")
    allowed = {s.url_name for s in dossier.sections_for(client)}
    return redirect(f"clients:{section if section in allowed else 'detail'}", pk=client.pk)


@require_POST
def dossier_close(request: AppRequest) -> HttpResponse:
    dossier.close(request)
    return redirect("core:home")


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
    def build(client: Client) -> dict[str, Any]:
        context: dict[str, Any] = {
            "rows": _history_rows(client),
            "events": events_for(client).select_related("actor")[:50],
        }
        if request.user.has_capability(Capability.AUDIT_VIEW):
            context["consultations"] = AccessLog.objects.filter(
                object_type=client._meta.label_lower, object_id=str(client.pk)
            )[:50]
        return context

    return _section(request, pk, "history", "clients/sections/history.html", build)


# --- Création et modification ---------------------------------------------------------------


def _initial_from_bce(number: str) -> dict[str, Any]:
    record = bce.lookup(number)
    if record is None:
        return {"enterprise_number": format_enterprise_number(number)}
    initial: dict[str, Any] = bce.proposed_values(record)
    initial["enterprise_number"] = format_enterprise_number(number)
    initial["kind"] = record.client_kind
    return initial


def _save_form(form: ClientForm) -> bool:
    """Enregistre ; un doublon créé entre-temps par un collègue devient une erreur de saisie
    au lieu d'une erreur serveur (dont le détail contiendrait la valeur en double)."""
    try:
        with transaction.atomic():
            form.save()
    except IntegrityError:
        form.add_error(None, "Une autre fiche porte déjà ce numéro ou cette référence.")
        return False
    return True


@require_capability(Capability.CLIENTS_EDIT)
def client_create(request: AppRequest) -> HttpResponse:
    if request.method == "POST":
        form = ClientForm(request.POST, user=request.user)
        if form.is_valid() and _save_form(form):
            client = form.instance
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
    client = _open(request, pk)
    previous_number = client.enterprise_number
    if request.method == "POST":
        form = ClientForm(request.POST, instance=client, user=request.user)
        if form.is_valid() and _save_form(form):
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
            return redirect("clients:identity", pk=client.pk)
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
        log_access(
            request, AccessLog.Action.UPDATE, client, details={"coordonnée ajoutée": contact.kind}
        )
        messages.success(request, "Coordonnée ajoutée.")
    else:
        errors = "; ".join(str(e) for errs in form.errors.values() for e in errs)
        messages.error(request, f"Coordonnée non ajoutée : {errors}")
    return redirect("clients:identity", pk=client.pk)


@require_POST
@require_capability(Capability.CLIENTS_EDIT)
def contact_delete(request: AppRequest, pk: int, contact_pk: int) -> HttpResponse:
    client = _get_client(request, pk)
    contact = get_object_or_404(client.contacts, pk=contact_pk)
    contact.delete()
    log_access(
        request, AccessLog.Action.UPDATE, client, details={"coordonnée supprimée": contact.kind}
    )
    messages.success(request, "Coordonnée supprimée.")
    return redirect("clients:identity", pk=client.pk)


# --- Relations ------------------------------------------------------------------------------


@require_capability(Capability.CLIENTS_EDIT)
def relation_edit(request: AppRequest, pk: int, relation_pk: int | None = None) -> HttpResponse:
    client = _open(request, pk)
    relation = None
    if relation_pk is not None:
        relation = _get_relation(request, client, relation_pk)
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
        log_access(
            request,
            AccessLog.Action.UPDATE if relation else AccessLog.Action.CREATE,
            saved,
            details={"rôle": saved.role},
        )
        events.emit(
            "relation.saved",
            subject=saved.entity,
            actor=request.user,
            payload={"relation": saved.pk, "role": saved.role},
        )
        messages.success(request, "Relation enregistrée.")
        return redirect("clients:relations", pk=client.pk)
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
    relation = _get_relation(request, client, relation_pk)
    entity = relation.entity
    log_access(request, AccessLog.Action.DELETE, relation, details={"rôle": relation.role})
    relation.delete()
    events.emit("relation.deleted", subject=entity, actor=request.user)
    messages.success(request, "Relation supprimée.")
    return redirect("clients:relations", pk=client.pk)


# --- Équipe ---------------------------------------------------------------------------------


@require_capability(Capability.CLIENTS_EDIT)
def assignments_edit(request: AppRequest, pk: int) -> HttpResponse:
    client = _open(request, pk)
    form = AssignmentForm(request.POST or None, client=client)
    if request.method == "POST" and form.is_valid():
        form.save()
        log_access(request, AccessLog.Action.UPDATE, client, details={"écran": "équipe"})
        messages.success(request, "Équipe mise à jour.")
        return redirect("clients:team", pk=client.pk)
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
    return redirect("clients:public_data", pk=client.pk)


@require_POST
@require_capability(Capability.CLIENTS_EDIT)
def bce_refresh(request: AppRequest, pk: int) -> HttpResponse:
    client = _get_client(request, pk)
    if not client.enterprise_number:
        messages.error(request, "Ce client n'a pas de numéro d'entreprise.")
    elif bce.fill_blanks(client) is None:
        messages.warning(request, "Numéro absent de la copie BCE (entreprise radiée ou arrêtée ?).")
    else:
        log_access(request, AccessLog.Action.UPDATE, client, details={"source": "BCE"})
        messages.success(request, "Fiche complétée avec la BCE.")
    return redirect("clients:public_data", pk=client.pk)


@require_POST
@require_capability(Capability.CLIENTS_EDIT)
def vies_check(request: AppRequest, pk: int) -> HttpResponse:
    client = _get_client(request, pk)
    check: VatCheck | None = None
    if client.enterprise_number:
        check = vies.check("BE", client.enterprise_number, client=client, user=request.user)
    if request.htmx:
        return render(request, "clients/_vies_result.html", {"check": check, "client": client})
    return redirect("clients:public_data", pk=client.pk)
