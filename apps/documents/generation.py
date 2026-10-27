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


def _identification(
    client: Client, subject: Client, risk: Any, management: list[Relation]
) -> dict[str, Any]:
    """Ce que les modèles ITAA 3.1 à 3.4 demandent en plus des données de la fiche (D-086)."""
    from .models import RiskAssessment
    from .signing import person_answers

    answers = person_answers(subject) if subject.is_person else None
    pep: bool | None = None
    pep_source = ""
    if answers is not None:
        pep = bool(answers.get("pep"))
        pep_source = "Déclaré par le client (déclaration des bénéficiaires effectifs signée)."
    elif subject == client and risk is not None and "pep" in (risk.answers or {}):
        pep = bool(risk.answers["pep"])
        pep_source = f"Fiche d'évaluation du risque du {risk.created_at:%d/%m/%Y}."
    roles = [r for r in management if r.person_id == subject.pk]
    powers = "; ".join(
        f"{r.get_role_display()}{f' depuis le {r.start_date:%d/%m/%Y}' if r.start_date else ''}"
        for r in roles
    )
    person_management = list(
        Relation.objects.current()
        .filter(entity=subject, role__in=Relation.MANAGEMENT_ROLES)
        .select_related("person")
    ) if not subject.is_person else []  # fmt: skip
    since = f" (client depuis le {client.client_since:%d/%m/%Y})" if client.client_since else ""
    return {
        "levels": list(reversed(RiskAssessment.Level.choices)),  # Élevé, Standard, Faible
        "birth_place": (answers or {}).get("lieu", ""),
        "pep": pep,
        "pep_source": pep_source,
        "powers_text": (powers + " — publication au Moniteur belge") if powers else "……",
        "person_management": person_management,
        "mission_text": f"Tenue de la comptabilité et missions fiscales{since}",
    }


class MissingData(ValueError):
    """Données obligatoires absentes : le document ne peut pas être préparé ni validé."""

    def __init__(self, missing: list[str]) -> None:
        self.missing = missing
        super().__init__("Il manque : " + ", ".join(missing) + ".")


def missing_data(client: Client, doc_type: str, person: Client | None = None) -> list[str]:
    """Ce qui doit être rempli avant de préparer ou valider ce document (D-085)."""
    from .identity import situation
    from .models import RiskAssessment

    missing: list[str] = []
    if doc_type in ("identification_client", "identification_mandataire"):
        subject = person if doc_type == "identification_mandataire" and person else client
        who = "" if subject == client else f" ({subject.display_name})"
        if subject.is_person:
            for label, value in (
                ("nom", subject.name), ("prénom", subject.first_name),
                ("date de naissance", subject.birth_date), ("nationalité", subject.nationality),
                ("adresse", subject.address_lines), ("numéro national", subject.national_number),
            ):  # fmt: skip
                if not value:
                    missing.append(label + who)
            if situation(subject)[1] == "danger":
                missing.append("carte d'identité valable" + who)
        else:
            for label, value in (
                ("dénomination", subject.name), ("forme juridique", subject.legal_form),
                ("numéro d'entreprise", subject.enterprise_number),
                ("adresse du siège", subject.address_lines),
            ):  # fmt: skip
                if not value:
                    missing.append(label + who)
            if doc_type == "identification_client" and not types.mandataires(client):
                missing.append("au moins un dirigeant (Mandataires)")
        if (
            doc_type == "identification_client"
            and not RiskAssessment.objects.filter(client=client).exists()
        ):
            missing.append("niveau de risque (fiche de risque)")
    if doc_type == "declaration_ubo" and not client.is_person:
        from apps.clients.services import ubo

        if not ubo.analyse(client).candidates:
            missing.append("bénéficiaires effectifs (encoder les actionnaires)")
    return missing


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
    subject = person if person is not None else client
    if subject.is_person:  # carte de la personne identifiée (client IPP ou mandataire)
        card, _, card_text = situation(subject, today)
        context["card"], context["card_text"] = card, card_text
    if doc_type.startswith("identification_"):
        from .models import RiskAssessment

        risk = RiskAssessment.objects.filter(client=client).order_by("-created_at").first()
        context["risk"] = risk
        context.update(_identification(client, subject, risk, list(management)))
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
    missing = missing_data(client, doc_type, person)
    if missing:
        raise MissingData(missing)
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
    missing = missing_data(document.client, document.doc_type, document.person)
    if missing:  # données effacées entre-temps : on ne valide pas un document incomplet
        raise MissingData(missing)
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
