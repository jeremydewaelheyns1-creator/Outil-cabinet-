"""Encadré « Mandats SPF » de la page Documents du dossier (D-072)."""

from __future__ import annotations

import logging

from django.contrib import messages
from django.db import transaction
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

logger = logging.getLogger(__name__)


@require_POST
@require_capability(Capability.CLIENTS_EDIT)
def spf_mandate_update(request: AppRequest, pk: int) -> HttpResponse:
    client = _get_client(request, pk)
    kind, status = request.POST.get("kind", ""), request.POST.get("status", "")
    if "case" in request.POST:  # case « signé » cochée ou décochée dans l'encadré
        status = SpfMandate.Status.SIGNED if status == "signed" else SpfMandate.Status.MISSING
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
    if client.status == Client.Status.PROSPECT:
        messages.info(request, "Prospect : les mandats se demandent après la lettre de mission.")
        return redirect("clients:documents", pk=client.pk)
    cabinet = CabinetSettings.current()
    # Tout ce qui n'est pas encore signé : les rouges (à demander) et les oranges (déjà
    # demandés : on peut revoir les infos à encoder et renvoyer l'e-mail en rappel).
    todo = spf.unsigned(client)
    kinds = [line.kind for line in todo]
    if not kinds:
        messages.info(request, "Tous les mandats de ce dossier sont signés.")
        return redirect("clients:documents", pk=client.pk)
    reminder = not any(line.status == SpfMandate.Status.MISSING for line in todo)
    subject, body = spf.email(client, kinds, cabinet.spf_mandates_url, reminder=reminder)
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
            # L'e-mail est parti : l'état « envoyé » est enregistré quoi qu'il arrive ensuite.
            spf.mark_requested(client, kinds, request.user)
            try:
                sent_at, address = timezone.now(), link.address
                with transaction.atomic():
                    mailing.archive_copy(
                        client, sender=address, to=to, subject=subject, body=body,
                        sent_at=sent_at, user=sender,
                    )  # fmt: skip
            except Exception:  # la copie d'archive ne doit jamais annuler l'envoi
                logger.exception("Mandats SPF : copie d'archive de l'e-mail impossible")
        elif action == "noter":
            spf.mark_requested(client, kinds, request.user)
        else:
            return redirect("clients:spf_mandate_request", pk=client.pk)
        details = {"mandats SPF demandés": kinds, "e-mail": action == "email"}
        log_access(request, AccessLog.Action.UPDATE, client, details=details)
        events.emit("spf_mandate.requested", subject=client, actor=request.user,
                    payload={"mandats": kinds, "email": action == "email"})  # fmt: skip
        messages.success(request, "E-mail envoyé au client : les lignes passent en orange "
                         "jusqu'à la signature." if action == "email"
                         else "Mandats notés « demandés » (orange).")  # fmt: skip
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
            "already": [x for x in spf.lines(c) if x.status == SpfMandate.Status.SIGNED],
            "reminder": reminder,
        },
    )


@require_POST
@require_capability(Capability.CLIENTS_EDIT)
def become_client(request: AppRequest, pk: int) -> HttpResponse:
    """Prospect → client à la main (lettre signée sur papier, accord du client) — D-077."""
    from . import prospects

    client = _get_client(request, pk)
    if prospects.become_client(client, actor=request.user, reason="Passé en client à la main"):
        log_access(request, AccessLog.Action.UPDATE, client, details={"statut": "client"})
        messages.success(request, "C'est un client : complétez sa fiche (statut TVA, équipe…).")
    return redirect("clients:identity", pk=client.pk)


def prospect_delete(request: AppRequest, pk: int) -> HttpResponse:
    """Supprimer un prospect sans suite (administrateurs) — page de confirmation (D-077)."""
    from django.core.exceptions import PermissionDenied
    from django.shortcuts import render

    from . import prospects

    if not request.user.is_staff:
        raise PermissionDenied
    client = _get_client(request, pk)
    if client.status != Client.Status.PROSPECT:
        messages.error(request, "Seul un prospect peut être supprimé.")
        return redirect("clients:identity", pk=client.pk)
    if request.method == "POST" and request.POST.get("confirme") == "1":
        name = client.display_name
        log_access(request, AccessLog.Action.DELETE, client, object_repr="Prospect supprimé",
                   details={"prospect supprimé": True})  # fmt: skip
        prospects.delete_prospect(client)
        messages.success(request, f"Prospect « {name} » supprimé, avec ses documents.")
        return redirect("clients:list")
    counts = {"documents": client.documents.count(), "demandes": client.document_requests.count()}
    return render(request, "clients/prospect_delete.html", {"client": client, "counts": counts})


def _recipient(client: Client) -> str:
    from apps.documents.services import _recipient as recipient

    return recipient(client)
