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


def _prepare(files: list[UploadedFile[bytes]]) -> UploadedFile[bytes]:
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
        return checked[0][0]
    if any(content_type not in IMAGES for _, content_type in checked):
        raise ValidationError("Déposez soit un seul PDF, soit deux photos (recto et verso).")
    return _combine(checked)


@login_not_required
@require_http_methods(["GET", "POST"])
def page(request: HttpRequest, token: str) -> HttpResponse:
    found = services.request_for_link(token)
    if found is None:
        return _headers(render(request, "documents/public/expired.html", status=404))
    context: dict[str, object] = {
        "demande": found,
        "is_card": found.kind == DocumentRequest.Kind.IDENTITY_CARD,
    }
    if request.method == "POST":
        DocumentRequest.objects.filter(pk=found.pk).update(link_attempts=F("link_attempts") + 1)
        try:
            upload = _prepare(request.FILES.getlist("files"))
            document = services.receive(found, upload)
        except ValidationError as error:
            context["error"] = " ".join(error.messages)
        else:
            log_access(request, AccessLog.Action.CREATE, document,
                       details={"via": "lien client", "demande": found.reference})  # fmt: skip
            return _headers(render(request, "documents/public/thanks.html", context))
    return _headers(render(request, "documents/public/upload.html", context))
