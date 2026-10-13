"""Exécute le travail de fond en attente, puis s'arrête.

Sur Cloud Run, aucun processus ne tourne en permanence (c'est ce qui rend l'hébergement
peu coûteux). Cloud Scheduler lance donc cette commande toutes les 5 minutes (tâche
Cloud Run « jobs ») :
1. les événements restés en échec ou en attente sont retraités ;
2. les travaux de la file procrastinate sont exécutés jusqu'à ce qu'elle soit vide.
"""

from typing import Any

from django.core.management import call_command
from django.core.management.base import BaseCommand

from apps.core import events


class Command(BaseCommand):
    help = "Retraite les événements en attente et vide la file des travaux de fond."

    def handle(self, *args: Any, **options: Any) -> None:
        count = events.retry_pending()
        self.stdout.write(f"Événements retraités : {count}")
        call_command("procrastinate", "worker", "--one-shot")
