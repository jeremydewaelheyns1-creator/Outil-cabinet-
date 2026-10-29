"""Aperçu des documents dans le visualiseur (D-036).

Les pages d'un PDF sont transformées en images sur le serveur (pdftoppm) : le navigateur
n'affiche que des images, jamais le PDF lui-même — aucun contenu actif ne peut s'exécuter, et
l'aperçu est identique sur tous les navigateurs. Une image (JPG, PNG) s'affiche telle quelle.
Word et Excel n'ont pas d'aperçu : on les télécharge.
"""

from __future__ import annotations

import re
import shutil
import subprocess
import tempfile
from pathlib import Path

from .models import Document, InboxItem

Previewable = Document | InboxItem  # un document rangé, ou un fichier encore à classer

MAX_PAGES = 20
RESOLUTION = "110"  # points par pouce : lisible à l'écran, léger à charger
IMAGES = ("image/jpeg", "image/png")


def _run(command: list[str]) -> subprocess.CompletedProcess[bytes]:
    return subprocess.run(command, capture_output=True, timeout=60, check=False)  # noqa: S603


def _copy(document: Previewable, folder: str) -> Path:
    source = Path(folder) / "source"
    with document.file.open("rb") as handle:
        source.write_bytes(handle.read())
    return source


def page_count(document: Previewable) -> int:
    """Nombre de pages affichables (0 = pas d'aperçu pour ce format)."""
    if document.content_type in IMAGES:
        return 1
    if document.content_type != "application/pdf" or not shutil.which("pdfinfo"):
        return 0
    with tempfile.TemporaryDirectory(prefix="apercu-") as folder:
        result = _run(["pdfinfo", str(_copy(document, folder))])
    match = re.search(rb"^Pages:\s+(\d+)", result.stdout, re.MULTILINE)
    return min(int(match.group(1)), MAX_PAGES) if match else 0


def render_page(document: Previewable, number: int) -> tuple[bytes, str] | None:
    """Image de la page `number` (à partir de 1) et son type, ou None."""
    if number < 1 or number > MAX_PAGES:
        return None
    if document.content_type in IMAGES:
        if number != 1:
            return None
        with document.file.open("rb") as handle:
            return handle.read(), document.content_type
    if document.content_type != "application/pdf" or not shutil.which("pdftoppm"):
        return None
    with tempfile.TemporaryDirectory(prefix="apercu-") as folder:
        source = _copy(document, folder)
        target = Path(folder) / "page"
        _run(
            ["pdftoppm", "-r", RESOLUTION, "-f", str(number), "-l", str(number), "-png",
             "-singlefile", str(source), str(target)]
        )  # fmt: skip
        image = target.with_suffix(".png")
        return (image.read_bytes(), "image/png") if image.exists() else None
