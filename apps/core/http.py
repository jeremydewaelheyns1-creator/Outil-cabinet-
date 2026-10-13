"""Type de requête utilisé dans les vues : utilisateur connecté et détails HTMX.

Toutes les vues passent derrière LoginRequiredMiddleware et RequireMFAMiddleware : l'utilisateur
y est donc toujours connecté (sauf vues marquées `login_not_required`).
"""

from django.http import HttpRequest
from django_htmx.middleware import HtmxDetails

from .models import User


class AppRequest(HttpRequest):
    htmx: HtmxDetails
    user: User
