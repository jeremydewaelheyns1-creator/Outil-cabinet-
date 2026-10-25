"""Lire les lignes « machine » d'une carte sur une vraie photo de téléphone (D-035, D-062).

Une photo réelle n'est jamais un scan : carte de travers, en perspective, floue, avec un
reflet, posée sur une table, parfois « couchée » (orientation rangée dans les métadonnées).
Tesseract seul ne lit rien dans ces conditions. On l'aide, tout sur le serveur du cabinet :

1. on remet la photo à l'endroit (métadonnées d'orientation) et en niveaux de gris ;
2. on cherche les bandes de texte larges et denses (la zone MRZ) par un traitement d'image
   classique (OpenCV, sans IA) ;
3. pour chaque bande : on la redresse, on la découpe, on l'agrandit, puis on essaie quelques
   versions (telle quelle, contrastée, noir et blanc) ;
4. on s'arrête dès qu'une lecture passe **tous** les chiffres de contrôle : une lecture fausse
   ne peut pas passer pour bonne. Sinon on essaie la photo retournée, puis tournée d'un quart.

Un délai maximal évite qu'une photo illisible ne bloque l'outil. Rien n'est conservé : les
images de travail sont en mémoire ou dans un dossier temporaire effacé aussitôt.
"""

from __future__ import annotations

import io
import os
import subprocess
import tempfile
import time
from collections.abc import Callable, Iterator
from pathlib import Path

import cv2
import numpy as np
from PIL import Image, ImageOps

WHITELIST = "ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789<"
WORK_SIZE = 1400  # côté le plus long de l'image de recherche des bandes
BAND_WIDTH = 1500  # largeur de la bande agrandie avant lecture
MAX_BANDS = 4
BUDGET_SECONDS = 40.0

Gray = np.ndarray


def load_gray(content: bytes) -> Gray | None:
    """Photo remise à l'endroit, en niveaux de gris (None si ce n'est pas une image)."""
    try:
        with Image.open(io.BytesIO(content)) as image:
            image.draft("L", (3000, 3000))  # JPEG très grand : décodage réduit, plus rapide
            return np.array(ImageOps.exif_transpose(image).convert("L"))
    except (OSError, ValueError, Image.DecompressionBombError):
        return None


def tesseract(gray: Gray, timeout: float = 15.0) -> str:
    """Une lecture Tesseract ; trop longue ou en échec → texte vide (on passe à la suivante)."""
    with tempfile.TemporaryDirectory(prefix="lecture-") as folder:
        path = Path(folder) / "bande.png"
        cv2.imwrite(str(path), gray)
        try:
            result = subprocess.run(  # noqa: S603 (commande fixe)
                ["tesseract", str(path), "-", "--psm", "6",  # noqa: S607
                 "-c", f"tessedit_char_whitelist={WHITELIST}"],
                capture_output=True, text=True, timeout=timeout, check=False,
                env={**os.environ, "OMP_THREAD_LIMIT": "1"},
            )  # fmt: skip
        except (OSError, subprocess.TimeoutExpired):
            return ""
        return result.stdout


def bands(gray: Gray) -> list[Gray]:
    """Zones qui ressemblent à la bande MRZ (larges, denses), redressées et agrandies."""
    height, width = gray.shape
    scale = WORK_SIZE / max(height, width)
    small = cv2.resize(
        gray, (int(width * scale), int(height * scale)), interpolation=cv2.INTER_AREA
    )
    small = cv2.GaussianBlur(small, (3, 3), 0)
    rect = cv2.getStructuringElement(cv2.MORPH_RECT, (13, 5))
    square = cv2.getStructuringElement(cv2.MORPH_RECT, (21, 21))
    # Texte sombre sur fond clair, puis les lettres d'une ligne fondues en une bande.
    blackhat = cv2.morphologyEx(small, cv2.MORPH_BLACKHAT, rect)
    gradient = np.absolute(cv2.Sobel(blackhat, cv2.CV_32F, 1, 0, ksize=-1))
    span = float(gradient.max() - gradient.min()) or 1.0
    gradient = (255 * (gradient - gradient.min()) / span).astype("uint8")
    gradient = cv2.morphologyEx(gradient, cv2.MORPH_CLOSE, rect)
    mask = cv2.threshold(gradient, 0, 255, cv2.THRESH_BINARY | cv2.THRESH_OTSU)[1]
    mask = cv2.morphologyEx(mask, cv2.MORPH_CLOSE, square)
    mask = cv2.erode(mask, np.ones((3, 3), np.uint8), iterations=2)
    contours, _ = cv2.findContours(mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    found = []
    for contour in contours:
        (cx, cy), (rw, rh), angle = cv2.minAreaRect(contour)
        if rw < rh:
            rw, rh, angle = rh, rw, angle + 90
        if rw < small.shape[1] * 0.15 or rw / max(rh, 1.0) < 2.5:
            continue
        found.append((rw * rh, cx / scale, cy / scale, rw / scale, rh / scale, angle))
    found.sort(reverse=True)
    result = []
    for _, cx, cy, rw, rh, angle in found[:MAX_BANDS]:
        while angle > 45:
            angle -= 90
        while angle < -45:
            angle += 90
        turn = cv2.getRotationMatrix2D((cx, cy), angle, 1.0)
        straight = cv2.warpAffine(gray, turn, (width, height), flags=cv2.INTER_CUBIC,
                                  borderMode=cv2.BORDER_REPLICATE)  # fmt: skip
        pad_w = rw * 0.08
        # Bande très étroite = une seule des trois lignes trouvée : on prend aussi ses voisines.
        pads = [rh * 0.35] if rw / max(rh, 1.0) < 12 else [rh * 2.6, rh * 0.35]
        for pad_h in pads:
            x0, x1 = int(max(0, cx - rw / 2 - pad_w)), int(min(width, cx + rw / 2 + pad_w))
            y0, y1 = int(max(0, cy - rh / 2 - pad_h)), int(min(height, cy + rh / 2 + pad_h))
            band = straight[y0:y1, x0:x1]
            if band.size == 0:
                continue
            factor = max(1.0, BAND_WIDTH / band.shape[1])
            result.append(
                cv2.resize(band, None, fx=factor, fy=factor, interpolation=cv2.INTER_CUBIC)
            )
    return result


def versions(band: Gray) -> Iterator[Gray]:
    yield band
    contrasted = cv2.createCLAHE(clipLimit=2.0, tileGridSize=(8, 8)).apply(band)
    yield cv2.threshold(contrasted, 0, 255, cv2.THRESH_BINARY | cv2.THRESH_OTSU)[1]
    yield cv2.adaptiveThreshold(
        band, 255, cv2.ADAPTIVE_THRESH_GAUSSIAN_C, cv2.THRESH_BINARY, 41, 15
    )


def attempts(gray: Gray) -> Iterator[Gray]:
    """Ce qu'on fait lire, du plus probable au moins probable."""
    if max(gray.shape) <= 2200:  # scan ou capture nette et droite : lue telle quelle
        yield gray
    for quarter in (0, 2, 1, 3):  # à l'endroit, à l'envers, puis couchée d'un côté ou de l'autre
        turned = gray if quarter == 0 else np.ascontiguousarray(np.rot90(gray, quarter))
        for band in bands(turned):
            yield from versions(band)


def read(content: bytes, is_valid: Callable[[str], bool], budget: float = BUDGET_SECONDS) -> str:
    """Texte de la meilleure lecture : la première qui passe tous les contrôles, sinon tout ce
    qui a été lu (pour que l'outil explique pourquoi la carte est « à confirmer »)."""
    gray = load_gray(content)
    if gray is None:
        return ""
    deadline = time.monotonic() + budget
    texts = []
    for image in attempts(gray):
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            break
        text = tesseract(image, timeout=min(15.0, remaining))
        if is_valid(text):
            return text
        texts.append(text)
    return "\n".join(texts)
