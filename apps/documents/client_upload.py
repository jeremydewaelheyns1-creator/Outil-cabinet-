"""Page publique du lien sécurisé : le client y dépose la pièce demandée (D-046).

Sécurité :
- pas de compte : le lien personnel (256 bits au hasard) est la seule clé ; on ne garde que son
  empreinte pour le retrouver ; il ne sert qu'à **déposer**, jamais à voir quoi que ce soit ;
- valable 14 jours (prolongé à chaque relance), inutilisable une fois la pièce reçue ou la
  demande annulée, bloqué après 10 essais ;
- la page ne montre que l'objet de la demande ; lien expiré ou inconnu : même message neutre ;
- fichiers contrôlés par leur contenu (photo JPG/PNG ou PDF), taille limitée ; deux photos
  (recto, verso) sont réunies en un seul PDF ;
- chaque dépôt est journalisé ; la page n'est ni mise en cache, ni indexée, et l'adresse n'est
  pas transmise aux autres sites (`Referrer-Policy: same-origin`).
"""

from __future__ import annotations

import base64
import hashlib

from django.conf import settings
from django.contrib.auth.decorators import login_not_required
from django.core.exceptions import ValidationError
from django.core.files.uploadedfile import SimpleUploadedFile, UploadedFile
from django.db.models import F
from django.http import HttpRequest, HttpResponse
from django.shortcuts import render
from django.views.decorators.http import require_http_methods

from apps.core.audit import log_access
from apps.core.models import AccessLog

from . import services
from .models import DocumentRequest

IMAGES = ("image/jpeg", "image/png")
MAX_FILES = 2


def _headers(response: HttpResponse) -> HttpResponse:
    response["Cache-Control"] = "no-store"
    response["X-Robots-Tag"] = "noindex, nofollow"
    # « same-origin » et pas « no-referrer » : le navigateur doit pouvoir dire au serveur que
    # le formulaire vient bien de cette page (contrôle anti-falsification CSRF), sans jamais
    # transmettre l'adresse du lien à un autre site.
    response["Referrer-Policy"] = "same-origin"
    return response


def _combine(images: list[tuple[UploadedFile[bytes], str]]) -> SimpleUploadedFile:
    """Recto et verso réunis en un PDF de deux pages (lu ensuite comme une seule pièce)."""
    from weasyprint import HTML

    pages = "".join(
        f'<div class="p"><img src="data:{content_type};base64,'
        f'{base64.b64encode(upload.read()).decode()}"></div>'
        for upload, content_type in images
    )
    html = (
        "<style>@page{size:A4;margin:12mm}.p{page-break-after:always;text-align:center}"
        ".p:last-child{page-break-after:auto}img{max-width:100%;max-height:260mm}</style>" + pages
    )
    content = bytes(HTML(string=html).write_pdf())
    return SimpleUploadedFile("piece.pdf", content, content_type="application/pdf")


def _prepare(files: list[UploadedFile[bytes]]) -> tuple[UploadedFile[bytes], list[str]]:
    """Le fichier à ranger, et les empreintes des photos d'origine s'il a fallu les réunir."""
    if not 1 <= len(files) <= MAX_FILES:
        raise ValidationError(f"Déposez un ou {MAX_FILES} fichiers.")
    checked = []
    for upload in files:
        if not upload.size or upload.size > settings.DOCUMENT_MAX_BYTES:
            raise ValidationError("Fichier vide ou trop lourd.")
        content_type = services.detect_type(upload).content_type
        if content_type not in (*IMAGES, "application/pdf"):
            raise ValidationError("Formats acceptés : photo (JPG, PNG) ou PDF.")
        checked.append((upload, content_type))
    if len(checked) == 1:
        return checked[0][0], []
    if any(content_type not in IMAGES for _, content_type in checked):
        raise ValidationError("Déposez soit un seul PDF, soit deux photos (recto et verso).")
    hashes = []
    for upload, _ in checked:
        upload.seek(0)
        hashes.append(hashlib.sha256(upload.read()).hexdigest())
        upload.seek(0)
    return _combine(checked), hashes


@login_not_required
@require_http_methods(["GET", "POST"])
def page(request: HttpRequest, token: str) -> HttpResponse:
    found = services.request_for_link(token)
    if found is None:
        return _headers(render(request, "documents/public/expired.html", status=404))
    if found.kind == DocumentRequest.Kind.BUNDLE:
        return _bundle_page(request, found)
    context: dict[str, object] = {
        "demande": found,
        "is_card": found.kind == DocumentRequest.Kind.IDENTITY_CARD,
        "bundle_url": _bundle_url(found),
    }
    if found.kind == DocumentRequest.Kind.SIGNATURE:
        return _sign_page(request, found, token, context)
    if request.method == "POST":
        DocumentRequest.objects.filter(pk=found.pk).update(link_attempts=F("link_attempts") + 1)
        try:
            upload, hashes = _prepare(request.FILES.getlist("files"))
            # La lecture de la carte se fait ensuite, en arrière-plan : le client n'attend pas.
            document = services.receive(found, upload, source_hashes=hashes, defer=True)
        except ValidationError as error:
            context["error"] = " ".join(error.messages)
        else:
            log_access(request, AccessLog.Action.CREATE, document,
                       details={"via": "lien client", "demande": found.reference})  # fmt: skip
            context["bundle_url"] = _bundle_url(found)
            return _headers(render(request, "documents/public/thanks.html", context))
    return _headers(render(request, "documents/public/upload.html", context))


# --- Demande groupée : une page qui rassemble toutes les pièces (D-051) ----------------------


def _bundle_url(found: DocumentRequest) -> str:
    """Retour à la liste des pièces, tant qu'il en reste à fournir."""
    bundle = found.bundle
    if bundle is None:
        return ""
    bundle.refresh_from_db(fields=["status"])
    return services.upload_url(bundle) if bundle.status == DocumentRequest.Status.PENDING else ""


def _bundle_page(request: HttpRequest, bundle: DocumentRequest) -> HttpResponse:
    items = []
    for item in bundle.items.order_by("title"):
        pending = item.status == DocumentRequest.Status.PENDING
        items.append({
            "title": item.title,
            "pending": pending,
            "sign": item.kind == DocumentRequest.Kind.SIGNATURE,
            "url": services.upload_url(item) if pending and item.link_token else "",
        })  # fmt: skip
    remaining = sum(1 for i in items if i["pending"])
    context = {"demande": bundle, "items": items, "remaining": remaining}
    return _headers(render(request, "documents/public/bundle.html", context))


# --- Signature en ligne (D-048) ---------------------------------------------------------------


def _sign_page(
    request: HttpRequest, found: DocumentRequest, token: str, context: dict[str, object]
) -> HttpResponse:
    from apps.core.audit import client_ip

    from . import preview, signing

    document = signing.awaiting_document(found)
    if document is None:
        return _headers(render(request, "documents/public/expired.html", status=404))
    context.update({"document": document, "pages": range(1, preview.page_count(document) + 1),
                    "token": token, "signer_name": found.client.contact_name})  # fmt: skip
    posted = request.POST if request.method == "POST" else {}
    context["questions"] = [
        {"key": str(q.get("person")), "name": q.get("name", ""),
         "lieu": posted.get(f"lieu-{q.get('person')}", ""),
         "pep": posted.get(f"pep-{q.get('person')}", "")}
        for q in document.questions or []
    ]  # fmt: skip
    if request.method == "POST":
        DocumentRequest.objects.filter(pk=found.pk).update(link_attempts=F("link_attempts") + 1)
        if request.POST.get("approve") != "1":
            context["error"] = "Cochez la case pour confirmer que vous avez lu le document."
        else:
            try:
                answers = signing.answers_from(document, request.POST)
                signed = signing.sign(
                    found,
                    answers=answers,
                    signer_name=request.POST.get("signer_name", ""),
                    signer_role=request.POST.get("signer_role", ""),
                    signature_data_url=request.POST.get("signature", ""),
                    ip=client_ip(request),
                    user_agent=request.headers.get("User-Agent", ""),
                )
            except ValidationError as error:
                context["error"] = " ".join(error.messages)
            else:
                details = {"via": "signature en ligne", "demande": found.reference}
                log_access(request, AccessLog.Action.CREATE, signed, details=details)
                context["signed"] = True
                context["bundle_url"] = _bundle_url(found)
                return _headers(render(request, "documents/public/thanks.html", context))
        context["signer_name"] = request.POST.get("signer_name", "")
        context["signer_role"] = request.POST.get("signer_role", "")
    return _headers(render(request, "documents/public/sign.html", context))


@login_not_required
@require_http_methods(["GET"])
def sign_page_image(request: HttpRequest, token: str, number: int) -> HttpResponse:
    """Image d'une page du document à signer (seulement tant que le lien est valable)."""
    from . import preview, signing

    found = services.request_for_link(token)
    document = signing.awaiting_document(found) if found is not None else None
    rendered = preview.render_page(document, number) if document is not None else None
    if rendered is None:
        return _headers(HttpResponse(status=404))
    content, content_type = rendered
    return _headers(HttpResponse(content, content_type=content_type))
