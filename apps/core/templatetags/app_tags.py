"""Petites aides de gabarits."""

from django import template
from django.http import HttpRequest
from django.utils.safestring import SafeString, mark_safe

from apps.core.models import User

register = template.Library()


@register.simple_tag
def nav_current(request: HttpRequest, target: str) -> SafeString:
    """Marque le lien de navigation de la section affichée (« clients » ou « core:home »)."""
    match = request.resolver_match
    if match is None:
        return mark_safe("")
    current = match.view_name if ":" in target else match.app_name
    return mark_safe('aria-current="page"' if current == target else "")  # noqa: S308


@register.filter
def can(user: object, capability: str) -> bool:
    return isinstance(user, User) and user.has_capability(capability)


@register.filter
def event_label(event_type: str) -> str:
    from apps.core.event_labels import event_label as label

    return label(event_type)
