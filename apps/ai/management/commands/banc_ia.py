"""Banc d'essai de la lecture des modèles par l'assistant IA (D-132).

    python manage.py banc_ia [--sans-ia] [--rapport fichier.md]

Documents entièrement fictifs ; rien n'est gardé en base (tout est annulé à la fin).
"""

from pathlib import Path
from typing import Any

from django.core.management.base import BaseCommand, CommandParser
from django.db import transaction


class Command(BaseCommand):
    help = "Note la lecture des modèles (documents fictifs) par l'assistant IA."

    def add_arguments(self, parser: CommandParser) -> None:
        parser.add_argument("--sans-ia", action="store_true", help="Règles de l'outil seules.")
        parser.add_argument("--rapport", default="", help="Écrit le rapport dans ce fichier.")

    def handle(self, *args: Any, **options: Any) -> None:
        from apps.ai import banc
        from apps.ai.models import AiCall

        class Rollback(Exception):
            pass

        text = ""
        try:
            with transaction.atomic():
                scores = banc.run(use_ai=not options["sans_ia"])
                calls = AiCall.objects.all()
                cost = sum(float(c.cost_eur) for c in calls)
                errors = sorted({c.error for c in calls if c.error})
                label = "règles seules" if options["sans_ia"] else "avec l'assistant IA"
                text = banc.report(scores, label)
                text += f"\nAppels à l'IA : {calls.count()} · coût estimé : {cost:.3f} €"
                if errors:
                    text += f" · erreurs : {', '.join(errors)}"
                raise Rollback
        except Rollback:
            pass
        if options["rapport"]:
            Path(options["rapport"]).write_text(text + "\n", encoding="utf-8")
        self.stdout.write(text)
