"""E-mail au client après le dépôt de sa déclaration TVA (D-042).

L'outil propose le texte (montant de la déclaration, acomptes déjà payés, reste à payer, date
limite) ; le gestionnaire le relit, le modifie s'il veut, puis clique sur « Envoyer ». Rien ne
part sans ce clic. Chaque préparation et chaque envoi sont tracés.
"""

from __future__ import annotations

from django.conf import settings
from django.core.mail import EmailMessage
from django.db import transaction
from django.utils import timezone

from apps.clients.models import ContactPoint
from apps.core import events
from apps.core.models import User
from apps.core.templatetags.app_tags import euros

from .models import Column, Status, VatFiling, VatMessage
from .services import set_status


def addresses(filing: VatFiling) -> list[str]:
    """Adresses e-mail de la fiche du client : les seules auxquelles on peut envoyer."""
    return list(
        filing.client.contacts.filter(kind=ContactPoint.Kind.EMAIL).values_list("value", flat=True)
    )


def recipient(filing: VatFiling) -> str:
    found = addresses(filing)
    return found[0] if found else ""


def compose(filing: VatFiling, user: User | None) -> tuple[str, str]:
    """Objet et texte proposés."""
    subject = f"Votre déclaration TVA — {filing.period_label}"
    lines = [filing.client.greeting, ""]
    lines.append(f"Nous avons déposé votre déclaration TVA du {filing.period_label}.")
    lines.append("")
    if filing.grid_72:
        lines.append(f"Montant de la déclaration : {euros(filing.grid_72)} à récupérer.")
    elif filing.grid_71 is not None:
        lines.append(f"Montant de la déclaration : {euros(filing.grid_71)} à payer.")
    advances = filing.advances_total
    if advances:
        parts = []
        if filing.advance_1:
            parts.append(f"1er mois : {euros(filing.advance_1)}")
        if filing.advance_2:
            parts.append(f"2e mois : {euros(filing.advance_2)}")
        lines.append(f"Acomptes déjà payés : {euros(advances)} ({' ; '.join(parts)}).")
    remaining = filing.remaining
    due = f", au plus tard le {filing.due_date:%d/%m/%Y}" if filing.due_date else ""
    if remaining is not None:
        if remaining > 0:
            label = "Reste à payer" if advances else "À payer"
            lines.append(f"{label} : {euros(remaining)}{due}.")
            lines.append("")
            if filing.payment_iban and filing.payment_reference:
                lines += [
                    "Pour le paiement (à copier-coller dans votre banque) :",
                    f"Compte : {filing.payment_iban}",
                    "Bénéficiaire : SPF Finances",
                    f"Montant : {euros(remaining)}",
                    f"Communication structurée : {filing.payment_reference}",
                ]
            else:
                lines.append(
                    "Le paiement se fait sur le compte TVA du SPF Finances, avec votre "
                    "communication structurée habituelle."
                )
        elif remaining < 0:
            lines.append(f"Montant en votre faveur : {euros(-remaining)}.")
        else:
            lines.append("Il ne reste rien à payer.")
    if filing.pdf_id:
        lines += ["", "Vous trouverez la déclaration en pièce jointe."]
    signature = user.get_full_name() if user is not None else ""
    lines += ["", "Nous restons à votre disposition pour toute question.", "", "Bien à vous,"]
    lines += [line for line in (signature, settings.CABINET_NAME) if line]
    return subject, "\n".join(lines)


def draft(filing: VatFiling, user: User | None) -> VatMessage:
    """Le brouillon en cours (ou un nouveau, avec le texte proposé)."""
    message = filing.messages.filter(sent_at__isnull=True).first()
    if message is None:
        subject, body = compose(filing, user)
        # Pas encore enregistré : il ne l'est qu'au premier « Enregistrer » ou « Envoyer ».
        message = VatMessage(
            filing=filing, to=recipient(filing), subject=subject, body=body,
            attach_pdf=bool(filing.pdf_id), created_by=user,
        )  # fmt: skip
    return message


def send(message: VatMessage, user: User | None) -> None:
    if message.sent_at is not None:
        raise ValueError("Cet e-mail est déjà parti.")
    if not message.to:
        raise ValueError("Adresse e-mail du client manquante : ajoutez-la sur sa fiche.")
    if message.to not in addresses(message.filing):
        # Sécurité : jamais d'envoi à une adresse qui n'est pas sur la fiche du client.
        raise ValueError("Cette adresse n'est pas sur la fiche du client.")
    with transaction.atomic():
        message.sent_at, message.sent_by = timezone.now(), user
        message.attach_pdf = message.attach_pdf and bool(message.filing.pdf_id)
        message.save(update_fields=["sent_at", "sent_by", "attach_pdf"])
        set_status(message.filing, Column.CLIENT, Status.DONE, user=user)
    events.emit(
        "vat.client_informed",
        subject=message.filing.client,
        actor=user,
        payload={"periode": message.filing.period_key, "piece_jointe": message.attach_pdf},
    )
    if settings.OUTGOING_EMAIL_ENABLED:
        _deliver(message)


def _deliver(message: VatMessage) -> None:
    """Envoi réel, seulement quand la messagerie du cabinet est branchée."""
    email = EmailMessage(message.subject, message.body, to=[message.to])
    pdf = message.filing.pdf
    if message.attach_pdf and pdf is not None:
        with pdf.file.open("rb") as handle:
            email.attach(f"declaration-tva-{message.filing.period_key}.pdf", handle.read(),
                         "application/pdf")  # fmt: skip
    email.send()
    message.delivered = True
    message.save(update_fields=["delivered"])
