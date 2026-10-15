"""Écrans des documents : cases de l'onglet Documents, dépôt, lecture, demandes au client.

Toute lecture d'un fichier passe par `document_file` : client visible par l'utilisateur,
journalisation, en-têtes qui empêchent le navigateur d'exécuter quoi que ce soit.
"""

from __future__ import annotations

from typing import Any, cast

from django import forms
from django.contrib import messages
from django.core.exceptions import ValidationError
from django.http import FileResponse, Http404, HttpResponse
from django.shortcuts import get_object_or_404, redirect
from django.views.decorators.http import require_GET, require_POST

from apps.clients import dossier
from apps.clients.models import Client
from apps.clients.views import _get_client, render_section
from apps.core.audit import log_access
from apps.core.capabilities import Capability
from apps.core.http import AppRequest
from apps.core.models import AccessLog
from apps.core.permissions import require_capability

from . import services
from .models import Document, DocumentRequest


class UploadForm(forms.Form):
    title = forms.CharField(label="Titre", max_length=200)
    file = forms.FileField(label="Fichier")
    case = forms.CharField(required=False, widget=forms.HiddenInput)
    folder = forms.CharField(required=False, widget=forms.HiddenInput)
    person = forms.ModelChoiceField(
        queryset=Client.objects.none(), required=False, label="Personne concernée"
    )

    def __init__(self, *args: Any, client: Client, **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        people = services.people_concerned(client)
        cast(
            "forms.ModelChoiceField[Client]", self.fields["person"]
        ).queryset = Client.objects.filter(pk__in=[p.pk for p in people])

    def clean(self) -> dict[str, Any]:
        data = super().clean() or {}
        case, folder = data.get("case") or "", data.get("folder") or ""
        if case and case not in dossier.DOCUMENT_CASE_SLUGS:
            raise ValidationError("Case inconnue.")
        if folder and folder not in dossier.ARCHIVE_FOLDERS:
            raise ValidationError("Dossier inconnu.")
        if not case and not folder:
            raise ValidationError("Choisissez où ranger le document.")
        return data


class RequestForm(forms.Form):
    kind = forms.ChoiceField(label="Pièce demandée", choices=DocumentRequest.Kind.choices)
    person = forms.ModelChoiceField(
        queryset=Client.objects.none(), required=False, label="Personne concernée"
    )
    label = forms.CharField(label="Précision (facultatif)", max_length=200, required=False)

    def __init__(self, *args: Any, client: Client, **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        cast(
            "forms.ModelChoiceField[Client]", self.fields["person"]
        ).queryset = Client.objects.filter(pk__in=[p.pk for p in services.people_concerned(client)])

    def clean(self) -> dict[str, Any]:
        data = super().clean() or {}
        if data.get("kind") == DocumentRequest.Kind.IDENTITY_CARD and not data.get("person"):
            raise ValidationError("Indiquez de qui on demande la carte d'identité.")
        return data


class ReceiveForm(forms.Form):
    file = forms.FileField(label="Document reçu")


def _form_errors(request: AppRequest, form: forms.Form) -> None:
    for errors in form.errors.values():
        for error in errors:
            messages.error(request, str(error))


def _back(request: AppRequest, client: Client) -> HttpResponse:
    target = request.POST.get("retour", "")
    if target.startswith(f"/clients/{client.pk}/") and "//" not in target:
        return redirect(target)
    return redirect("clients:documents", pk=client.pk)


# --- Lecture ---------------------------------------------------------------------------------


def case_page(request: AppRequest, pk: int, slug: str) -> HttpResponse:
    """Une case de l'onglet Documents (sauf UBO, qui a sa page)."""
    case = dossier.DOCUMENT_CASE_SLUGS.get(slug)
    if case is None or case.url_name != "document_case":
        raise Http404

    def build(client: Client) -> dict[str, Any]:
        from apps.clients.views import case_status

        context: dict[str, Any] = {
            "case": case,
            "status": case_status(client, case, request),
            "upload_form": UploadForm(client=client, initial={"case": slug}),
        }
        if slug == "a-recevoir":
            context["requests"] = services.pending_requests(client)
            context["request_form"] = RequestForm(client=client)
            context["receive_form"] = ReceiveForm()
        else:
            context["documents"] = services.current_documents(client, slug)
        return context

    return render_section(request, pk, f"documents:{slug}", "documents/case.html", build)


@require_GET
def document_file(request: AppRequest, pk: int, document_id: str) -> FileResponse:
    client = _get_client(request, pk)
    document = get_object_or_404(Document, pk=document_id, client=client)
    log_access(
        request,
        AccessLog.Action.VIEW,
        document,
        details={"client": client.pk, "case": document.case, "dossier": document.folder},
    )
    inline = services.inline_allowed(document)
    response = FileResponse(
        document.file.open("rb"),
        content_type=document.content_type,
        as_attachment=not inline,
        filename=document.original_name,
    )
    # Le fichier vient de l'extérieur : le navigateur ne doit rien y exécuter.
    response["Content-Security-Policy"] = (
        "sandbox; default-src 'none'; img-src 'self'; style-src 'unsafe-inline'"
    )
    response["X-Content-Type-Options"] = "nosniff"
    response["Cache-Control"] = "private, no-store"
    return response


# --- Actions ---------------------------------------------------------------------------------


@require_POST
@require_capability(Capability.CLIENTS_EDIT)
def upload(request: AppRequest, pk: int) -> HttpResponse:
    client = _get_client(request, pk)
    form = UploadForm(request.POST, request.FILES, client=client)
    if not form.is_valid():
        _form_errors(request, form)
        return _back(request, client)
    try:
        document = services.store(
            client,
            form.cleaned_data["file"],
            title=form.cleaned_data["title"],
            case=form.cleaned_data["case"],
            folder=form.cleaned_data["folder"],
            person=form.cleaned_data["person"],
            user=request.user,
        )
    except ValidationError as error:
        messages.error(request, " ".join(error.messages))
        return _back(request, client)
    log_access(request, AccessLog.Action.CREATE, document, details={"client": client.pk})
    messages.success(request, f"Document « {document.title} » ajouté.")
    return _back(request, client)


@require_POST
@require_capability(Capability.CLIENTS_EDIT)
def request_create(request: AppRequest, pk: int) -> HttpResponse:
    client = _get_client(request, pk)
    form = RequestForm(request.POST, client=client)
    if not form.is_valid():
        _form_errors(request, form)
        return redirect("clients:document_case", pk=client.pk, slug="a-recevoir")
    created = services.create_request(
        client,
        form.cleaned_data["kind"],
        person=form.cleaned_data["person"],
        label=form.cleaned_data["label"],
        user=request.user,
    )
    log_access(request, AccessLog.Action.CREATE, created, details={"client": client.pk})
    if created.recipient:
        messages.success(request, f"Demande « {created.title} » préparée.")
    else:
        messages.warning(
            request,
            f"Demande « {created.title} » créée, mais le client n'a pas d'adresse e-mail.",
        )
    return redirect("clients:document_case", pk=client.pk, slug="a-recevoir")


def _get_request(client: Client, request_id: str) -> DocumentRequest:
    return get_object_or_404(DocumentRequest, pk=request_id, client=client)


@require_POST
@require_capability(Capability.CLIENTS_EDIT)
def request_receive(request: AppRequest, pk: int, request_id: str) -> HttpResponse:
    client = _get_client(request, pk)
    pending = _get_request(client, request_id)
    form = ReceiveForm(request.POST, request.FILES)
    if form.is_valid():
        try:
            document = services.receive(pending, form.cleaned_data["file"], user=request.user)
        except ValidationError as error:
            messages.error(request, " ".join(error.messages))
        else:
            log_access(request, AccessLog.Action.CREATE, document, details={"client": client.pk})
            messages.success(request, f"« {pending.title} » reçu et rangé.")
    else:
        messages.error(request, "Joignez le document reçu.")
    return redirect("clients:document_case", pk=client.pk, slug="a-recevoir")


@require_POST
@require_capability(Capability.CLIENTS_EDIT)
def request_cancel(request: AppRequest, pk: int, request_id: str) -> HttpResponse:
    client = _get_client(request, pk)
    pending = _get_request(client, request_id)
    services.cancel(pending, user=request.user)
    log_access(request, AccessLog.Action.UPDATE, pending, details={"annulée": True})
    messages.success(request, f"Demande « {pending.title} » annulée.")
    return redirect("clients:document_case", pk=client.pk, slug="a-recevoir")
