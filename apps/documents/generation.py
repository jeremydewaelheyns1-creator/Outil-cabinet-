"""Documents produits par l'outil à partir des données du dossier (D-039).

Deux situations, même mécanique :
- le document n'a jamais existé (nouveau dossier) : « Générer » le produit de A à Z ;
- il existe déjà (repris de FID-Manager) et arrive à échéance ou n'est plus à jour : « Mettre à
  jour » le refait avec les données actuelles et les nouvelles dates.

Le document généré est d'abord un **brouillon**, visible dans sa case. Le gestionnaire le relit
puis le valide (document du cabinet) ou l'envoie au client pour signature (document que le
client signe). Il ne remplace le document en place qu'une fois définitif.

Les modèles sont des pages HTML (`templates/documents/modeles/`) transformées en PDF par
WeasyPrint, sur le serveur. Celui de la procuration est provisoire. La lettre de mission n'a
pas de modèle de base : elle est faite seulement sur le modèle déposé par le cabinet (D-070).
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from typing import Any

from django.conf import settings
from django.core.files.base import ContentFile
from django.db import transaction
from django.template.loader import render_to_string
from django.utils import timezone

from apps.clients.models import Client, Relation
from apps.core import events
from apps.core.models import User

from . import freshness, types
from .models import Document, DocumentRequest


@dataclass(frozen=True)
class Model:
    template: str
    signature: bool  # le client doit le signer
    provisional: bool = False  # modèle provisoire, à remplacer par celui du cabinet


MODELS: dict[str, Model] = {
    "identification_client": Model("identification_client.html", signature=False),
    "identification_mandataire": Model("identification_mandataire.html", signature=False),
    "declaration_ubo": Model("declaration_ubo.html", signature=True),
    "procuration": Model("procuration.html", signature=True, provisional=True),
}


LETTER = "lettre_mission"  # propre à chaque cabinet : seulement avec son modèle (D-070)


def can_generate(doc_type: str) -> bool:
    from . import letter

    if doc_type == LETTER:
        return letter.active() is not None
    return doc_type in MODELS


def needs_signature(doc_type: str) -> bool:
    return doc_type == LETTER or (doc_type in MODELS and MODELS[doc_type].signature)


def _context(
    client: Client, doc_type: str, person: Client | None, user: User | None
) -> dict[str, Any]:
    from apps.clients.services import ubo

    from .identity import situation

    today = timezone.localdate()
    management = (
        Relation.objects.current()
        .filter(
            entity=client,
            role__in=(*Relation.MANAGEMENT_ROLES, Relation.Role.PERMANENT_REPRESENTATIVE),
        )
        .select_related("person")
    )
    context: dict[str, Any] = {
        "client": client,
        "person": person,
        "today": today,
        "cabinet": settings.CABINET_NAME,
        "author": user,
        "doc_label": types.BY_SLUG[doc_type].label,
        "management": list(management),
        "provisional": MODELS[doc_type].provisional,
    }
    if person is not None and person.is_person:
        card, _, card_text = situation(person, today)
        context["card"], context["card_text"] = card, card_text
    if doc_type.startswith("identification_"):
        from .models import RiskAssessment

        context["risk"] = (
            RiskAssessment.objects.filter(client=client).order_by("-created_at").first()
        )
    if doc_type == "declaration_ubo" and not client.is_person:
        context["ubo"] = ubo.analyse(client)
        context["nonprofit"] = client.kind == Client.Kind.NONPROFIT
    return context


def render_pdf(client: Client, doc_type: str, person: Client | None, user: User | None) -> bytes:
    from weasyprint import HTML

    html = render_to_string(
        f"documents/modeles/{MODELS[doc_type].template}",
        _context(client, doc_type, person, user),
    )
    return bytes(HTML(string=html, base_url=str(settings.BASE_DIR)).write_pdf())


def generate(
    client: Client,
    doc_type: str,
    *,
    person: Client | None = None,
    user: User | None = None,
    answers: dict[str, str] | None = None,
) -> Document:
    """Produit un brouillon du document (nouveau, ou mise à jour de celui en place).

    Lettre de mission : uniquement sur le modèle Word que le cabinet a déposé et activé
    (D-069, D-070), avec les réponses du comptable (`answers`)."""
    from . import letter

    if not can_generate(doc_type):
        raise ValueError("Ce document ne peut pas être généré.")
    kind = types.BY_SLUG[doc_type]
    if doc_type == LETTER:
        template = letter.active()
        if template is None:
            raise ValueError("Aucun modèle de lettre de mission n'est activé.")
        content = letter.to_pdf(letter.fill(template, client, answers or {}), kind.label)
    else:
        content = render_pdf(client, doc_type, person, user)
    today = timezone.localdate()
    who = f" — {person.display_name}" if person is not None and kind.per else ""
    with transaction.atomic():
        # Un seul brouillon à la fois par document (et par mandataire).
        _drafts(client, doc_type, person).delete()
        document = Document(
            client=client,
            title=f"{kind.label}{who} ({today:%d/%m/%Y})",
            case=kind.case,
            person=person,
            doc_type=doc_type,
            source=Document.Source.UPLOAD,
            generated=True,
            state=Document.State.DRAFT,
            original_name=f"{doc_type}_{today:%Y%m%d}.pdf",
            content_type="application/pdf",
            size=len(content),
            sha256=hashlib.sha256(content).hexdigest(),
            uploaded_by=user,
            data_fingerprint=freshness.fingerprint(client, doc_type, person),
            questions=_questions(client, doc_type),
        )
        document.file.save("document", ContentFile(content), save=False)
        document.save()
    events.emit(
        "document.generated",
        subject=client,
        actor=user,
        payload={"document": str(document.pk), "type": doc_type},
    )
    return document


def _questions(client: Client, doc_type: str) -> list[dict[str, Any]]:
    """Déclaration UBO : le client répondra, pour chaque bénéficiaire, aux questions PEP et
    donnera le lieu de naissance au moment de signer (D-071)."""
    from apps.clients.services import ubo

    if doc_type != "declaration_ubo" or client.is_person:
        return []
    return [
        {"person": c.person.pk, "name": c.person.display_name}
        for c in ubo.analyse(client).candidates
        if isinstance(c.person, Client)
    ]


def _drafts(client: Client, doc_type: str, person: Client | None) -> Any:
    drafts = Document.objects.filter(
        client=client,
        doc_type=doc_type,
        archived_at__isnull=True,
        state__in=(Document.State.DRAFT, Document.State.AWAITING_SIGNATURE),
    )
    return drafts.filter(person=person) if types.BY_SLUG[doc_type].per else drafts


def finalize(document: Document, *, user: User | None = None) -> Document:
    """Le brouillon devient le document en place ; l'ancien part aux archives."""
    from .services import archive_replaced

    if document.state != Document.State.DRAFT:
        raise ValueError("Seul un brouillon peut être validé.")
    with transaction.atomic():
        archive_replaced(document.client, document.case, document.doc_type, document.person)
        document.state = Document.State.FINAL
        document.uploaded_at = timezone.now()
        document.save(update_fields=["state", "uploaded_at"])
    events.emit(
        "document.finalized", subject=document.client, actor=user,
        payload={"document": str(document.pk)},
    )  # fmt: skip
    return document


def send_for_signature(
    document: Document, *, user: User | None = None, bundle: DocumentRequest | None = None
) -> DocumentRequest:
    """Le brouillon part chez le client pour signature : une demande « À recevoir »."""
    from .services import create_request

    if document.state != Document.State.DRAFT or not needs_signature(document.doc_type):
        raise ValueError("Ce document ne s'envoie pas pour signature.")
    with transaction.atomic():
        request = create_request(
            document.client,
            DocumentRequest.Kind.SIGNATURE,
            person=document.person,
            label=f"{types.BY_SLUG[document.doc_type].label} à signer",
            user=user,
            doc_type=document.doc_type,
            bundle=bundle,
        )
        document.state = Document.State.AWAITING_SIGNATURE
        document.request = request
        document.save(update_fields=["state", "request"])
    return request


def discard(document: Document) -> None:
    if document.state not in (Document.State.DRAFT, Document.State.AWAITING_SIGNATURE):
        raise ValueError("Seul un brouillon peut être supprimé.")
    if document.request and document.request.status == DocumentRequest.Status.PENDING:
        from .services import cancel

        cancel(document.request)
    document.file.delete(save=False)
    document.delete()
