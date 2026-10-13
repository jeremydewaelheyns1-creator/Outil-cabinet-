"""Analyse ou importe un export clients FID-Manager depuis la ligne de commande.

python manage.py import_fid_clients export.xlsx              # analyse seule
python manage.py import_fid_clients export.xlsx --appliquer  # import réel
"""

from pathlib import Path
from typing import Any

from django.core.management.base import BaseCommand, CommandError, CommandParser

from apps.core.models import User
from apps.reprise.importer import ImportFileError, Report, run_import


class Command(BaseCommand):
    help = "Analyse (par défaut) ou importe un export clients FID-Manager (.xlsx)."

    def add_arguments(self, parser: CommandParser) -> None:
        parser.add_argument("fichier", type=Path)
        parser.add_argument("--appliquer", action="store_true", help="Importer réellement.")
        parser.add_argument("--utilisateur", help="E-mail de l'auteur de l'import.")

    def handle(self, *args: Any, **options: Any) -> None:
        path: Path = options["fichier"]
        if not path.is_file():
            raise CommandError(f"Fichier introuvable : {path}")
        actor = None
        if options["utilisateur"]:
            actor = User.objects.filter(email=options["utilisateur"].lower()).first()
            if actor is None:
                raise CommandError("Utilisateur inconnu.")
        try:
            report = run_import(path, file_name=path.name, apply=options["appliquer"], actor=actor)
        except ImportFileError as exc:
            raise CommandError(str(exc)) from exc
        self.print_report(report)

    def print_report(self, report: Report) -> None:
        mode = "IMPORT" if report.applied else "ANALYSE (rien n'a été modifié)"
        self.stdout.write(self.style.MIGRATE_HEADING(f"{mode} — {report.file_name}"))
        self.stdout.write(f"En-têtes ligne {report.header_row} de la feuille « {report.sheet} »")
        for header, target in report.columns.items():
            self.stdout.write(f"  {header} → {target}")
        if report.unmapped:
            self.stdout.write(
                self.style.WARNING(f"Colonnes ignorées : {', '.join(report.unmapped)}")
            )
        self.stdout.write(
            f"Lignes : {report.rows} — à créer : {report.created} — à compléter : "
            f"{report.updated} — inchangées : {report.unchanged} — ignorées : {report.skipped}"
        )
        for issue in report.issues:
            style = self.style.ERROR if issue.level == "error" else self.style.WARNING
            self.stdout.write(style(f"  ligne {issue.row} [{issue.field}] {issue.message}"))
        for conflict in report.conflicts:
            self.stdout.write(
                f"  ligne {conflict.row} {conflict.client} : {conflict.field} "
                f"« {conflict.existing} » ≠ « {conflict.imported} » (conservé)"
            )
