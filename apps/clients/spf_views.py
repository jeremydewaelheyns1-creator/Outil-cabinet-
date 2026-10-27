"""Encadré « Mandats SPF » de la page Documents du dossier (D-072)."""

from __future__ import annotations

from django.contrib import messages
from django.http import HttpResponse
from django.shortcuts import redirect
from django.utils import timezone
from django.views.decorators.http import require_POST

from apps.core import events
from apps.core.audit import log_access
from apps.core.capabilities import Capability
from apps.core.http import AppRequest
from apps.core.models import AccessLog
from apps.core.permissions import require_capability

from . import spf
from .models import Client, SpfMandate
from .views import _get_client, render_section


@require_POST
@require_capability(Capability.CLIENTS_EDIT)
def spf_mandate_update(request: AppRequest, pk: int) -> HttpResponse:
    client = _get_client(request, pk)
    kind, status = request.POST.get("kind", ""), request.POST.get("status", "")
    if kind not in spf.needed(client) or status not in SpfMandate.Status.values:
        messages.error(request, "Changement refusé.")
        return redirect("clients:documents", pk=client.pk)
    SpfMandate.objects.update_or_create(
        client=client,
        kind=kind,
        defaults={"status": status, "updated_at": timezone.now(), "updated_by": request.user},
    )
    log_access(request, AccessLog.Action.UPDATE, client,
               details={"mandat SPF": kind, "état": status})  # fmt: skip
    events.emit("spf_mandate.changed", subject=client, actor=request.user,
                payload={"mandat": kind, "etat": status})  # fmt: skip
    return redirect("clients:documents", pk=client.pk)


@require_capability(Capability.CLIENTS_EDIT)
def spf_mandate_request(request: AppRequest, pk: int) -> HttpResponse:
    """Demander les mandats manquants (D-075) : fiche à recopier sur le site du SPF, puis un
    seul e-mail au client avec tous ses mandats à signer. Rien ne part sans clic."""
    from apps.core.models import CabinetSettings
    from apps.documents import mailing
    from apps.outlook import graph

    client = _get_client(request, pk)
    cabinet = CabinetSettings.current()
    todo = spf.missing(client)
    kinds = [line.kind for line in todo]
    if not kinds:
        messages.info(request, "Aucun mandat manquant pour ce dossier.")
        return redirect("clients:documents", pk=client.pk)
    subject, body = spf.email(client, kinds, cabinet.spf_mandates_url)
    to = _recipient(client)
    if request.method == "POST":
        action = request.POST.get("action")
        if action == "email":
            sender = mailing.sender_for(client, request.user)
            link = graph.mailbox_for(sender)
            if not to or link is None:
                messages.error(request, "E-mail impossible : " + (
                    "pas d'adresse e-mail dans la fiche du client." if not to
                    else "reliez d'abord votre boîte Outlook (Ma boîte mail)."))  # fmt: skip
                return redirect("clients:spf_mandate_request", pk=client.pk)
            try:
                graph.send(link, to=to, subject=subject, body=body)
            except graph.MailboxError:
                messages.error(request, "Microsoft a refusé l'envoi : rien n'a été modifié.")
                return redirect("clients:spf_mandate_request", pk=client.pk)
            mailing.archive_copy(client, sender=link.address, to=to, subject=subject, body=body,
                                 sent_at=timezone.now(), user=sender)  # fmt: skip
        elif action != "noter":
            return redirect("clients:spf_mandate_request", pk=client.pk)
        spf.mark_requested(client, kinds, request.user)
        details = {"mandats SPF demandés": kinds, "e-mail": action == "email"}
        log_access(request, AccessLog.Action.UPDATE, client, details=details)
        events.emit("spf_mandate.requested", subject=client, actor=request.user,
                    payload={"mandats": kinds, "email": action == "email"})  # fmt: skip
        messages.success(request, "E-mail envoyé au client." if action == "email"
                         else "Mandats notés « demandés ».")  # fmt: skip
        return redirect("clients:documents", pk=client.pk)
    return render_section(
        request,
        pk,
        "documents",
        "clients/sections/spf_request.html",
        lambda c: {
            "todo": todo,
            "cabinet": cabinet,
            "subject": subject,
            "body": body,
            "to": to,
            "already": [x for x in spf.lines(c) if x.status != SpfMandate.Status.MISSING],
        },
    )


def _recipient(client: Client) -> str:
    from apps.documents.services import _recipient as recipient

    return recipient(client)
