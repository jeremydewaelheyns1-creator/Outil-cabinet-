"""Crée le tout premier compte (administrateur) lors de l'installation chez le cabinet.

Le mot de passe n'est jamais passé sur la ligne de commande ni écrit dans un journal : il est
lu dans la variable d'environnement `PREMIER_COMPTE_MOT_DE_PASSE`, alimentée par un secret
temporaire que l'installateur supprime aussitôt après. Refusé s'il existe déjà un compte.
La double authentification sera demandée à la première connexion.
"""

from typing import Any

from django.contrib.auth.password_validation import validate_password
from django.core.exceptions import ValidationError
from django.core.management.base import BaseCommand, CommandError, CommandParser

from apps.core.models import SecurityProfile, User

PASSWORD_VARIABLE = "PREMIER_COMPTE_MOT_DE_PASSE"  # noqa: S105 — nom de variable, pas un secret


class Command(BaseCommand):
    help = "Crée le premier compte administrateur (installation)."

    def add_arguments(self, parser: CommandParser) -> None:
        parser.add_argument("--email", required=True)
        parser.add_argument("--prenom", default="")
        parser.add_argument("--nom", default="")

    def handle(self, *args: Any, **options: Any) -> None:
        import os

        if User.objects.exists():
            raise CommandError("Un compte existe déjà : rien n'a été créé.")
        password = os.environ.get(PASSWORD_VARIABLE, "")
        try:
            validate_password(password)
        except ValidationError as error:
            raise CommandError("Mot de passe refusé : " + " ".join(error.messages)) from error
        user = User.objects.create_superuser(
            options["email"],
            password,
            first_name=options["prenom"],
            last_name=options["nom"],
            profile=SecurityProfile.objects.filter(name="Responsable").first(),
        )
        self.stdout.write(self.style.SUCCESS(f"Compte créé : {user.email}"))
