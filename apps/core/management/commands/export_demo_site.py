"""Exporte une démo cliquable de l'outil en pages HTML fixes (pour GitHub Pages).

    python manage.py demo
    python manage.py export_demo_site site/ --base /Outil-cabinet-/

Les écrans sont produits par l'application elle-même, avec les données fictives de la commande
`demo` : ce qu'on voit est exactement l'outil. Mais c'est une photo : les boutons qui
enregistrent quelque chose sont désactivés. Jamais à lancer sur une base contenant de vraies
données (la commande le refuse).
"""

from __future__ import annotations

import re
import shutil
from collections import deque
from html import escape
from pathlib import Path
from typing import Any

from allauth.mfa.models import Authenticator
from django.conf import settings
from django.core.management.base import BaseCommand, CommandError, CommandParser
from django.test import Client as BrowserClient
from django.test.utils import override_settings
from django.utils import timezone

from apps.clients.models import Client
from apps.core.models import User

DEMO_EMAIL = "demo@cabinet.test"
SKIP_PREFIXES = (
    "/compte/", "/gestion/", "/static/", "/sante/", "/clients/export/", "/media/",
)  # fmt: skip
ATTRIBUTE = re.compile(r'(\s(?:href|src|action|hx-get|hx-post))="(/[^"]*)"')
OPEN_DOSSIER = re.compile(r"^/clients/dossier/ouvrir/(\d+)/")

BANNER = """
<div id="demo-banner" style="position:sticky;top:0;z-index:100;background:#fff4d6;color:#5c4400;
  border-bottom:1px solid #f1d79b;padding:.45rem 1rem;font:14px system-ui,sans-serif;
  display:flex;gap:1rem;flex-wrap:wrap;align-items:center">
  <strong>Démo — données inventées.</strong>
  <span>Vous pouvez naviguer partout ; les boutons qui enregistrent sont désactivés.</span>
  <span style="margin-left:auto">Version du {stamp} ·
    <a href="{base}nouveautes/" style="color:#5c4400;font-weight:600">Nouveautés</a></span>
</div>
<div id="demo-toast" style="display:none;position:fixed;bottom:1rem;left:50%;
  transform:translateX(-50%);background:#14243b;color:#fff;padding:.6rem 1rem;border-radius:8px;
  font:14px system-ui,sans-serif;z-index:101">Démo : cette action est désactivée.</div>
<script>
(function () {
  function toast() {
    var t = document.getElementById("demo-toast");
    t.style.display = "block";
    clearTimeout(window.__demoToast);
    window.__demoToast = setTimeout(function () { t.style.display = "none"; }, 2200);
  }
  document.addEventListener("submit", function (e) {
    if ((e.target.method || "get").toLowerCase() !== "get") { e.preventDefault(); toast(); }
  }, true);
  document.addEventListener("htmx:beforeRequest", function (e) {
    var verb = (e.detail.requestConfig && e.detail.requestConfig.verb) || "get";
    if (verb.toLowerCase() !== "get") { e.preventDefault(); toast(); }
  });
})();
</script>
"""


class Command(BaseCommand):
    help = "Exporte une démo statique de l'outil (données fictives) pour GitHub Pages."

    def add_arguments(self, parser: CommandParser) -> None:
        parser.add_argument("dossier", type=Path)
        parser.add_argument("--base", default="/", help="Chemin du site, ex. /Outil-cabinet-/")
        parser.add_argument("--max-pages", type=int, default=400)

    def handle(self, *args: Any, **options: Any) -> None:
        out: Path = options["dossier"]
        base: str = "/" + options["base"].strip("/") + "/" if options["base"].strip("/") else "/"
        self._refuse_real_data()
        user = User.objects.get(email=DEMO_EMAIL)
        Authenticator.objects.get_or_create(
            user=user, type=Authenticator.Type.TOTP, defaults={"data": {"secret": "demo"}}
        )
        if out.exists():
            shutil.rmtree(out)
        out.mkdir(parents=True)
        shutil.copytree(Path(settings.BASE_DIR) / "static", out / "static")
        (out / ".nojekyll").write_text("")

        stamp = timezone.localtime().strftime("%d/%m/%Y %H:%M")
        banner = BANNER.replace("{stamp}", stamp).replace("{base}", base)
        with override_settings(ALLOWED_HOSTS=["testserver"], SECURE_SSL_REDIRECT=False):
            browser = BrowserClient()
            browser.force_login(user)
            pages = self._crawl(browser, out, base, banner, options["max_pages"])
            # Liste des derniers dossiers du sélecteur (chargée à l'ouverture, en HTMX).
            fragment = browser.get("/clients/dossier/recherche/").content.decode()
            self._write(out, "/clients/dossier/recherche/", self._rewrite(fragment, base))
        self._write(out, "/nouveautes/", self._news_page(base, banner))
        self.stdout.write(self.style.SUCCESS(f"{pages} pages exportées dans {out}"))

    # ------------------------------------------------------------------------------------------

    def _refuse_real_data(self) -> None:
        if not User.objects.filter(email=DEMO_EMAIL).exists():
            raise CommandError("Lancez d'abord `manage.py demo` (base de démonstration).")
        if (
            Client.objects.exclude(reference__startswith="D")
            .exclude(reference__startswith="P")
            .exists()
        ):
            raise CommandError("Cette base contient d'autres fiches que la démo : export refusé.")

    def _crawl(self, browser: BrowserClient, out: Path, base: str, banner: str, limit: int) -> int:
        queue: deque[str] = deque(["/"])
        seen = {"/"}
        count = 0
        while queue and count < limit:
            path = queue.popleft()
            response = browser.get(path)
            if response.status_code != 200 or "text/html" not in response.get("Content-Type", ""):
                continue
            html = response.content.decode()
            for link in re.findall(r'\shref="(/[^"#?]*)', html):
                link = OPEN_DOSSIER.sub(r"/clients/\1/", link)
                if link not in seen and not link.startswith(SKIP_PREFIXES):
                    seen.add(link)
                    queue.append(link)
            # Visualiseur de documents : fenêtre chargée en HTMX et images des pages.
            for link in re.findall(r'\shx-get="(/clients/[^"]*/apercu/[^"]*/fenetre/)"', html):
                if link not in seen:
                    seen.add(link)
                    fragment = browser.get(link)
                    if fragment.status_code == 200:
                        self._write(out, link, self._rewrite(fragment.content.decode(), base))
                        for image in re.findall(
                            r'\ssrc="(/clients/[^"]*\.png)"', fragment.content.decode()
                        ):
                            self._write_binary(out, image, browser.get(image))
            html = self._rewrite(html, base).replace("<body", "<body data-demo", 1)
            html = re.sub(r"(<body[^>]*>)", r"\1" + banner.replace("\\", "\\\\"), html, count=1)
            self._write(out, path, html)
            count += 1
        return count

    @staticmethod
    def _rewrite(html: str, base: str) -> str:
        def fix(match: re.Match[str]) -> str:
            attribute, url = match.group(1), match.group(2)
            url = OPEN_DOSSIER.sub(r"/clients/\1/", url)
            if attribute.strip() == "href":
                url = url.split("?", 1)[0]
            return f'{attribute}="{base}{url.lstrip("/")}"'

        return ATTRIBUTE.sub(fix, html)

    @staticmethod
    def _write_binary(out: Path, path: str, response: Any) -> None:
        if response.status_code == 200:
            target = out / path.strip("/")
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(response.content)

    @staticmethod
    def _write(out: Path, path: str, html: str) -> None:
        target = out / path.strip("/") / "index.html" if path.strip("/") else out / "index.html"
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(html, encoding="utf-8")

    @staticmethod
    def _news_page(base: str, banner: str) -> str:
        """Page « Nouveautés » tirée de docs/NOUVEAUTES.md (titres, listes, paragraphes)."""
        source = (Path(settings.BASE_DIR) / "docs" / "NOUVEAUTES.md").read_text(encoding="utf-8")
        body: list[str] = []
        block: list[str] = []
        kind = ""

        def inline(text: str) -> str:
            text = escape(text)
            text = re.sub(r"\*\*(.+?)\*\*", r"<strong>\1</strong>", text)
            return re.sub(r"`(.+?)`", r"<code>\1</code>", text)

        def flush() -> None:
            nonlocal block, kind
            if kind == "li":
                body.append(f"<li>{inline(' '.join(block))}</li>")
            elif kind == "p":
                body.append(f"<p>{inline(' '.join(block))}</p>")
            block, kind = [], ""

        in_list = False
        for raw in source.splitlines():
            line = raw.rstrip()
            if line.startswith("- "):
                flush()
                if not in_list:
                    body.append("<ul>")
                    in_list = True
                block, kind = [line[2:]], "li"
            elif line.startswith("  ") and kind == "li":
                block.append(line.strip())
            elif not line.strip():
                flush()
            else:
                flush()
                if in_list:
                    body.append("</ul>")
                    in_list = False
                if line.startswith("## "):
                    body.append(f"<h2 style='margin-top:1.5rem'>{inline(line[3:])}</h2>")
                elif line.startswith("# "):
                    body.append(f"<h1>{inline(line[2:])}</h1>")
                else:
                    block, kind = [line], "p"
        flush()
        if in_list:
            body.append("</ul>")
        return (
            '<!DOCTYPE html><html lang="fr"><head><meta charset="utf-8">'
            '<meta name="viewport" content="width=device-width, initial-scale=1">'
            f'<title>Nouveautés</title><link rel="stylesheet" href="{base}static/css/app.css">'
            f"</head><body>{banner}"
            '<main class="main" style="max-width:860px;margin:0 auto">'
            f'<p><a href="{base}">← Ouvrir la démo</a></p>'
            f'<div class="card">{"".join(body)}</div></main></body></html>'
        )
