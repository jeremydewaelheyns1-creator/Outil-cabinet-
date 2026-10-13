"""Importe une archive « KBO Open Data » (export complet ou mise à jour).

    python manage.py import_bce chemin/KboOpenData_0141_2026_10_Full.zip
    python manage.py import_bce chemin/KboOpenData_0142_2026_10_13_Update.zip

Plusieurs archives peuvent être données : elles sont appliquées dans l'ordre de leur numéro.
"""

from pathlib import Path
from typing import Any

from django.core.management.base import BaseCommand, CommandError, CommandParser

from apps.bce.opendata import Archive, OpenDataError, import_archive


class Command(BaseCommand):
    help = "Importe une ou plusieurs archives KBO Open Data de la BCE."

    def add_arguments(self, parser: CommandParser) -> None:
        parser.add_argument("archives", nargs="+", type=Path)

    def handle(self, *args: Any, **options: Any) -> None:
        paths: list[Path] = options["archives"]
        for path in paths:
            if not path.is_file():
                raise CommandError(f"Fichier introuvable : {path}")
        try:
            ordered = sorted(paths, key=self._extract_number)
            for path in ordered:
                run = import_archive(path)
                self.stdout.write(
                    self.style.SUCCESS(
                        f"{path.name} : {run.get_kind_display()} n° {run.extract_number} "
                        f"importé ({run.changed_enterprises} entreprises modifiées)."
                    )
                )
                if run.notes:
                    self.stdout.write(self.style.WARNING(run.notes))
        except OpenDataError as exc:
            raise CommandError(str(exc)) from exc

    @staticmethod
    def _extract_number(path: Path) -> int:
        with Archive(path) as archive:
            return archive.extract_number or 0
