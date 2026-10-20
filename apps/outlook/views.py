"""Page « Ma boîte mail » : relier ou délier sa boîte Outlook (D-044)."""

from __future__ import annotations

import secrets

from django.contrib import messages
from django.http import HttpResponse
from django.shortcuts import redirect, render
from django.urls import reverse
from django.views.decorators.http import require_GET, require_POST

from apps.core.audit import log_access
from apps.core.http import AppRequest
from apps.core.models import AccessLog

from . import graph
from .models import MailboxLink

SESSION_STATE = "outlook_etat"
SESSION_VERIFIER = "outlook_verif"


def _redirect_uri(request: AppRequest) -> str:
    return request.build_absolute_uri(reverse("outlook:callback"))


@require_GET
def mailbox(request: AppRequest) -> HttpResponse:
    return render(
        request,
        "outlook/mailbox.html",
        {
            "configured": graph.configured(),
            "link": MailboxLink.objects.filter(user=request.user).first(),
            "redirect_uri": _redirect_uri(request),
        },
    )


@require_POST
def connect(request: AppRequest) -> HttpResponse:
    if not graph.configured():
        messages.error(request, "La connexion Outlook n'est pas encore configurée.")
        return redirect("outlook:mailbox")
    state = secrets.token_urlsafe(32)
    verifier, challenge = graph.pkce()
    request.session[SESSION_STATE] = state
    request.session[SESSION_VERIFIER] = verifier
    url = graph.authorize_url(_redirect_uri(request), state, challenge, request.user.email)
    return redirect(url)


@require_GET
def callback(request: AppRequest) -> HttpResponse:
    """Retour de Microsoft après la connexion de l'employé."""
    expected = request.session.pop(SESSION_STATE, "")
    verifier = request.session.pop(SESSION_VERIFIER, "")
    state = request.GET.get("state", "")
    if not expected or not secrets.compare_digest(str(expected), state):
        messages.error(request, "Connexion refusée (demande expirée) : recommencez.")
        return redirect("outlook:mailbox")
    if request.GET.get("error") or not request.GET.get("code"):
        messages.error(request, "Connexion annulée chez Microsoft : la boîte n'est pas reliée.")
        return redirect("outlook:mailbox")
    try:
        link = graph.connect(
            request.user,
            code=request.GET["code"],
            redirect_uri=_redirect_uri(request),
            verifier=str(verifier),
        )
    except graph.MailboxError as error:
        messages.error(request, f"Boîte non reliée : {error}")
        return redirect("outlook:mailbox")
    log_access(request, AccessLog.Action.CREATE, None, object_type="boîte Outlook reliée",
               object_repr=link.address)  # fmt: skip
    messages.success(request, f"Boîte {link.address} reliée : vos e-mails partiront d'elle.")
    return redirect("outlook:mailbox")


@require_POST
def disconnect(request: AppRequest) -> HttpResponse:
    link = MailboxLink.objects.filter(user=request.user).first()
    if link is not None:
        graph.disconnect(request.user)
        log_access(request, AccessLog.Action.DELETE, None, object_type="boîte Outlook reliée",
                   object_repr=link.address)  # fmt: skip
        messages.success(request, "Boîte déliée : l'outil ne peut plus envoyer en votre nom.")
    return redirect("outlook:mailbox")
