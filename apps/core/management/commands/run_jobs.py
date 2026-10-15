"""Exécute le travail de fond en attente, puis s'arrête.

Sur Cloud Run, aucun processus ne tourne en permanence (c'est ce qui rend l'hébergement
peu coûteux). Cloud Scheduler lance donc cette commande toutes les 5 minutes (tâche
Cloud Run « jobs ») :
1. les événements restés en échec ou en attente sont retraités ;
2. les fichiers de reprise déposés depuis plus de 24 heures sans suite sont effacés ;
3. une fois par jour, les échéances manquantes sont générées ;
4. les travaux de la file procrastinate sont exécutés jusqu'à ce qu'elle soit vide.
"""

from typing import Any

from django.core.management import call_command
from django.core.management.base import BaseCommand

from apps.core import events
from apps.documents import services as documents
from apps.integrations import official
from apps.reprise.models import purge_stale_uploads
from apps.tasks.generator import generate_all_if_due


class Command(BaseCommand):
    help = "Retraite les événements en attente et vide la file des travaux de fond."

    def handle(self, *args: Any, **options: Any) -> None:
        count = events.retry_pending()
        self.stdout.write(f"Événements retraités : {count}")
        self.stdout.write(f"Fichiers de reprise expirés effacés : {purge_stale_uploads()}")
        run = generate_all_if_due()
        if run is not None:
            self.stdout.write(f"Échéances : {run.created} créées, {run.removed} retirées")
        self.stdout.write(f"Relances préparées : {documents.send_due_reminders()}")
        self.stdout.write(f"Sites officiels consultés : {official.refresh_due()} sociétés")
        call_command("procrastinate", "worker", "--one-shot")
