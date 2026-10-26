"""Logo du cabinet, ajouté aux signatures des e-mails (D-066).

Déposé une fois par un administrateur. L'image est **refaite** par l'outil (PNG, 600 × 200
pixels au plus) : seuls ses pixels sont gardés, rien de ce qui pourrait être caché dans le
fichier d'origine. Elle part **jointe** à chaque e-mail et s'affiche dans la signature, sans
rien charger depuis Internet (pas de lien qui pisterait l'ouverture du message).
"""

from __future__ import annotations

import io

from django.core.exceptions import ValidationError
from PIL import Image, UnidentifiedImageError

MAX_UPLOAD = 2 * 1024 * 1024
MAX_RESULT = 200 * 1024
BOX = (600, 200)
CONTENT_ID = "logo-cabinet"
DISPLAY_HEIGHT = 60  # hauteur affichée dans la signature (pixels)


def prepare(content: bytes) -> bytes:
    """PNG propre à partir d'un PNG ou JPEG déposé (sinon ValidationError lisible)."""
    if len(content) > MAX_UPLOAD:
        raise ValidationError("Image trop lourde (2 Mo au maximum).")
    try:
        with Image.open(io.BytesIO(content)) as image:
            if image.format not in {"PNG", "JPEG"}:
                raise ValidationError("Déposez une image PNG ou JPEG.")
            if image.width * image.height > 25_000_000:
                raise ValidationError("Image trop grande.")
            image.load()
            clean = image.convert("RGBA")
    except (UnidentifiedImageError, OSError, Image.DecompressionBombError) as exc:
        raise ValidationError("Ce fichier n'est pas une image lisible.") from exc
    clean.thumbnail(BOX)
    out = io.BytesIO()
    clean.save(out, format="PNG", optimize=True)
    data = out.getvalue()
    if len(data) > MAX_RESULT:
        raise ValidationError("Logo trop détaillé : utilisez une image plus simple ou plus petite.")
    return data


def size(data: bytes) -> tuple[int, int]:
    with Image.open(io.BytesIO(data)) as image:
        return image.width, image.height
