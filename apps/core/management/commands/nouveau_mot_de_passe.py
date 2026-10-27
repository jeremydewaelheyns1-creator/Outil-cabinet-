"""Nouveau mot de passe d'un compte, depuis Cloud Shell (dépannage, D-081).

Comme `premier_compte` : le mot de passe n'est jamais sur la ligne de commande ni dans un
journal ; il est lu dans `NOUVEAU_MOT_DE_PASSE`, alimentée par un secret temporaire que le
script `deploy/mot-de-passe.sh` supprime aussitôt après. Adresse inconnue : rien n'est changé,
et la commande rappelle les comptes administrateurs sous forme masquée (j•••@d•••.be) pour
aider à retrouver la bonne adresse. La double authentification reste demandée.
"""

from typing import Any

from django.contrib.auth.password_validation import validate_password
from django.core.exceptions import ValidationError
from django.core.management.base import BaseCommand, CommandError, CommandParser

from apps.core.audit import log_access
from apps.core.models import AccessLog, User

PASSWORD_VARIABLE = "NOUVEAU_MOT_DE_PASSE"  # noqa: S105 — nom de variable, pas un secret


def masked(email: str) -> str:
    name, _, domain = email.partition("@")
    host, _, tld = domain.rpartition(".")
    return f"{name[:1]}•••@{host[:1]}•••.{tld}"


class Command(BaseCommand):
    help = "Donne un nouveau mot de passe à un compte (dépannage depuis Cloud Shell)."

    def add_arguments(self, parser: CommandParser) -> None:
        parser.add_argument("--email", required=True)

    def handle(self, *args: Any, **options: Any) -> None:
        import os

        user = User.objects.filter(email__iexact=options["email"].strip(), is_active=True).first()
        if user is None:
            admins = User.objects.filter(is_staff=True, is_active=True).values_list(
                "email", flat=True
            )
            hint = ", ".join(masked(e) for e in admins) or "aucun"
            raise CommandError(f"Aucun compte actif à cette adresse. Administrateurs : {hint}")
        password = os.environ.get(PASSWORD_VARIABLE, "")
        try:
            validate_password(password, user)
        except ValidationError as error:
            raise CommandError("Mot de passe refusé : " + " ".join(error.messages)) from error
        user.set_password(password)
        user.save(update_fields=["password"])
        log_access(None, AccessLog.Action.UPDATE, user, user=user,
                   details={"mot de passe": "changé depuis Cloud Shell"})  # fmt: skip
        self.stdout.write(
            self.style.SUCCESS(f"Nouveau mot de passe enregistré pour {masked(user.email)}")
        )
