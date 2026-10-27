"""Comptes : pas d'inscription libre ; « mot de passe oublié » envoyé par Outlook (D-081)."""

from __future__ import annotations

import logging
from typing import Any

from allauth.account.adapter import DefaultAccountAdapter
from django.http import HttpRequest

logger = logging.getLogger(__name__)


class AccountAdapter(DefaultAccountAdapter):
    """Pas d'inscription libre : les comptes sont créés par un administrateur."""

    def is_open_for_signup(self, request: HttpRequest) -> bool:
        return False

    def send_mail(self, template_prefix: str, email: str, context: dict[str, Any]) -> None:
        """L'e-mail (lien de réinitialisation) part de la boîte Outlook reliée d'un
        administrateur, sans copie dans ses « Éléments envoyés ». Sans boîte reliée : par le
        serveur d'envoi du cabinet s'il est configuré. Le journal ne garde jamais l'adresse."""
        from apps.core.models import User
        from apps.outlook import graph

        message = self.render_mail(template_prefix, email, context)
        for admin in User.objects.filter(is_staff=True, is_active=True).order_by("pk"):
            link = graph.mailbox_for(admin)
            if link is None:
                continue
            try:
                graph.send(link, to=email, subject=str(message.subject), body=str(message.body),
                           keep_copy=False)  # fmt: skip
            except graph.MailboxError:
                logger.warning("Mot de passe oublié : envoi Outlook refusé, essai suivant")
                continue
            return
        try:
            message.send()
        except Exception:  # serveur d'envoi absent ou refus : rien de plus à faire ici
            logger.warning("Mot de passe oublié : aucun moyen d'envoyer l'e-mail")
