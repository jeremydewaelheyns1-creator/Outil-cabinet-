"""Écran « Ma boîte mail » (D-060) : réception, en attente de réponse, envoyés, dossiers
(▸ personne physique, pièces jointes), lecture, réponse, clic droit, recherche.

Tout est filtré sur l'employé connecté (`owner`) : personne ne voit la boîte d'un autre.
Les dossiers proposés sont toujours parmi ceux qu'il peut voir.
"""

from __future__ import annotations

from datetime import date, time
from typing import Any
from urllib.parse import urlencode

from django.contrib import messages
from django.contrib.postgres.search import SearchHeadline, SearchQuery, SearchRank
from django.core.exceptions import ValidationError
from django.db.models import Count, F, Q, QuerySet
from django.http import FileResponse, Http404, HttpResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils import timezone
from django.utils.html import escape
from django.utils.safestring import SafeString, mark_safe
from django.views.decorators.http import require_GET, require_POST

from apps.clients.models import Client, Relation
from apps.core.audit import log_access
from apps.core.http import AppRequest
from apps.core.models import AccessLog
from apps.outlook import graph
from apps.outlook.models import MailboxLink

from . import classify, richtext, services
from .models import Awaiting, MailAttachment, MailMessage, ScheduledMail
from .sync import SEARCH_CONFIG, sync_link

MARK_START, MARK_END = "⁣[[", "]]⁣"  # repères invisibles, remplacés par <mark>


def _mine(request: AppRequest) -> QuerySet[MailMessage]:
    return MailMessage.objects.filter(owner=request.user)


def _message(request: AppRequest, message_id: str) -> MailMessage:
    return get_object_or_404(_mine(request), pk=message_id)


def _back(request: AppRequest) -> HttpResponse:
    target = request.POST.get("retour", "")
    if target.startswith(reverse("boite:inbox")) and "//" not in target:
        return redirect(target)
    return redirect("boite:inbox")


def _log(request: AppRequest, action: str, what: str) -> None:
    log_access(request, AccessLog.Action.UPDATE, None, object_type="e-mail",
               object_repr=what[:200], details={"action": action})  # fmt: skip


# --- Arborescence -----------------------------------------------------------------------------


def _tree(request: AppRequest) -> list[dict[str, Any]]:
    """Mes dossiers (ceux où j'ai classé des e-mails), avec personnes et pièces jointes."""
    mine = _mine(request).filter(client__isnull=False, classed_at__isnull=False)
    visible = Client.objects.visible_to(request.user)
    counts = dict(mine.values_list("client").annotate(n=Count("pk")))
    clients = list(visible.filter(pk__in=counts).order_by("name", "first_name"))
    people = mine.filter(person__isnull=False).values_list("client", "person").distinct()
    by_client: dict[int, list[int]] = {}
    for client_id, person_id in people:
        by_client.setdefault(client_id, []).append(person_id)
    persons = {p.pk: p for p in visible.filter(pk__in=[p for _, p in people])}
    files = dict(
        MailAttachment.objects.filter(message__in=mine).values_list("message__client")
        .annotate(n=Count("pk"))
    )  # fmt: skip
    return [
        {"client": c, "count": counts.get(c.pk, 0), "files": files.get(c.pk, 0),
         "persons": [persons[p] for p in by_client.get(c.pk, []) if p in persons]}
        for c in clients
    ]  # fmt: skip


# --- Recherche --------------------------------------------------------------------------------


def _highlight(text: str) -> SafeString:
    """Extrait surligné : tout est échappé, seuls nos repères deviennent <mark>."""
    safe = str(escape(text or ""))
    return mark_safe(  # noqa: S308 - contenu échappé ci-dessus
        safe.replace(escape(MARK_START), "<mark>").replace(escape(MARK_END), "</mark>")
    )


def _search(request: AppRequest, text: str, client: Client | None) -> list[MailMessage]:
    query = SearchQuery(text, config=SEARCH_CONFIG, search_type="websearch")
    found = _mine(request).filter(search=query)
    if client is not None:
        found = found.filter(Q(client=client) | Q(suggested_client=client, classed_at__isnull=True))
    results: list[MailMessage] = list(
        found.annotate(
            rank=SearchRank(F("search"), query),
            excerpt=SearchHeadline(
                "body", query, config=SEARCH_CONFIG, start_sel=MARK_START, stop_sel=MARK_END,
                max_words=30, min_words=12, max_fragments=2,
            ),
        ).order_by("-rank", "-received_at")[:50]
    )  # fmt: skip
    for message in results:
        message.excerpt_html = _highlight(getattr(message, "excerpt", ""))  # type: ignore[attr-defined]
    return results


# --- Écran principal --------------------------------------------------------------------------


def _brief(client: Client | None) -> dict[str, Any] | None:
    """« Le dossier en bref » : 3 faits utiles pour répondre sans ouvrir le dossier."""
    if client is None:
        return None
    from apps.documents.compliance import progress
    from apps.documents.services import pending_requests
    from apps.tasks.models import Task

    upcoming = Task.objects.filter(client=client).open().order_by("due_date").first()
    return {
        "client": client,
        "task": upcoming,
        "progress": progress(client)["percent"],
        "pending": len(pending_requests(client)),
    }


def _reclass_options(request: AppRequest, message: MailMessage) -> list[tuple[str, str]]:
    """Choix « Reclasser dans… » : chaque dossier visible, et les personnes physiques liées
    aux dossiers proposés pour cet e-mail."""
    visible = Client.objects.visible_to(request.user).exclude(status=Client.Status.FORMER)
    options: list[tuple[str, str]] = []
    around = [c for c in (message.client, message.suggested_client) if c is not None]
    for company in dict.fromkeys(around):
        persons = Client.objects.filter(
            pk__in=Relation.objects.current().filter(entity=company).values("person"),
            kind=Client.Kind.PERSON,
        ).filter(pk__in=visible)
        options.append((f"c:{company.pk}", f"{company.display_name}"))
        options += [(f"p:{company.pk}:{p.pk}", f"{company.display_name} › {p.display_name}")
                    for p in persons]  # fmt: skip
    options += [(f"c:{c.pk}", c.display_name) for c in visible.order_by("name", "first_name")]
    return list(dict.fromkeys(options))


def _query(request: AppRequest, **changes: str) -> str:
    params = {k: v for k, v in request.GET.items() if k not in {"message", "ouvrir"}}
    params.update({k: v for k, v in changes.items() if v})
    return f"{reverse('boite:inbox')}?{urlencode(params)}"


@require_GET
def inbox(request: AppRequest) -> HttpResponse:
    link = MailboxLink.objects.filter(user=request.user).first()
    if link is None or not link.read_enabled:
        return render(request, "mailbox/activate.html",
                      {"link": link, "configured": graph.configured()})  # fmt: skip
    view = request.GET.get("vue", "reception")
    visible = Client.objects.visible_to(request.user)
    dossier = None
    if request.GET.get("dossier", "").isdigit():
        dossier = visible.filter(pk=int(request.GET["dossier"])).first()
    person = None
    if request.GET.get("personne", "").isdigit():
        person = visible.filter(pk=int(request.GET["personne"])).first()
    text = request.GET.get("q", "").strip()[:200]
    mine = (
        _mine(request)
        .select_related("suggested_client", "client", "person")
        .annotate(n_files=Count("attachments"))
    )
    title, items, attachments, awaiting = "Boîte de réception", [], [], []
    scheduled: list[ScheduledMail] = []
    if text:
        view, title = "recherche", f"Résultats pour « {text} »"
        items = _search(request, text, dossier)
    elif view == "envoyes":
        title, items = "Envoyés", list(mine.filter(folder=MailMessage.Folder.SENT)[:100])
    elif view == "programmes":
        title = "Programmés"
        scheduled = list(
            request.user.scheduled_mails.filter(
                sent_at__isnull=True, cancelled_at__isnull=True, failed_at__isnull=True
            ).select_related("client")
        )
    elif view == "attente":
        title = "En attente de réponse"
        awaiting = list(request.user.awaiting.filter(done_at__isnull=True).select_related("client"))
    elif view == "pj" and dossier is not None:
        title = f"{dossier.display_name} › Pièces jointes"
        attachments = list(
            MailAttachment.objects.filter(message__owner=request.user, message__client=dossier)
            .select_related("message").order_by("-message__received_at")[:200]
        )  # fmt: skip
    elif view == "personne" and dossier is not None and person is not None:
        title = f"{dossier.display_name} › {person.display_name}"
        items = list(mine.filter(client=dossier, person=person, classed_at__isnull=False)[:200])
    elif view == "dossier" and dossier is not None:
        title = dossier.display_name
        items = list(
            mine.filter(client=dossier, person__isnull=True, classed_at__isnull=False)[:200]
        )
    else:
        view = "reception"
        items = list(mine.filter(folder=MailMessage.Folder.INBOX, classed_at__isnull=True)[:100])

    for item in items:
        item.url = _query(request, message=str(item.pk))  # type: ignore[attr-defined]
    for piece_jointe in attachments:
        piece_jointe.url = _query(request, message=str(piece_jointe.message_id))  # type: ignore[attr-defined]
    selected = None
    if request.GET.get("message"):
        selected = mine.filter(pk=request.GET["message"]).prefetch_related("attachments").first()
    if selected is not None:
        services.mark_read(selected)
        log_access(request, AccessLog.Action.VIEW, None, object_type="e-mail",
                   object_repr=str(selected.pk))  # fmt: skip
    context: dict[str, Any] = {
        "link": link,
        "view": view,
        "title": title,
        "items": items,
        "attachments": attachments,
        "awaiting": awaiting,
        "scheduled": scheduled,
        "selected": selected,
        "dossier": dossier,
        "person": person,
        "q": text,
        "tree": _tree(request),
        "counts": {
            "inbox": _mine(request)
            .filter(folder="inbox", classed_at__isnull=True, read_at__isnull=True)
            .count(),
            "awaiting": request.user.awaiting.filter(done_at__isnull=True).count(),
            "scheduled": request.user.scheduled_mails.filter(
                sent_at__isnull=True, cancelled_at__isnull=True, failed_at__isnull=True
            ).count(),
        },
        "open": request.GET.get("ouvrir", ""),
        "here": request.get_full_path(),
        "today": timezone.localdate(),
        "now_local": timezone.localtime().strftime("%Y-%m-%dT%H:%M"),
        "all_clients": visible.exclude(status=Client.Status.FORMER).order_by("name", "first_name"),
    }
    if selected is not None:
        target = selected.client or selected.suggested_client
        if request.GET.get("ouvrir") == "timesheet":
            return redirect(_timesheet_url(selected, target))
        context.update({
            "selected_url": _query(request, message=str(selected.pk)),
            "brief": _brief(target),
            "choices": (
                classify.choices_for(selected.suggested_person, request.user)
                if selected.choice_needed and selected.suggested_person else []
            ),
            "reclass_options": _reclass_options(request, selected),
            "places": _places(target),
            "attachments": _with_place(selected, target),
            "timesheet_url": _timesheet_url(selected, target),
        })  # fmt: skip
    return render(request, "mailbox/inbox.html", context)


def _places(client: Client | None) -> list[tuple[str, str]]:
    from apps.documents import inbox as depot

    return depot.places(client) if client is not None else []


# Endroit proposé d'office pour ce que l'outil a reconnu (l'employé peut en choisir un autre).
PLACE_FOR_KIND = {"ubo": "case:ubo", "facture": "folder:factures"}


def _with_place(message: MailMessage, client: Client | None) -> list[MailAttachment]:
    pieces = list(message.attachments.all())
    for piece in pieces:
        place = PLACE_FOR_KIND.get(piece.kind, "")
        if piece.kind == MailAttachment.Kind.TAX and client is not None:
            place = "folder:ipp" if client.is_person else "folder:isoc"
        piece.suggested_place = place  # type: ignore[attr-defined]
    return pieces


def _timesheet_url(message: MailMessage, client: Client | None) -> str:
    params = {"jour": f"{timezone.localtime(message.received_at):%Y-%m-%d}",
              "texte": message.subject[:150]}  # fmt: skip
    if client is not None:
        params["dossier"] = str(client.pk)
    return f"{reverse('core:agenda')}?{urlencode(params)}#ts-form"


# --- Actions ----------------------------------------------------------------------------------


@require_POST
def classer(request: AppRequest, message_id: str) -> HttpResponse:
    message = _message(request, message_id)
    try:
        client, person = services.target_for(message, request.POST.get("choix", ""), request.user)
    except (ValueError, Client.DoesNotExist) as error:
        messages.error(
            request, str(error) if isinstance(error, ValueError) else "Dossier introuvable."
        )
        return redirect(_query_for(request, message))
    services.file_message(message, client, person)
    _log(request, "classé", str(message.pk))
    where = f"{client.display_name} › {person.display_name}" if person else client.display_name
    messages.success(request, f"Classé dans {where}.")
    return _back(request)


def _query_for(request: AppRequest, message: MailMessage) -> str:
    back = request.POST.get("retour", "") or reverse("boite:inbox")
    if not back.startswith(reverse("boite:inbox")):
        back = reverse("boite:inbox")
    joiner = "&" if "?" in back else "?"
    return f"{back}{joiner}message={message.pk}" if "message=" not in back else back


@require_POST
def reclasser(request: AppRequest, message_id: str) -> HttpResponse:
    message = _message(request, message_id)
    try:
        client, person = classify.resolve(request.POST.get("cible", ""), request.user)
    except (ValueError, Client.DoesNotExist):
        messages.error(request, "Choisissez un dossier dans la liste.")
        return redirect(_query_for(request, message))
    services.file_message(message, client, person)
    _log(request, "reclassé", str(message.pk))
    messages.success(request, f"Reclassé dans {client.display_name}"
                     f"{f' › {person.display_name}' if person else ''}.")  # fmt: skip
    return _back(request)


@require_POST
def remettre(request: AppRequest, message_id: str) -> HttpResponse:
    message = _message(request, message_id)
    services.unclass(message)
    messages.success(request, "Remis dans la boîte de réception.")
    return _back(request)


@require_POST
def prive(request: AppRequest, message_id: str) -> HttpResponse:
    message = _message(request, message_id)
    services.remove_private(message)
    _log(request, "retiré (privé)", "copie effacée")
    messages.success(request, "E-mail retiré de l'outil : il reste dans Outlook, l'outil "
                     "ne le recopiera plus.")  # fmt: skip
    return _back(request)


def _when(request: AppRequest) -> Any:
    """Heure d'envoi programmé choisie (None : envoyer tout de suite)."""
    if request.POST.get("quand") != "plus-tard":
        return None
    send_at = services.parse_send_at(request.POST.get("programmer", ""))
    if send_at is None:
        raise ValidationError("Choisissez le jour et l'heure de l'envoi.")
    return send_at


def _scheduled_message(item: Any) -> str:
    when = timezone.localtime(item.send_at)
    return (f"Envoi programmé le {when:%d/%m/%Y} à {when:%H:%M}, depuis votre boîte Outlook. "
            "Vous pouvez l'annuler dans « Programmés ».")  # fmt: skip


@require_POST
def repondre(request: AppRequest, message_id: str) -> HttpResponse:
    message = _message(request, message_id)
    html, _ = richtext.body(request.POST.get("html", ""), request.POST.get("texte", ""))
    wait = request.POST.get("attente") == "1"
    try:
        send_at = _when(request)
        if send_at is not None:
            item = services.schedule(request.user, send_at=send_at, html=html,
                                     reply_to=message, wait=wait)  # fmt: skip
            _log(request, "réponse programmée", str(message.pk))
            messages.success(request, _scheduled_message(item))
            return redirect(_query_for(request, message))
        services.reply(message, html, wait=wait)
    except (ValidationError, graph.MailboxError) as error:
        text = " ".join(error.messages) if isinstance(error, ValidationError) else str(error)
        messages.error(request, f"Réponse non envoyée : {text}")
        return redirect(f"{_query_for(request, message)}&ouvrir=repondre")
    _log(request, "réponse envoyée", str(message.pk))
    messages.success(request, "Réponse envoyée depuis votre boîte Outlook. L'e-mail reste "
                     "ici jusqu'à « Traité : classer ».")  # fmt: skip
    return redirect(_query_for(request, message))


@require_POST
def nouveau(request: AppRequest) -> HttpResponse:
    client = None
    if request.POST.get("dossier", "").isdigit():
        client = (
            Client.objects.visible_to(request.user).filter(pk=int(request.POST["dossier"])).first()
        )
    html, _ = richtext.body(request.POST.get("html", ""), request.POST.get("texte", ""))
    to, subject = request.POST.get("a", ""), request.POST.get("objet", "")
    wait = request.POST.get("attente") == "1"
    try:
        send_at = _when(request)
        if send_at is not None:
            item = services.schedule(request.user, send_at=send_at, to=to, subject=subject,
                                     html=html, client=client, wait=wait)  # fmt: skip
            _log(request, "nouveau message programmé", "—")
            messages.success(request, _scheduled_message(item))
            return redirect(f"{reverse('boite:inbox')}?vue=programmes")
        services.send_new(request.user, to=to, subject=subject, html=html, client=client,
                          wait=wait)  # fmt: skip
    except (ValidationError, graph.MailboxError) as error:
        text = " ".join(error.messages) if isinstance(error, ValidationError) else str(error)
        messages.error(request, f"Message non envoyé : {text}")
        return redirect(f"{reverse('boite:inbox')}?ouvrir=nouveau")
    _log(request, "nouveau message envoyé", "—")
    messages.success(request, "Message envoyé depuis votre boîte Outlook.")
    return redirect("boite:inbox")


def _scheduled(request: AppRequest, item_id: int) -> ScheduledMail:
    return get_object_or_404(ScheduledMail, pk=item_id, owner=request.user)


@require_POST
def programme_annuler(request: AppRequest, item_id: int) -> HttpResponse:
    item = _scheduled(request, item_id)
    services.cancel(item)
    _log(request, "envoi programmé annulé", str(item.pk))
    messages.success(request, "Envoi annulé : le message ne partira pas.")
    return redirect(f"{reverse('boite:inbox')}?vue=programmes")


@require_POST
def programme_envoyer(request: AppRequest, item_id: int) -> HttpResponse:
    item = _scheduled(request, item_id)
    try:
        services.deliver(item)
    except (ValidationError, graph.MailboxError) as error:
        text = " ".join(error.messages) if isinstance(error, ValidationError) else str(error)
        messages.error(request, f"Message non envoyé : {text}")
        return redirect(f"{reverse('boite:inbox')}?vue=programmes")
    _log(request, "envoi programmé envoyé maintenant", str(item.pk))
    messages.success(request, "Message envoyé depuis votre boîte Outlook.")
    return redirect(f"{reverse('boite:inbox')}?vue=programmes")


@require_POST
def plus_attendre(request: AppRequest, awaiting_id: int) -> HttpResponse:
    item = get_object_or_404(Awaiting, pk=awaiting_id, owner=request.user)
    item.done_at = timezone.now()
    item.save(update_fields=["done_at"])
    return redirect(f"{reverse('boite:inbox')}?vue=attente")


@require_POST
def echeance(request: AppRequest, message_id: str) -> HttpResponse:
    from apps.tasks import deadlines

    message = _message(request, message_id)
    client = (
        Client.objects.visible_to(request.user).filter(pk=request.POST.get("dossier") or 0).first()
    )
    try:
        if client is None:
            raise ValidationError("Choisissez le dossier.")
        day = date.fromisoformat(request.POST.get("jour", ""))
        at = time.fromisoformat(request.POST["heure"]) if request.POST.get("heure") else None
        until = time.fromisoformat(request.POST["fin"]) if request.POST.get("fin") else None
        deadlines.add(request.user, client=client, day=day, at=at, until=until,
                      comment=request.POST.get("commentaire", ""),
                      remind=request.POST.get("rappel") == "1")  # fmt: skip
    except (ValidationError, ValueError) as error:
        text = (
            " ".join(error.messages)
            if isinstance(error, ValidationError)
            else "Date ou heure invalide."
        )
        messages.error(request, f"Échéance non créée : {text}")
        return redirect(_query_for(request, message))
    _log(request, "échéance créée depuis un e-mail", str(message.pk))
    when = f"{day:%d/%m}" + (f" à {at:%H:%M}" if at else "")
    messages.success(request, f"Échéance ajoutée le {when} : elle apparaît dans « Mon agenda ».")
    return redirect(_query_for(request, message))


@require_POST
def ranger_piece(request: AppRequest, attachment_id: str) -> HttpResponse:
    attachment = get_object_or_404(
        MailAttachment.objects.select_related("message"), pk=attachment_id,
        message__owner=request.user,
    )  # fmt: skip
    try:
        text = services.file_attachment(attachment, request.user, request.POST.get("endroit", ""))
    except ValidationError as error:
        messages.error(request, " ".join(error.messages))
    else:
        _log(request, "pièce jointe rangée dans le dossier", str(attachment.pk))
        messages.success(request, text)
    return redirect(_query_for(request, attachment.message))


@require_GET
def piece(request: AppRequest, attachment_id: str) -> FileResponse:
    from apps.documents.views import SAFE_HEADERS

    attachment = get_object_or_404(MailAttachment, pk=attachment_id, message__owner=request.user)
    log_access(request, AccessLog.Action.VIEW, None, object_type="pièce jointe",
               object_repr=str(attachment.pk))  # fmt: skip
    inline = attachment.content_type in ("application/pdf", "image/jpeg", "image/png")
    response = FileResponse(
        attachment.file.open("rb"), as_attachment=not inline, filename=attachment.name,
        content_type=attachment.content_type if inline else "application/octet-stream",
    )  # fmt: skip
    for header, value in SAFE_HEADERS.items():
        response[header] = value
    return response


@require_POST
def relever(request: AppRequest) -> HttpResponse:
    """« Relever maintenant » : lecture immédiate de la boîte, sans attendre 5 minutes."""
    link = MailboxLink.objects.filter(user=request.user, read_enabled=True).first()
    if link is None:
        raise Http404
    count = sync_link(link)
    link.refresh_from_db()
    if link.sync_error:
        messages.error(request, link.sync_error)
    else:
        messages.success(
            request, f"{count} nouvel e-mail" if count == 1 else f"{count} nouveaux e-mails"
        )
    return redirect("boite:inbox")


@require_POST
def desactiver(request: AppRequest) -> HttpResponse:
    """L'employé arrête la lecture : toutes les copies de sa boîte sont effacées de l'outil."""
    from .sync import delete

    link = MailboxLink.objects.filter(user=request.user).first()
    if link is not None:
        link.read_enabled = False
        link.read_since = None
        link.inbox_cursor = link.sent_cursor = None
        link.save(update_fields=["read_enabled", "read_since", "inbox_cursor", "sent_cursor"])
    for message in _mine(request):
        delete(message)
    request.user.awaiting.all().delete()
    log_access(request, AccessLog.Action.DELETE, None, object_type="lecture de la boîte",
               object_repr="désactivée, copies effacées")  # fmt: skip
    messages.success(request, "Lecture désactivée : les copies de vos e-mails ont été effacées "
                     "de l'outil. Ils restent dans Outlook.")  # fmt: skip
    return redirect("outlook:mailbox")
