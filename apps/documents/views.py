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
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.views.decorators.http import require_GET, require_POST

from apps.clients import dossier
from apps.clients.models import Client
from apps.clients.views import _get_client, render_section
from apps.core.audit import log_access
from apps.core.capabilities import Capability
from apps.core.http import AppRequest
from apps.core.models import AccessLog
from apps.core.permissions import require_capability

from . import services, types
from .models import Document, DocumentRequest


def _concerned_ids(client: Client) -> list[int]:
    """Personnes et sociétés liées au dossier (choix « personne concernée »)."""
    people = [*services.people_concerned(client), *types.mandataires(client)]
    return [p.pk for p in people]


class UploadForm(forms.Form):
    doc_type = forms.ChoiceField(label="Type de document", required=False, choices=())
    title = forms.CharField(label="Titre", max_length=200)
    file = forms.FileField(label="Fichier")
    case = forms.CharField(required=False, widget=forms.HiddenInput)
    folder = forms.CharField(required=False, widget=forms.HiddenInput)
    person = forms.ModelChoiceField(
        queryset=Client.objects.none(), required=False, label="Personne concernée"
    )
    expires_on = forms.DateField(
        label="Date d'expiration",
        required=False,
        widget=forms.DateInput(attrs={"type": "date"}),
    )

    def __init__(self, *args: Any, client: Client, **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        cast(
            "forms.ModelChoiceField[Client]", self.fields["person"]
        ).queryset = Client.objects.filter(pk__in=_concerned_ids(client))
        case = (self.data.get("case") if self.is_bound else self.initial.get("case")) or ""
        cast("forms.ChoiceField", self.fields["doc_type"]).choices = [
            (t.slug, t.label)
            for t in [*types.types_for_case(str(case), client), types.BY_SLUG["autre"]]
        ]

    def clean(self) -> dict[str, Any]:
        data = super().clean() or {}
        doc_type = types.BY_SLUG.get(data.get("doc_type") or "")
        if doc_type is not None and doc_type.per and not data.get("person"):
            raise ValidationError("Indiquez le mandataire concerné.")
        case, folder = data.get("case") or "", data.get("folder") or ""
        if case and case not in dossier.DOCUMENT_CASE_SLUGS:
            raise ValidationError("Case inconnue.")
        if folder and folder not in dossier.ARCHIVE_FOLDERS:
            raise ValidationError("Dossier inconnu.")
        if not case and not folder:
            raise ValidationError("Choisissez où ranger le document.")
        return data


class RequestForm(forms.Form):
    kind = forms.ChoiceField(
        label="Pièce demandée",
        choices=[c for c in DocumentRequest.Kind.choices if c[0] != DocumentRequest.Kind.BUNDLE],
    )
    doc_type = forms.CharField(required=False, widget=forms.HiddenInput)
    person = forms.ModelChoiceField(
        queryset=Client.objects.none(), required=False, label="Personne concernée"
    )
    label = forms.CharField(label="Précision (facultatif)", max_length=200, required=False)

    def __init__(self, *args: Any, client: Client, **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        cast(
            "forms.ModelChoiceField[Client]", self.fields["person"]
        ).queryset = Client.objects.filter(pk__in=_concerned_ids(client))

    def clean(self) -> dict[str, Any]:
        data = super().clean() or {}
        doc_type = data.get("doc_type") or ""
        if doc_type and (doc_type not in types.BY_SLUG or not types.BY_SLUG[doc_type].from_client):
            raise ValidationError("Ce document ne se demande pas au client.")
        if data.get("kind") == DocumentRequest.Kind.IDENTITY_CARD and not data.get("person"):
            raise ValidationError("Indiquez de qui on demande la carte d'identité.")
        return data


class ConfirmCardForm(forms.Form):
    valid_until = forms.DateField(
        label="Valable jusqu'au", widget=forms.DateInput(attrs={"type": "date"})
    )
    card_number = forms.CharField(label="Numéro de carte", max_length=20, required=False)


class ReceiveForm(forms.Form):
    file = forms.FileField(label="Document reçu")


def _form_errors(request: AppRequest, form: forms.Form) -> None:
    for errors in form.errors.values():
        for error in errors:
            messages.error(request, str(error))


def rows_with_requests(client: Client, case: str) -> list[tuple[types.Row, bool]]:
    """Lignes de la case, avec « déjà demandé au client » pour chacune."""
    pending = {(r.doc_type, r.person_id) for r in services.pending_requests(client) if r.doc_type}
    return [
        (row, (row.doc_type.slug, row.person.pk if row.person else None) in pending)
        for row in types.rows(client, case)
    ]


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
        if slug == "pieces-identite":
            from . import identity

            context["people"] = identity.people_cards(client, services.people_concerned(client))
            context["to_confirm"] = identity.documents_to_confirm(client)
            context["confirm_form"] = ConfirmCardForm()
        if slug in types.TYPED_CASES:
            context["rows"] = rows_with_requests(client, slug)
            context["upload_form"] = UploadForm(
                client=client,
                initial={
                    "case": slug,
                    "doc_type": request.GET.get("type", "")
                    or next((t.slug for t in types.types_for_case(slug)), ""),
                    "person": request.GET.get("personne") or None,
                },
            )
        if slug == "fiche-risque":
            latest = client.risk_assessments.first()
            context["risk_pending"] = latest if latest and latest.awaiting_approval else None
            context["can_decide"] = request.user.has_capability(Capability.AML_DECIDE)
        if slug == "a-recevoir":
            from .compliance import overview

            context["ask_all"] = overview(client)
            context["requests"] = services.pending_requests(client)
            context["request_form"] = RequestForm(client=client)
            context["receive_form"] = ReceiveForm()
        else:
            context["documents"] = services.current_documents(client, slug)
        return context

    return render_section(request, pk, f"documents:{slug}", "documents/case.html", build)


SAFE_HEADERS = {
    # Le fichier vient de l'extérieur : le navigateur ne doit rien y exécuter.
    "Content-Security-Policy": (
        "sandbox; default-src 'none'; img-src 'self'; style-src 'unsafe-inline'"
    ),
    "X-Content-Type-Options": "nosniff",
    "Cache-Control": "private, no-store",
}


def _place_label(document: Document) -> str:
    if document.case:
        case = dossier.DOCUMENT_CASE_SLUGS.get(document.case)
        return f"Documents › {case.label}" if case else "Documents"
    folder = dossier.ARCHIVE_FOLDERS.get(document.folder)
    return f"Archives › {folder.label}" if folder else "Archives"


def _viewer_context(request: AppRequest, client: Client, document: Document) -> dict[str, Any]:
    from . import preview

    log_access(
        request,
        AccessLog.Action.VIEW,
        document,
        details={"client": client.pk, "case": document.case, "dossier": document.folder},
    )
    pages = preview.page_count(document)
    # Les autres documents du même endroit, pour passer de l'un à l'autre (‹ ›).
    siblings = (
        services.current_documents(client, document.case)
        if document.case
        else services.archived_documents(client, document.folder)
    )
    ids = [d.pk for d in siblings]
    position = ids.index(document.pk) if document.pk in ids else -1
    from . import generation

    return {
        "can_edit": request.user.has_capability(Capability.CLIENTS_EDIT),
        "needs_signature": generation.needs_signature(document.doc_type),
        "position": position + 1,
        "total": len(ids),
        "previous": siblings[position - 1] if position > 0 else None,
        "next": siblings[position + 1] if 0 <= position < len(ids) - 1 else None,
        "client": client,
        "document": document,
        "place": _place_label(document),
        "pages": range(1, pages + 1),
        "cards": list(document.identity_cards.all()),
        "extension": (document.original_name.rsplit(".", 1)[-1].lower()
                      if "." in document.original_name else ""),
    }  # fmt: skip


@require_GET
def document_viewer(request: AppRequest, pk: int, document_id: str) -> HttpResponse:
    """Visualiseur (fenêtre au-dessus de la page) : renvoie le contenu de la fenêtre."""
    client = _get_client(request, pk)
    document = get_object_or_404(Document, pk=document_id, client=client)
    if not request.htmx:  # adresse ouverte directement (nouvel onglet) : la page entière
        return redirect("clients:document_viewer_page", client.pk, document.pk)
    return render(request, "documents/_viewer.html", _viewer_context(request, client, document))


@require_GET
def document_viewer_page(request: AppRequest, pk: int, document_id: str) -> HttpResponse:
    """Même visualiseur en page entière (lien ouvert sans JavaScript)."""
    client = _get_client(request, pk)
    document = get_object_or_404(Document, pk=document_id, client=client)
    return render_section(
        request,
        pk,
        "documents",
        "documents/viewer_page.html",
        lambda c: _viewer_context(request, c, document),
    )


@require_GET
def document_page(request: AppRequest, pk: int, document_id: str, number: int) -> HttpResponse:
    """Image d'une page pour l'aperçu (la consultation est journalisée à l'ouverture)."""
    from . import preview

    client = _get_client(request, pk)
    document = get_object_or_404(Document, pk=document_id, client=client)
    rendered = preview.render_page(document, number)
    if rendered is None:
        raise Http404
    content, content_type = rendered
    response = HttpResponse(content, content_type=content_type)
    for header, value in SAFE_HEADERS.items():
        response[header] = value
    return response


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
    inline = services.inline_allowed(document) and not request.GET.get("telecharger")
    response = FileResponse(
        document.file.open("rb"),
        content_type=document.content_type,
        as_attachment=not inline,
        filename=document.original_name,
    )
    for header, value in SAFE_HEADERS.items():
        response[header] = value
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
            doc_type=form.cleaned_data["doc_type"] or "",
            expires_on=form.cleaned_data["expires_on"],
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
        doc_type=form.cleaned_data["doc_type"],
    )
    log_access(request, AccessLog.Action.CREATE, created, details={"client": client.pk})
    email = created.emails.first()
    if email is not None and email.delivered:
        messages.success(request, f"Demande « {created.title} » envoyée depuis {email.sent_from}.")
    elif created.recipient:
        messages.warning(
            request,
            f"Demande « {created.title} » préparée mais pas envoyée : aucune boîte Outlook "
            "reliée (menu « Ma boîte mail »).",
        )
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


@require_POST
@require_capability(Capability.CLIENTS_EDIT)
def identity_confirm(request: AppRequest, pk: int, document_id: str) -> HttpResponse:
    """Le gestionnaire confirme une carte que l'outil n'a pas pu appliquer seul."""
    from . import identity

    client = _get_client(request, pk)
    document = get_object_or_404(
        Document, pk=document_id, client=client, case=identity.CASE, review_needed=True
    )
    form = ConfirmCardForm(request.POST)
    if not form.is_valid():
        _form_errors(request, form)
    else:
        card = identity.confirm(
            document,
            valid_until=form.cleaned_data["valid_until"],
            card_number=form.cleaned_data["card_number"],
            user=request.user,
        )
        log_access(request, AccessLog.Action.UPDATE, card, details={"client": client.pk})
        messages.success(request, "Carte confirmée.")
    return redirect("clients:document_case", pk=client.pk, slug=identity.CASE)


@require_POST
@require_capability(Capability.CLIENTS_EDIT)
def identity_undo(request: AppRequest, pk: int, card_id: int) -> HttpResponse:
    """Annule un classement automatique (7 jours)."""
    from . import identity
    from .models import IdentityCard

    client = _get_client(request, pk)
    card = get_object_or_404(IdentityCard, pk=card_id, document__client=client)
    if identity.can_undo(card):
        log_access(request, AccessLog.Action.DELETE, card, details={"annulation": True})
        identity.undo(card, user=request.user)
        messages.success(request, "Classement annulé : la carte est à confirmer.")
    else:
        messages.error(request, "Ce classement ne peut plus être annulé.")
    return redirect("clients:document_case", pk=client.pk, slug=identity.CASE)


# --- Documents générés par l'outil (D-039) ---------------------------------------------------


def _viewer_response(request: AppRequest, client: Client, document: Document) -> HttpResponse:
    """Après une action : le visualiseur (fenêtre) si HTMX, sinon retour à la case."""
    if request.htmx:
        response = render(
            request, "documents/_viewer.html", _viewer_context(request, client, document)
        )
        response["HX-Trigger"] = (
            "documents-changed"  # la page derrière se met à jour à la fermeture
        )
        return response
    case = document.case or "a-recevoir"
    if case == "ubo":
        return redirect("clients:ubo", pk=client.pk)
    return redirect("clients:document_case", pk=client.pk, slug=case)


@require_POST
@require_capability(Capability.CLIENTS_EDIT)
def document_generate(request: AppRequest, pk: int, doc_type: str) -> HttpResponse:
    """« Générer » ou « Mettre à jour » : produit un brouillon et l'affiche aussitôt."""
    from . import generation

    client = _get_client(request, pk)
    if not generation.can_generate(doc_type) or doc_type == generation.LETTER:
        raise Http404  # la lettre de mission passe par « Préparer » (letter_views.prepare)
    person = None
    if types.BY_SLUG[doc_type].per:
        person = get_object_or_404(
            Client, pk=request.POST.get("person") or 0, pk__in=_concerned_ids(client)
        )
    try:
        document = generation.generate(client, doc_type, person=person, user=request.user)
    except generation.MissingData as error:
        return _missing_response(request, client, doc_type, error.missing)
    log_access(request, AccessLog.Action.CREATE, document, details={"généré": doc_type})
    return _viewer_response(request, client, document)


def _missing_response(
    request: AppRequest, client: Client, doc_type: str, missing: list[str]
) -> HttpResponse:
    """Données obligatoires absentes : on dit quoi compléter, rien n'est préparé (D-085)."""
    label = types.BY_SLUG[doc_type].label
    if request.htmx:
        context = {"client": client, "label": label, "missing": missing}
        return render(request, "documents/_missing.html", context)
    messages.error(request, f"{label} : il manque " + ", ".join(missing) + ".")
    case = types.BY_SLUG[doc_type].case
    if case == "ubo":
        return redirect("clients:ubo", pk=client.pk)
    return redirect("clients:document_case", pk=client.pk, slug=case)


def _draft(request: AppRequest, client: Client, document_id: str) -> Document:
    return get_object_or_404(
        Document,
        pk=document_id,
        client=client,
        generated=True,
        state__in=(Document.State.DRAFT, Document.State.AWAITING_SIGNATURE),
    )


@require_POST
@require_capability(Capability.CLIENTS_EDIT)
def document_finalize(request: AppRequest, pk: int, document_id: str) -> HttpResponse:
    from . import generation

    client = _get_client(request, pk)
    document = _draft(request, client, document_id)
    try:
        generation.finalize(document, user=request.user)
    except ValueError as error:
        messages.error(request, str(error))
        return _viewer_response(request, client, document)
    log_access(request, AccessLog.Action.UPDATE, document, details={"validé": True})
    messages.success(request, f"« {document.title} » validé et rangé.")
    return _viewer_response(request, client, document)


@require_POST
@require_capability(Capability.CLIENTS_EDIT)
def document_send(request: AppRequest, pk: int, document_id: str) -> HttpResponse:
    from . import generation

    client = _get_client(request, pk)
    document = _draft(request, client, document_id)
    if not services._recipient(client):
        messages.error(
            request,
            "Pas d'adresse e-mail dans la fiche du client : ajoutez-la (Identité et "
            "coordonnées), puis envoyez le document.",
        )
        return _viewer_response(request, client, document)
    try:
        sent = generation.send_for_signature(document, user=request.user)
    except ValueError as error:
        messages.error(request, str(error))
        return _viewer_response(request, client, document)
    log_access(request, AccessLog.Action.UPDATE, document, details={"envoyé": sent.reference})
    email = sent.emails.first()
    if email is not None and email.delivered:
        messages.success(request, f"« {document.title} » envoyé au client pour signature.")
    else:
        messages.warning(
            request,
            f"« {document.title} » est prêt à signer, mais l'e-mail est seulement préparé, pas "
            "envoyé : aucune boîte Outlook reliée (menu « Ma boîte mail »).",
        )
    return _viewer_response(request, client, document)


@require_POST
@require_capability(Capability.CLIENTS_EDIT)
def document_discard(request: AppRequest, pk: int, document_id: str) -> HttpResponse:
    from . import generation

    client = _get_client(request, pk)
    document = _draft(request, client, document_id)
    case = document.case
    log_access(request, AccessLog.Action.DELETE, document, details={"brouillon": True})
    generation.discard(document)
    messages.success(request, "Brouillon supprimé.")
    if case == "ubo":
        return redirect("clients:ubo", pk=client.pk)
    return redirect("clients:document_case", pk=client.pk, slug=case)


@require_capability(Capability.CLIENTS_EDIT)
def document_delete(request: AppRequest, pk: int, document_id: str) -> HttpResponse:
    """Supprimer un document validé ou déposé par erreur (D-085) : page de confirmation, puis
    suppression ; le document qu'il avait remplacé est remis en place."""
    client = _get_client(request, pk)
    document = get_object_or_404(Document, pk=document_id, client=client)
    refused = services.can_delete(document)
    back = (
        reverse("clients:document_case", args=[client.pk, document.case])
        if document.case and document.case != "ubo"
        else reverse("clients:ubo", args=[client.pk]) if document.case == "ubo"
        else reverse("clients:archive", args=[client.pk, document.folder]) if document.folder
        else reverse("clients:documents", args=[client.pk])
    )  # fmt: skip
    if request.method == "POST" and not refused and request.POST.get("confirme") == "1":
        title = document.title
        log_access(request, AccessLog.Action.DELETE, document,
                   details={"supprimé": True, "type": document.doc_type})  # fmt: skip
        restored = services.delete_document(document)
        text = f"« {title} » supprimé."
        if restored is not None:
            text += f" Le document précédent (« {restored.title} ») est remis en place."
        messages.success(request, text)
        return redirect(back)
    return render_section(
        request,
        pk,
        "documents",
        "documents/delete.html",
        lambda c: {
            "document": document,
            "refused": refused,
            "back": back,
            "previous": services.previous_version(document),
        },
    )
