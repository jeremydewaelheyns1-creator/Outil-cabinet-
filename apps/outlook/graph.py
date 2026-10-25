"""Relier une boîte Outlook et envoyer depuis elle, par Microsoft Graph (D-044).

Connexion « Se connecter avec Microsoft » (OAuth 2.0, code d'autorisation + PKCE) :
- l'employé se connecte chez Microsoft, jamais dans l'outil : l'outil ne voit pas son mot de
  passe ;
- droits demandés : `Mail.Send` (envoyer en son nom), `User.Read` (connaître son adresse),
  `offline_access` (pouvoir envoyer plus tard sans se reconnecter). **Pas de lecture de
  la boîte** ;
- le jeton de renouvellement est chiffré en base ; l'employé peut délier sa boîte dans
  l'outil, et l'administrateur Microsoft peut retirer l'accès à tout moment.

Les e-mails partent de sa propre adresse et sont gardés dans ses « Éléments envoyés ».
Rien de ce que renvoie Microsoft n'est écrit dans les journaux (seulement le code d'erreur).
"""

from __future__ import annotations

import base64
import contextlib
import hashlib
import logging
import secrets
from dataclasses import dataclass
from typing import Any
from urllib.parse import urlencode

import httpx
from cryptography.fernet import Fernet, InvalidToken
from django.conf import settings
from django.utils import timezone

from apps.core.models import User

from .models import MailboxLink

logger = logging.getLogger(__name__)

LOGIN = "https://login.microsoftonline.com"
GRAPH = "https://graph.microsoft.com/v1.0"
SCOPES = "offline_access User.Read Mail.Send"
READ_SCOPES = f"{SCOPES} Mail.Read"  # D-060 : seulement si l'employé active la lecture
MAX_ATTACHMENTS_BYTES = 3 * 1024 * 1024  # limite de Graph pour un envoi en une fois


class MailboxError(Exception):
    """Envoi ou connexion impossible : message lisible, sans donnée sensible."""


@dataclass(frozen=True)
class Attachment:
    name: str
    content: bytes
    content_type: str = "application/pdf"


def configured() -> bool:
    return bool(
        settings.OUTLOOK_TENANT_ID and settings.OUTLOOK_CLIENT_ID and settings.OUTLOOK_CLIENT_SECRET
    )


def _http() -> httpx.Client:
    return httpx.Client(timeout=settings.OUTLOOK_TIMEOUT_SECONDS)


# --- Chiffrement du jeton ---------------------------------------------------------------------


def _fernet() -> Fernet:
    key = settings.MAILBOX_TOKEN_KEY
    if not key:
        digest = hashlib.sha256(f"boite-outlook:{settings.SECRET_KEY}".encode()).digest()
        key = base64.urlsafe_b64encode(digest).decode()
    return Fernet(key)


def encrypt(token: str) -> str:
    return _fernet().encrypt(token.encode()).decode()


def decrypt(token: str) -> str:
    try:
        return _fernet().decrypt(token.encode()).decode()
    except InvalidToken as exc:
        raise MailboxError("Boîte à relier à nouveau.") from exc


# --- Connexion --------------------------------------------------------------------------------


def pkce() -> tuple[str, str]:
    """(secret gardé en session, empreinte envoyée à Microsoft)."""
    verifier = secrets.token_urlsafe(64)
    challenge = base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest())
    return verifier, challenge.decode().rstrip("=")


def authorize_url(
    redirect_uri: str, state: str, challenge: str, login_hint: str = "", *, read: bool = False
) -> str:
    params = {
        "client_id": settings.OUTLOOK_CLIENT_ID,
        "response_type": "code",
        "redirect_uri": redirect_uri,
        "response_mode": "query",
        "scope": READ_SCOPES if read else SCOPES,
        "state": state,
        "code_challenge": challenge,
        "code_challenge_method": "S256",
        "prompt": "select_account",
    }
    if login_hint:
        params["login_hint"] = login_hint
    return f"{LOGIN}/{settings.OUTLOOK_TENANT_ID}/oauth2/v2.0/authorize?{urlencode(params)}"


def _token(data: dict[str, str], http: httpx.Client, scope: str = SCOPES) -> dict[str, Any]:
    payload = {
        "client_id": settings.OUTLOOK_CLIENT_ID,
        "client_secret": settings.OUTLOOK_CLIENT_SECRET,
        "scope": scope,
        **data,
    }
    url = f"{LOGIN}/{settings.OUTLOOK_TENANT_ID}/oauth2/v2.0/token"
    try:
        response = http.post(url, data=payload)
    except httpx.HTTPError as exc:
        raise MailboxError("Microsoft ne répond pas : réessayez dans un instant.") from exc
    if response.status_code != 200:
        error = ""
        with contextlib.suppress(ValueError):
            error = str(response.json().get("error", ""))
        logger.warning("Jeton Microsoft refusé (code %s, %s)", response.status_code, error)
        raise MailboxError("invalid_grant" if error == "invalid_grant" else "Microsoft a refusé.")
    result: dict[str, Any] = response.json()
    return result


def connect(
    user: User,
    *,
    code: str,
    redirect_uri: str,
    verifier: str,
    read: bool = False,
    http: httpx.Client | None = None,
) -> MailboxLink:
    http = http or _http()
    tokens = _token(
        {"grant_type": "authorization_code", "code": code, "redirect_uri": redirect_uri,
         "code_verifier": verifier},
        http, READ_SCOPES if read else SCOPES,
    )  # fmt: skip
    granted = str(tokens.get("scope", ""))
    if read and "Mail.Read" not in granted:
        raise MailboxError("Le droit de lire les e-mails n'a pas été accordé.")
    if "Mail.Send" not in str(tokens.get("scope", "")) or not tokens.get("refresh_token"):
        raise MailboxError("Le droit d'envoyer des e-mails n'a pas été accordé.")
    profile = http.get(
        f"{GRAPH}/me?$select=mail,userPrincipalName",
        headers={"Authorization": f"Bearer {tokens['access_token']}"},
    )
    if profile.status_code != 200:
        raise MailboxError("Adresse de la boîte introuvable.")
    data = profile.json()
    address = str(data.get("mail") or data.get("userPrincipalName") or "")
    if "@" not in address:
        raise MailboxError("Adresse de la boîte introuvable.")
    previous = MailboxLink.objects.filter(user=user).first()
    defaults: dict[str, Any] = {
        "address": address,
        "token": encrypt(str(tokens["refresh_token"])),
        "connected_at": timezone.now(),
        "broken_at": None,
        "scopes": READ_SCOPES if read else SCOPES,
        "sync_error": "",
    }
    if read:
        defaults["read_enabled"] = True
        if previous is None or previous.read_since is None or previous.address != address:
            # Seuls les e-mails reçus à partir de l'activation sont lus (pas l'historique).
            defaults.update(read_since=timezone.now(), inbox_cursor=None, sent_cursor=None)
    elif previous is not None and previous.read_enabled:
        defaults.update(read_enabled=False)
    link, _ = MailboxLink.objects.update_or_create(user=user, defaults=defaults)
    return link


def disconnect(user: User) -> None:
    MailboxLink.objects.filter(user=user).delete()


# --- Envoi ------------------------------------------------------------------------------------


def mailbox_for(user: User | None) -> MailboxLink | None:
    """La boîte reliée et utilisable de cet employé (si Outlook est configuré)."""
    if user is None or not configured():
        return None
    link = MailboxLink.objects.filter(user=user, broken_at__isnull=True).first()
    return link


def _access_token(link: MailboxLink, http: httpx.Client) -> str:
    try:
        tokens = _token(
            {"grant_type": "refresh_token", "refresh_token": decrypt(link.token)},
            http, link.scopes or SCOPES,
        )  # fmt: skip
    except MailboxError as exc:
        if str(exc) in ("invalid_grant", "Boîte à relier à nouveau."):
            link.broken_at = timezone.now()
            link.save(update_fields=["broken_at"])
            raise MailboxError(
                "Votre boîte Outlook doit être reliée à nouveau (accès expiré ou retiré)."
            ) from exc
        raise
    if tokens.get("refresh_token"):  # Microsoft renouvelle le jeton : on garde le nouveau
        link.token = encrypt(str(tokens["refresh_token"]))
        link.save(update_fields=["token"])
    return str(tokens["access_token"])


def send(
    link: MailboxLink,
    *,
    to: str,
    subject: str,
    body: str,
    attachments: list[Attachment] | None = None,
    http: httpx.Client | None = None,
) -> None:
    """Envoie depuis la boîte de l'employé ; copie gardée dans ses « Éléments envoyés »."""
    attachments = attachments or []
    if sum(len(a.content) for a in attachments) > MAX_ATTACHMENTS_BYTES:
        raise MailboxError("Pièce jointe trop lourde pour un envoi (3 Mo au maximum).")
    http = http or _http()
    token = _access_token(link, http)
    message: dict[str, Any] = {
        "subject": subject,
        "body": {"contentType": "Text", "content": body},
        "toRecipients": [{"emailAddress": {"address": to}}],
    }
    if attachments:
        message["attachments"] = [
            {
                "@odata.type": "#microsoft.graph.fileAttachment",
                "name": a.name,
                "contentType": a.content_type,
                "contentBytes": base64.b64encode(a.content).decode(),
            }
            for a in attachments
        ]
    try:
        response = http.post(
            f"{GRAPH}/me/sendMail",
            json={"message": message, "saveToSentItems": True},
            headers={"Authorization": f"Bearer {token}"},
        )
    except httpx.HTTPError as exc:
        raise MailboxError("Microsoft ne répond pas : l'e-mail n'est pas parti.") from exc
    if response.status_code != 202:
        logger.warning("Envoi Outlook refusé (code %s)", response.status_code)
        raise MailboxError("Microsoft a refusé l'envoi : l'e-mail n'est pas parti.")
    link.last_used_at = timezone.now()
    link.save(update_fields=["last_used_at"])


# --- Lecture de la boîte (D-060) -------------------------------------------------------------


class Session:
    """Un jeton d'accès pour une série d'appels (une lecture de la boîte)."""

    def __init__(self, link: MailboxLink, http: httpx.Client | None = None) -> None:
        self.link = link
        self.http = http or _http()
        self.token = _access_token(link, self.http)

    def get(
        self, url: str, params: dict[str, str] | None = None, *, text_body: bool = False
    ) -> Any:
        headers = {"Authorization": f"Bearer {self.token}"}
        if text_body:
            # Le corps en texte simple : rien à interpréter, aucun contenu actif.
            headers["Prefer"] = 'outlook.body-content-type="text"'
        target = url if url.startswith("https://") else f"{GRAPH}{url}"
        if not target.startswith(GRAPH):
            raise MailboxError("Adresse Microsoft inattendue.")
        try:
            response = self.http.get(target, params=params, headers=headers)
        except httpx.HTTPError as exc:
            raise MailboxError("Microsoft ne répond pas : la boîte sera relue plus tard.") from exc
        if response.status_code != 200:
            logger.warning("Lecture Outlook refusée (code %s)", response.status_code)
            raise MailboxError("Microsoft a refusé la lecture de la boîte.")
        return response.json()

    def reply(self, message_id: str, comment_html: str) -> None:
        try:
            response = self.http.post(
                f"{GRAPH}/me/messages/{message_id}/reply",
                json={"comment": comment_html},
                headers={"Authorization": f"Bearer {self.token}"},
            )
        except httpx.HTTPError as exc:
            raise MailboxError("Microsoft ne répond pas : la réponse n'est pas partie.") from exc
        if response.status_code != 202:
            logger.warning("Réponse Outlook refusée (code %s)", response.status_code)
            raise MailboxError("Microsoft a refusé l'envoi : la réponse n'est pas partie.")
        self.link.last_used_at = timezone.now()
        self.link.save(update_fields=["last_used_at"])
