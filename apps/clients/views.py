"""Écrans des clients : liste, fiche, création, modification, relations, équipe."""

from __future__ import annotations

import io
import re
from collections.abc import Callable
from dataclasses import dataclass
from datetime import timedelta
from typing import Any

from django.contrib import messages
from django.core.exceptions import ValidationError
from django.core.paginator import Paginator
from django.db import IntegrityError, transaction
from django.db.models import Q, QuerySet
from django.http import Http404, HttpResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
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
from apps.integrations import official
from apps.integrations.models import OfficialSnapshot

from . import dossier
from .forms import AssignmentForm, ClientForm, ContactPointForm, RelationForm
from .identifiers import format_enterprise_number, normalize_national_number
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
        "can_delete": request.user.is_staff,  # corbeille (D-095)
        "in_trash": Client.objects.in_trash_visible_to(request.user).count()
        if request.user.is_staff
        else 0,
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


def open_dossier(request: AppRequest, pk: int) -> Client:
    """Client demandé, devenu le dossier actif (en haut de l'écran)."""
    client = _get_client(request, pk)
    dossier.activate(request, client)
    return client


def render_section(
    request: AppRequest,
    pk: int,
    section: str,
    template: str,
    build: Callable[[Client], dict[str, Any]] | None = None,
) -> HttpResponse:
    """Affiche une rubrique du dossier : ouvre le dossier, journalise, rend le gabarit."""
    client = open_dossier(request, pk)
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
    """Ouverture d'un dossier : la Fiche (identité et coordonnées), comme dans FID-Manager."""
    return client_identity(request, pk)


def client_identity(request: AppRequest, pk: int) -> HttpResponse:
    return render_section(
        request,
        pk,
        "identity",
        "clients/sections/identity.html",
        lambda client: {
            "contacts": client.contacts.all(),
            "contact_form": ContactPointForm(),
            "contact_titles": Client.Title.choices,
            "assignments": client.assignments.select_related("user"),
            "last_change": client.history.select_related("history_user").first(),
            "external_links": _external_links(client),
            **_bce_and_moniteur(client),
        },
    )


RECENT_PUBLICATION_DAYS = 45


def _bce_and_moniteur(client: Client) -> dict[str, Any]:
    """Différences avec la BCE (à reprendre en cochant) et publication récente au Moniteur."""
    if client.is_person or not client.enterprise_number:
        return {}
    record = bce.lookup(client.enterprise_number)
    moniteur = official.latest(client, OfficialSnapshot.Source.MONITEUR, ok_only=True)
    since = (timezone.localdate() - timedelta(days=RECENT_PUBLICATION_DAYS)).isoformat()
    recent = [
        p for p in (moniteur.items if moniteur else []) if str(p.get("published_on")) >= since
    ]
    return {
        "bce_differences": bce.differences(client, record) if record else [],
        "recent_publications": recent[:3],
    }


def _external_links(client: Client) -> list[tuple[str, str]]:
    """Sites publics, déjà ouverts sur ce client (comme les boutons du bas de FID-Manager)."""
    number = client.enterprise_number
    if not number:
        return []
    urls = official.public_urls(number)
    return [
        ("BCE", urls[OfficialSnapshot.Source.KBO]),
        ("Banque Nationale (comptes annuels)", urls[OfficialSnapshot.Source.NBB]),
        ("Moniteur belge", urls[OfficialSnapshot.Source.MONITEUR]),
        ("Companyweb", f"https://www.companyweb.be/fr/{number}"),
        ("VIES", "https://ec.europa.eu/taxation_customs/vies/#/vat-validation"),
    ]


def client_relations(request: AppRequest, pk: int) -> HttpResponse:
    """Ancienne page « Relations » : remplacée par Mandataires, Actionnaires, Autres (D-026)."""
    return redirect("clients:mandates", pk=pk)


RELATION_TITLES = {
    "mandates": "Mandataires",
    "shareholders": "Actionnaires",
}


def _relation_page(request: AppRequest, pk: int, page: str) -> HttpResponse:
    roles = dossier.RELATION_PAGES[page]

    def build(client: Client) -> dict[str, Any]:
        incoming = _split_relations(
            request,
            client.relations_as_entity.filter(role__in=roles).select_related("person"),
            "person",
        )
        outgoing = _split_relations(
            request,
            client.relations_as_person.filter(role__in=roles).select_related("entity"),
            "entity",
        )
        return {
            "page": page,
            "title": RELATION_TITLES[page],
            # Pour une société : ses mandataires / actionnaires. Pour une personne : les
            # sociétés où elle a un mandat / des parts.
            "incoming": incoming if not client.is_person else None,
            "outgoing": outgoing if client.is_person else None,
            "default_role": roles[0],
            **(_bce_functions(client) if page == "mandates" and not client.is_person else {}),
        }

    return render_section(request, pk, page, "clients/sections/relations.html", build)


def _bce_functions(client: Client) -> dict[str, Any]:
    """Administrateurs et gérants publiés à la BCE, comparés aux mandataires encodés."""
    return {
        **_official(client, OfficialSnapshot.Source.KBO),
        "function_checks": official.compare_functions(
            client, official.latest(client, OfficialSnapshot.Source.KBO, ok_only=True)
        ),
    }


def client_mandates(request: AppRequest, pk: int) -> HttpResponse:
    return _relation_page(request, pk, "mandates")


def client_shareholders(request: AppRequest, pk: int) -> HttpResponse:
    return _relation_page(request, pk, "shareholders")


# --- Onglet Documents (D-033) ---------------------------------------------------------------


@dataclass(frozen=True)
class CaseStatus:
    """État d'une case : vert (tout va bien), orange (à confirmer), rouge (problème),
    gris (pas encore en place)."""

    level: str  # "ok", "warning", "danger", "empty"
    text: str


def case_status(
    client: Client,
    case: dossier.DocumentCase,
    request: AppRequest,
    every: dict[str, Any] | None = None,
    current: list[Any] | None = None,
) -> CaseStatus:
    """`every` (lignes de toutes les cases) et `current` (documents en place de la case) :
    déjà chargés par l'onglet Documents, pour ne pas relire la base case par case."""
    from apps.documents import services as documents

    if case.slug == "ubo":
        analysis = _ubo(request, client)
        if analysis is None or not analysis.candidates:
            return CaseStatus(
                "danger", "Aucun bénéficiaire effectif calculé : actionnaires à encoder"
            )
        from apps.documents import types

        ubo_rows = every["ubo"] if every and "ubo" in every else types.rows(client, "ubo")
        missing = [r for r in ubo_rows if r.level in ("danger", "warning")]
        if missing:
            level = types.worst([r.level for r in missing])
            return CaseStatus(level, f"{missing[0].doc_type.label} : {missing[0].text.lower()}")
        if not analysis.declared:
            return CaseStatus("warning", "Calculés, pas encore comparés au registre")
        if not analysis.is_consistent:
            return CaseStatus("warning", "Différents de ce qui est déclaré")
        return CaseStatus("ok", "Conformes aux déclarations")
    if case.slug == "a-recevoir":
        overdue = documents.overdue_requests(client)
        if overdue:
            return CaseStatus("danger", f"Sans réponse après relances : {len(overdue)}")
        pending = len(documents.pending_requests(client))
        if pending:
            return CaseStatus("ok", f"{pending} demande{'s' if pending > 1 else ''} en attente")
        return CaseStatus("ok", "Aucune demande en attente")
    if case.slug == "pieces-identite":
        from apps.documents import identity

        rows = identity.people_cards(client, documents.people_concerned(client))
        to_confirm = identity.documents_to_confirm(client)
        if not rows and not to_confirm:
            return CaseStatus("empty", "Aucune personne concernée")
        red = [r for r in rows if r.level == "danger"]
        orange = [r for r in rows if r.level == "warning"]
        if red:
            return CaseStatus("danger", f"{len(red)} carte(s) manquante(s) ou expirée(s)")
        if to_confirm:
            return CaseStatus("warning", f"{len(to_confirm)} carte(s) reçue(s) à confirmer")
        if orange:
            return CaseStatus("warning", f"{len(orange)} carte(s) expirent bientôt")
        return CaseStatus("ok", "Toutes les cartes sont valables")
    from apps.documents import types

    if case.slug in types.TYPED_CASES:
        doc_rows = (
            every[case.slug] if every and case.slug in every else types.rows(client, case.slug)
        )
        level = types.worst([r.level for r in doc_rows])
        problems = [r for r in doc_rows if r.level in ("danger", "warning")]
        if not problems:
            return (
                CaseStatus("ok", "Tout est en ordre")
                if level == "ok"
                else CaseStatus("empty", "Aucun document")
            )
        first = problems[0]
        more = f" + {len(problems) - 1} autre(s)" if len(problems) > 1 else ""
        if len(types.types_for_case(case.slug)) > 1:
            return CaseStatus(level, f"{first.doc_type.label} : {first.text.lower()}{more}")
        who = f"{first.person.display_name} : " if first.person else ""
        return CaseStatus(level, f"{who}{first.text}{more}")
    count = len(current if current is not None else documents.current_documents(client, case.slug))
    if not count:
        return CaseStatus("empty", "Aucun document")
    return CaseStatus("ok", f"{count} document{'s' if count > 1 else ''}")


def client_documents(request: AppRequest, pk: int) -> HttpResponse:
    """Onglet Documents : une case par sujet, avec son état (D-033)."""

    def build(client: Client) -> dict[str, Any]:
        from apps.documents import types
        from apps.documents.models import Document

        # Tous les documents en place du dossier en une requête (au lieu d'une par case).
        loaded = list(
            Document.objects.filter(client=client, archived_at__isnull=True)
            .exclude(case="")
            .select_related("person", "request", "uploaded_by")
            .order_by("-uploaded_at")
        )
        every = types.all_rows(client, [d for d in loaded if d.case in types.TYPED_CASES])
        final = Document.State.FINAL
        cases = []
        for c in dossier.document_cases_for(client):
            if not c.in_documents:  # D-117 : dans la case « UBO » de l'onglet Clôture
                continue
            current = [d for d in loaded if d.case == c.slug and d.state == final]
            cases.append((c, case_status(client, c, request, every, current), current))
        from . import spf

        mandates = spf.lines(client)
        missing = sum(1 for line in mandates if line.status == spf.Status.MISSING)
        waiting = sum(1 for line in mandates if line.status == spf.Status.REQUESTED)
        return {"cases": cases, "mandates": mandates, "mandates_missing": missing,
                "mandates_waiting": waiting}  # fmt: skip

    return render_section(request, pk, "documents", "clients/sections/documents.html", build)


def _ubo_rows(client: Client) -> list[Any]:
    from apps.documents.views import rows_with_requests

    return rows_with_requests(client, "ubo")


def _register(client: Client) -> dict[str, Any]:
    """Registre UBO (D-078) : dernier extrait rangé, changements depuis, pièces justificatives."""
    from apps.documents.freshness import changes
    from apps.documents.models import Document

    extract = (
        Document.objects.filter(client=client, doc_type="extrait_ubo", case="ubo",
                                archived_at__isnull=True)
        .order_by("-uploaded_at")
        .first()
    )  # fmt: skip
    proofs = list(
        Document.objects.filter(client=client, folder="legal").order_by("-uploaded_at")[:6]
    )
    return {
        "extract": extract,
        "changed": changes(extract, client) if extract is not None else [],
        "proofs": proofs,
    }


def _declared(client: Client) -> Any:
    from apps.documents.signing import latest_answers

    return latest_answers(client)


def client_ubo(request: AppRequest, pk: int) -> HttpResponse:
    return render_section(
        request,
        pk,
        "ubo",
        "clients/sections/ubo.html",
        lambda client: {
            "ubo": _ubo(request, client),
            **_documents_block(client, case="ubo"),
            "rows": _ubo_rows(client),
            "declared": _declared(client),
            "register": _register(client),
        },
    )


@require_POST
@require_capability(Capability.CLIENTS_EDIT)
def client_ubo_confirm(request: AppRequest, pk: int) -> HttpResponse:
    """« Le registre UBO montre ces mêmes personnes » : les bénéficiaires calculés sont notés
    comme déclarés au registre (D-103). C'est l'utilisateur qui confirme, après avoir lu
    l'extrait ; l'outil ne devine rien."""
    client = _get_client(request, pk)
    if client.is_person or _register(client)["extract"] is None:
        raise Http404
    analysis = ubo.analyse(client)
    declared = set(
        Relation.objects.filter(entity=client, role=Relation.Role.BENEFICIAL_OWNER).values_list(
            "person_id", flat=True
        )
    )
    added = 0
    with transaction.atomic():
        for candidate in analysis.candidates:
            person = candidate.person
            if not isinstance(person, Client) or person.pk in declared:
                continue
            ownership = candidate.basis == "ownership"
            Relation.objects.create(
                entity=client, person=person, role=Relation.Role.BENEFICIAL_OWNER,
                share_percentage=candidate.share_percentage if ownership else None,
                voting_percentage=candidate.voting_percentage if ownership else None,
            )  # fmt: skip
            added += 1
    log_access(request, AccessLog.Action.UPDATE, client, details={"registre UBO confirmé": added})
    events.emit("ubo.register_confirmed", subject=client, actor=request.user,
                payload={"ajoutes": added})  # fmt: skip
    messages.success(request, "Registre UBO confirmé : les bénéficiaires calculés sont ceux "
                     "déclarés au registre.")  # fmt: skip
    return redirect("clients:ubo", pk=client.pk)


def _official(client: Client, source: str) -> dict[str, Any]:
    """Dernier relevé d'un site officiel (et le dernier réussi, s'il est plus ancien)."""
    last = official.latest(client, source)
    good = last if last is not None and last.ok else official.latest(client, source, ok_only=True)
    urls = official.public_urls(client.enterprise_number) if client.enterprise_number else {}
    return {
        "source": source,
        "last": last,
        "snapshot": good,
        "official_url": urls.get(source, ""),
    }


def client_annual_accounts(request: AppRequest, pk: int) -> HttpResponse:
    """Comptes annuels déposés à la Banque Nationale."""
    from apps.documents import archive_groups

    def build(client: Client) -> dict[str, Any]:
        # Dépôts lus à la Banque Nationale, puis les comptes déposés au cabinet (D-098).
        context = {**_official(client, OfficialSnapshot.Source.NBB),
                   **_documents_block(client, folder=dossier.ACCOUNTS_FOLDER)}  # fmt: skip
        context.update(archive_groups.group(
            client, dossier.ACCOUNTS_FOLDER, list(context["documents"]),
            request.GET.get("annee", ""), request.GET.get("periode", ""),
        ))  # fmt: skip
        return context

    return render_section(
        request, pk, "annual_accounts", "clients/sections/annual_accounts.html", build
    )


def _documents_block(client: Client, *, case: str = "", folder: str = "") -> dict[str, Any]:
    """Liste des documents d'une case ou d'un dossier, avec le formulaire de dépôt."""
    from apps.documents import services as documents
    from apps.documents.views import UploadForm

    return {
        "documents": documents.current_documents(client, case)
        if case
        else documents.archived_documents(client, folder),
        "upload_form": UploadForm(client=client, initial={"case": case, "folder": folder}),
    }


REFERENCE_IN_TITLE = re.compile(r"\[réf\. ([A-Z0-9]+)\]")


def _attach_replies(client: Client, emails: list[Any]) -> None:
    """D-047 : sous chaque e-mail de demande, la pièce que le client a renvoyée."""
    from apps.documents.models import Document, DocumentRequest

    for email in emails:
        request_id = email.request_id
        if request_id is None:
            match = REFERENCE_IN_TITLE.search(email.title)
            found = (
                DocumentRequest.objects.filter(client=client, reference=match.group(1)).first()
                if match
                else None
            )
            request_id = found.pk if found else None
        email.replies = (
            list(
                Document.objects.filter(client=client, request_id=request_id)
                .exclude(folder="courriels")
                .order_by("uploaded_at")
            )
            if request_id
            else []
        )


def client_archives(request: AppRequest, pk: int) -> HttpResponse:
    """Archives du dossier en classeur : années, puis sujets, qui s'ouvrent et se ferment
    (D-105). Une seule entrée au lieu des 8 dossiers copiés de FID-Manager."""
    from apps.documents import archive_groups
    from apps.documents.models import Document

    def build(client: Client) -> dict[str, Any]:
        documents = list(
            Document.objects.filter(client=client, folder__in=dossier.CLASSEUR_FOLDERS)
            .select_related("person", "uploaded_by")
            .order_by("-uploaded_at")
        )
        _attach_replies(client, [d for d in documents if d.folder == "courriels"])
        years = archive_groups.classeur(client, documents)
        wanted = request.GET.get("sujet", "")
        opened = next((y.year for y in years if any(s.folder == wanted for s in y.subjects)), "")
        choices = [(slug, archive_groups.SUBJECTS[slug][0]) for slug, _ in
                   dossier.folders_for(client) if slug in archive_groups.SUBJECTS]  # fmt: skip
        return {"years": years, "wanted": wanted, "opened_year": opened or
                (years[0].year if years else ""), "subjects": choices}  # fmt: skip

    return render_section(request, pk, "archives", "clients/sections/archives.html", build)


def client_archive(request: AppRequest, pk: int, slug: str) -> HttpResponse:
    """Dossier d'archives (D-031). Le Moniteur se remplit seul ; les autres, avec l'onglet
    Documents (les documents traités y seront rangés automatiquement)."""
    found = dossier.ARCHIVE_FOLDERS.get(slug)
    if found is None:
        raise Http404
    if slug in dossier.CLASSEUR_FOLDERS and slug != "moniteur":
        # Les anciens dossiers sont devenus des sujets du classeur (D-105) ; le Moniteur garde
        # sa page (publications lues sur le site officiel).
        return redirect(f"{reverse('clients:archives', args=[pk])}?sujet={slug}")

    def build(client: Client) -> dict[str, Any]:
        context: dict[str, Any] = {"folder": found, **_documents_block(client, folder=slug)}
        if slug == "moniteur" and client.enterprise_number:
            context.update(_official(client, OfficialSnapshot.Source.MONITEUR))
        if slug == "courriels":
            _attach_replies(client, context["documents"])
        from apps.documents import archive_groups

        context.update(archive_groups.group(
            client, slug, list(context["documents"]),
            request.GET.get("annee", ""), request.GET.get("periode", ""),
        ))  # fmt: skip
        return context

    return render_section(request, pk, found.key, "clients/sections/archive.html", build)


def client_work(request: AppRequest, pk: int, slug: str) -> HttpResponse:
    """Page pas encore construite : son contenu sera défini avec Jeremy (D-026)."""
    found = dossier.WORK_PAGES.get(slug)
    if found is None:
        raise Http404
    return render_section(
        request,
        pk,
        found.key,
        "clients/sections/work.html",
        lambda client: {"page_label": found.label},
    )


# --- Dossier actif --------------------------------------------------------------------------


def dossier_switcher(request: AppRequest) -> HttpResponse:
    """Résultats du sélecteur de client (en haut de l'écran) : recherche ou derniers dossiers."""
    query = request.GET.get("q", "").strip()
    section = request.GET.get("rubrique", dossier.DEFAULT_SECTION)
    current = dossier.current(request)
    if len(query) >= 2:
        results = list(_visible_clients(request).search(query).select_related("portfolio")[:12])
        title = ""
    else:
        results = dossier.recent(request, exclude=current)[:5]
        title = "Derniers dossiers ouverts"
    return render(
        request,
        "clients/_switcher_results.html",
        {"results": results, "title": title, "query": query, "section": section},
    )


def dossier_open(request: AppRequest, pk: int) -> HttpResponse:
    """Ouvre un dossier, toujours sur Identité et coordonnées (D-028)."""
    client = open_dossier(request, pk)
    return redirect(f"clients:{dossier.DEFAULT_SECTION}", pk=client.pk)


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

    return render_section(request, pk, "history", "clients/sections/history.html", build)


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
    client = open_dossier(request, pk)
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
def contact_person(request: AppRequest, pk: int) -> HttpResponse:
    """Personne de contact (civilité + nom), pour le « Bonjour … » des e-mails (D-043)."""
    client = _get_client(request, pk)
    title = request.POST.get("contact_title", "")
    if title not in Client.Title.values:
        messages.error(request, "Civilité inconnue.")
        return redirect("clients:identity", pk=client.pk)
    client.contact_title = title
    client.contact_name = request.POST.get("contact_name", "").strip()[:150]
    client.save(update_fields=["contact_title", "contact_name", "updated_at"])
    log_access(request, AccessLog.Action.UPDATE, client, details={"personne de contact": True})
    messages.success(request, "Personne de contact enregistrée.")
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
    client = open_dossier(request, pk)
    relation = None
    if relation_pk is not None:
        relation = _get_relation(request, client, relation_pk)
        as_person = relation.person_id == client.pk
    else:
        as_person = request.GET.get("sens") == "mandat" or request.POST.get("sens") == "mandat"
    role = request.GET.get("role", "")
    form = RelationForm(
        request.POST or None,
        initial={"role": role} if role in Relation.Role.values else None,
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
        return redirect(f"clients:{dossier.page_for_role(saved.role)}", pk=client.pk)
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
            "back": dossier.page_for_role(relation.role if relation else role),
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
    return redirect(f"clients:{dossier.page_for_role(relation.role)}", pk=client.pk)


# --- Équipe ---------------------------------------------------------------------------------


@require_capability(Capability.CLIENTS_EDIT)
def assignments_edit(request: AppRequest, pk: int) -> HttpResponse:
    client = open_dossier(request, pk)
    form = AssignmentForm(request.POST or None, client=client)
    if request.method == "POST" and form.is_valid():
        form.save(actor=request.user)
        log_access(request, AccessLog.Action.UPDATE, client, details={"écran": "équipe"})
        events.emit("client.team_changed", subject=client, actor=request.user)
        messages.success(request, "Équipe mise à jour.")
        return redirect("clients:identity", pk=client.pk)
    return render(request, "clients/assignments_form.html", {"client": client, "form": form})


# --- Gestion hybride (D-063) ------------------------------------------------------------------


def _back(request: AppRequest, client: Client) -> str:
    from django.utils.http import url_has_allowed_host_and_scheme

    target = request.POST.get("retour", "")
    if target and url_has_allowed_host_and_scheme(target, allowed_hosts={request.get_host()}):
        return target
    return str(client.get_absolute_url())


@require_POST
@require_capability(Capability.CLIENTS_EDIT)
def hybrid_take(request: AppRequest, pk: int) -> HttpResponse:
    from . import hybrid

    client = _get_client(request, pk)
    try:
        hybrid.take(client, request.user)
        messages.success(request, f"Vous avez pris « {client.display_name} ».")
    except hybrid.HybridError as error:
        messages.error(request, str(error))
    return redirect(_back(request, client))


@require_POST
@require_capability(Capability.CLIENTS_EDIT)
def hybrid_release(request: AppRequest, pk: int) -> HttpResponse:
    from . import hybrid

    client = _get_client(request, pk)
    try:
        hybrid.release(client, request.user)
        messages.success(request, f"« {client.display_name} » est de nouveau libre.")
    except hybrid.HybridError as error:
        messages.error(request, str(error))
    return redirect(_back(request, client))


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
    return redirect("clients:identity", pk=client.pk)


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
    return redirect("clients:identity", pk=client.pk)


SOURCE_SECTIONS: dict[str, str] = {
    OfficialSnapshot.Source.KBO: "clients:mandates",
    OfficialSnapshot.Source.MONITEUR: "clients:identity",  # voir aussi Archives › Moniteur
    OfficialSnapshot.Source.NBB: "clients:annual_accounts",
}


@require_POST
def official_refresh(request: AppRequest, pk: int, source: str) -> HttpResponse:
    """Consulte maintenant un site officiel pour ce client (BCE, Moniteur, BNB)."""
    client = _get_client(request, pk)
    if source not in SOURCE_SECTIONS:
        raise Http404
    if client.enterprise_number:
        snapshot = official.refresh(client, source, user=request.user)
        if snapshot.ok:
            messages.success(request, f"{snapshot.get_source_display()} : informations à jour.")
        else:
            messages.warning(
                request,
                f"{snapshot.get_source_display()} : {snapshot.get_status_display().lower()}"
                f"{f' ({snapshot.error})' if snapshot.error else ''}. "
                "Le lien vers le site officiel reste disponible.",
            )
    return redirect(SOURCE_SECTIONS[source], pk=client.pk)


@require_POST
@require_capability(Capability.CLIENTS_EDIT)
def official_function_add(request: AppRequest, pk: int, index: int) -> HttpResponse:
    """Reprend dans les relations une fonction lue à la BCE (décision du cabinet, un clic)."""
    client = _get_client(request, pk)
    snapshot = official.latest(client, OfficialSnapshot.Source.KBO, ok_only=True)
    check = next(
        (c for c in official.compare_functions(client, snapshot) if c.index == index), None
    )
    if check is None:
        raise Http404
    if check.matched:
        messages.info(request, "Cette fonction figure déjà dans les relations.")
        return redirect("clients:mandates", pk=client.pk)
    function = check.function
    with transaction.atomic():
        other, created = _client_for_function(request, client, function)
        if other is None:
            return redirect("clients:mandates", pk=client.pk)
        relation = Relation.objects.create(
            entity=client,
            person=other,
            role=check.role,
            start_date=function.since or None,
            notes="Repris de la BCE",
        )
    if created:
        log_access(request, AccessLog.Action.CREATE, other, details={"source": "BCE"})
        events.emit("client.created", subject=other, actor=request.user)
    log_access(request, AccessLog.Action.CREATE, relation, details={"rôle": relation.role})
    events.emit(
        "relation.saved",
        subject=client,
        actor=request.user,
        payload={"relation": relation.pk, "role": relation.role, "source": "BCE"},
    )
    messages.success(
        request,
        f"{other.display_name} ajouté aux relations ({relation.get_role_display().lower()})"
        f"{' — nouvelle fiche créée' if created else ''}.",
    )
    return redirect("clients:mandates", pk=client.pk)


def _client_for_function(
    request: AppRequest, client: Client, function: official.Function
) -> tuple[Client | None, bool]:
    """Fiche existante correspondant à la fonction, sinon nouvelle fiche (prospect)."""
    if function.enterprise_number:
        existing = Client.objects.filter(enterprise_number=function.enterprise_number).first()
        if existing is not None:
            if not _visible_clients(request).filter(pk=existing.pk).exists():
                messages.error(request, "Cette société est suivie dans un portefeuille privé.")
                return None, False
            return existing, False
        return (
            Client.objects.create(
                kind=Client.Kind.COMPANY,
                status=Client.Status.PROSPECT,
                name=function.name,
                enterprise_number=function.enterprise_number,
                portfolio=client.portfolio,
            ),
            True,
        )
    persons = [
        p
        for p in _visible_clients(request).filter(
            kind=Client.Kind.PERSON, name__iexact=function.name
        )
        if official.same_person(function, p)
    ]
    if len(persons) > 1:
        messages.warning(
            request,
            "Plusieurs fiches portent ce nom : ajoutez la relation à la main (choix de la fiche).",
        )
        return None, False
    if persons:
        return persons[0], False
    return (
        Client.objects.create(
            kind=Client.Kind.PERSON,
            status=Client.Status.PROSPECT,
            name=function.name,
            first_name=function.first_name,
            portfolio=client.portfolio,
        ),
        True,
    )
