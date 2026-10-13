"""Crée les échéances manquantes de tous les clients (sans doublon).

python manage.py generate_tasks
"""

from typing import Any

from django.core.management.base import BaseCommand

from apps.tasks.generator import generate_all


class Command(BaseCommand):
    help = "Génère les échéances de tous les clients d'après config/taches/regles.yaml."

    def handle(self, *args: Any, **options: Any) -> None:
        run = generate_all()
        self.stdout.write(
            self.style.SUCCESS(
                f"{run.clients} clients : {run.created} échéances créées, {run.removed} retirées."
            )
        )
