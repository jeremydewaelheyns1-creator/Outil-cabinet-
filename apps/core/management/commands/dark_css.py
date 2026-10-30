"""Fabrique static/css/dark.css (mode sombre, D-119) à partir de static/css/app.css.

Chaque règle qui fixe une couleur (fond, texte, bordure) est recopiée pour
`html[data-theme="dark"]` avec la couleur transposée : fonds clairs → foncés, textes foncés →
clairs ; les couleurs franches (boutons, vert « fait ») restent. Les variables du thème sont
redéfinies à la main (PALETTE). Une deuxième copie s'applique au réglage « Automatique » quand
l'ordinateur est en mode sombre.

À relancer après une modification de app.css : `python manage.py dark_css`.
"""

from __future__ import annotations

import colorsys
import re
from pathlib import Path
from typing import Any

from django.conf import settings
from django.core.management.base import BaseCommand

PALETTE = """
  --bg: #121120;
  --surface: #1c1b2e;
  --surface-muted: #23223a;
  --border: #2f2d48;
  --border-strong: #3d3a5c;
  --text: #e8e6f3;
  --text-muted: #a9a6c4;
  --ink: #f1f0fa;
  --ink-bg: #4f46e5;
  --primary: #7a73f5;
  --primary-hover: #a5a0ff;
  --primary-soft: #2a2752;
  --primary-text: #c7c4ff;
  --success: #6ee7a1;
  --success-soft: #16301f;
  --warning: #fbbf6a;
  --warning-soft: #33260f;
  --danger: #fb7c98;
  --danger-soft: #3a1622;
  --alarm: #fb7185;
  --shadow-raised: 0 12px 40px rgb(0 0 0 / 45%);
  --topbar-bg: #1c1b2e;
  color-scheme: dark;
"""

HEX = re.compile(r"#([0-9a-fA-F]{6}|[0-9a-fA-F]{3})\b")
RGB = re.compile(r"rgba?\(\s*(\d+)[ ,]+(\d+)[ ,]+(\d+)\s*(?:[/,]\s*([\d.]+%?))?\s*\)")
NAMED = re.compile(r"\b(white)\b")
INK = re.compile(r"var\(--ink(?=[,)])")
COLOR_PROPS = ("color", "background", "border", "outline", "box-shadow", "fill", "stroke")


def _role(prop: str) -> str:
    if prop.startswith("background"):
        return "bg"
    if prop.startswith(("border", "outline", "box-shadow")):
        return "line"
    return "fg"


def _shift(r: float, g: float, b: float, role: str) -> tuple[float, float, float]:
    h, light, s = colorsys.rgb_to_hls(r, g, b)
    if role == "bg" and light > 0.8:  # fond clair (blanc, pastel) → fond foncé teinté
        light, s = 0.13 + (1 - light) * 0.7, s * 0.45
    elif role == "line" and light > 0.7:  # bordure claire → bordure foncée
        light, s = 0.27, s * 0.4
    elif role == "fg" and light < 0.45:  # texte foncé → texte clair
        light, s = 0.86 - light * 0.35, min(s, 0.75)
    else:
        return r, g, b
    return colorsys.hls_to_rgb(h, light, s)


def _hex(r: float, g: float, b: float) -> str:
    return "#{:02x}{:02x}{:02x}".format(*(round(c * 255) for c in (r, g, b)))


def transform(value: str, role: str) -> str:
    def from_hex(match: re.Match[str]) -> str:
        raw = match.group(1)
        if len(raw) == 3:
            raw = "".join(c * 2 for c in raw)
        r, g, b = (int(raw[i : i + 2], 16) / 255 for i in (0, 2, 4))
        return _hex(*_shift(r, g, b, role))

    def from_rgb(match: re.Match[str]) -> str:
        r, g, b = (int(match.group(i)) / 255 for i in (1, 2, 3))
        r, g, b = _shift(r, g, b, role)
        alpha = match.group(4)
        inner = f"{round(r * 255)} {round(g * 255)} {round(b * 255)}"
        return f"rgb({inner} / {alpha})" if alpha else f"rgb({inner})"

    value = NAMED.sub("#ffffff", value)
    value = HEX.sub(from_hex, value)
    return RGB.sub(from_rgb, value)


def _strip_comments(css: str) -> str:
    return re.sub(r"/\*.*?\*/", "", css, flags=re.S)


def _blocks(css: str) -> list[tuple[str, Any]]:
    """[(prélude, contenu)] au premier niveau ; le contenu d'un @media est lui-même découpé."""
    out: list[tuple[str, Any]] = []
    i, n = 0, len(css)
    while i < n:
        start = css.find("{", i)
        if start == -1:
            break
        prelude = css[i:start].strip()
        depth, j = 1, start + 1
        while j < n and depth:
            depth += {"{": 1, "}": -1}.get(css[j], 0)
            j += 1
        body = css[start + 1 : j - 1]
        out.append((prelude, _blocks(body) if prelude.startswith("@media") else body))
        i = j
    return out


def _prefix(selectors: str, scope: str) -> str:
    parts = []
    for sel in selectors.split(","):
        sel = sel.strip()
        if sel in (":root", "html"):
            parts.append(scope)
        elif sel.startswith("html"):
            parts.append(scope + sel[4:])
        else:
            parts.append(f"{scope} {sel}")
    return ", ".join(parts)


def _rules(blocks: list[tuple[str, Any]], scope: str) -> list[str]:
    out: list[str] = []
    for prelude, body in blocks:
        if prelude.startswith("@media"):
            inner = _rules(body, scope)
            if inner:
                out.append(prelude + " {\n" + "\n".join(inner) + "\n}")
            continue
        if prelude.startswith("@") or prelude in (":root",) or prelude.startswith(":root"):
            continue
        decls = []
        for decl in body.split(";"):
            if ":" not in decl:
                continue
            prop, value = (x.strip() for x in decl.split(":", 1))
            if not prop.startswith(COLOR_PROPS) or prop.startswith("--"):
                continue
            if _role(prop) == "bg" and INK.search(value):
                # Pastille foncée à texte blanc (onglet actif…) : reste foncée en mode sombre.
                decls.append(f"{prop}: {INK.sub('var(--ink-bg', value)}")
                continue
            if not (HEX.search(value) or RGB.search(value) or NAMED.search(value)):
                continue
            new = transform(value, _role(prop))
            if new != value:
                decls.append(f"{prop}: {new}")
        if decls:
            out.append(f"{_prefix(prelude, scope)} {{ {'; '.join(decls)}; }}")
    return out


def build(css: str) -> str:
    blocks = _blocks(_strip_comments(css))
    dark = 'html[data-theme="dark"]'
    auto = 'html[data-theme="auto"]'
    head = (
        "/* Mode sombre (D-119) : fichier fabriqué par `python manage.py dark_css` à partir de\n"
        "   app.css. Ne pas modifier à la main : relancer la commande. */\n"
    )
    main = [
        f"{dark} {{{PALETTE}}}",
        *_rules(blocks, dark),
        f"{dark} body {{ background: var(--bg); }}",
    ]
    system = [
        f"{auto} {{{PALETTE}}}",
        *_rules(blocks, auto),
        f"{auto} body {{ background: var(--bg); }}",
    ]
    return (
        head
        + "\n".join(main)
        + "\n\n@media (prefers-color-scheme: dark) {\n"
        + "\n".join(system)
        + "\n}\n"
    )


class Command(BaseCommand):
    help = "Fabrique static/css/dark.css (mode sombre) à partir de static/css/app.css."

    def handle(self, *args: Any, **options: Any) -> None:
        folder = Path(settings.BASE_DIR) / "static" / "css"
        (folder / "dark.css").write_text(build((folder / "app.css").read_text()), encoding="utf-8")
        self.stdout.write("static/css/dark.css fabriqué.")
