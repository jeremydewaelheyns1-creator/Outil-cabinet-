"""Exécute le travail de fond en attente, puis s'arrête.

Sur Cloud Run, aucun processus ne tourne en permanence (c'est ce qui rend l'hébergement
peu coûteux). Cloud Scheduler lance donc cette commande toutes les 5 minutes (tâche
Cloud Run « jobs ») :
1. les événements restés en échec ou en attente sont retraités ;
2. les fichiers de reprise déposés depuis plus de 24 heures sans suite sont effacés ;
3. une fois par jour, les échéances manquantes sont générées, ainsi que les tâches pour les
   documents qui expirent ou ne sont plus à jour (D-050), les annonces de délais prolongés
   par le SPF sont relevées (D-089) et, en début de mois, le résumé de chaque employé
   (notification dans l'outil, D-052) ;
4. les travaux de la file procrastinate sont exécutés jusqu'à ce qu'elle soit vide.
"""

from typing import Any

from django.core.management import call_command
from django.core.management.base import BaseCommand

from apps.clients import hybrid, prospects
from apps.core import events
from apps.documents import digest, freshness, identity, inbox
from apps.documents import services as documents
from apps.integrations import official
from apps.mailbox import services as mail_services
from apps.mailbox import sync as mail_sync
from apps.reprise.models import purge_stale_uploads
from apps.tasks import deadlines, extensions
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
            self.stdout.write(f"Documents à revoir : {freshness.follow_up()} tâches créées")
            self.stdout.write(f"Résumés mensuels : {digest.monthly()} employés")
            self.stdout.write(f"Copies d'e-mails expirées effacées : {mail_sync.purge()}")
            self.stdout.write(f"Brouillons oubliés effacés : {mail_services.purge_drafts()}")
            self.stdout.write(f"Dossiers hybrides rendus libres : {hybrid.release_stale()}")
            self.stdout.write(f"Prospects sans suite signalés : {prospects.remind_stale()}")
            self.stdout.write(f"Délais du SPF, articles à vérifier : {extensions.watch()}")
        self.stdout.write(f"Relances préparées : {documents.send_due_reminders()}")
        self.stdout.write(f"Cartes d'identité demandées : {identity.request_renewals()}")
        self.stdout.write(f"Rappels d'échéances : {deadlines.send_reminders()}")
        self.stdout.write(f"E-mails relevés : {mail_sync.sync_all()}")
        self.stdout.write(f"Envois programmés partis : {mail_services.send_due()}")
        self.stdout.write(f"Fichiers non classés effacés : {inbox.purge()}")
        self.stdout.write(f"Sites officiels consultés : {official.refresh_due()} sociétés")
        call_command("procrastinate", "worker", "--one-shot")
