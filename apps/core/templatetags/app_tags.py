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


@register.filter
def external_url(value: str) -> str:
    """Adresse web cliquable sans risque : http(s) uniquement, « https:// » ajouté si absent."""
    value = (value or "").strip()
    if not value or any(c.isspace() for c in value):
        return ""
    if "://" not in value:
        value = f"https://{value}"
    scheme = value.split("://", 1)[0].lower()
    return value if scheme in ("http", "https") else ""


_ICONS = {
    # Personne physique (IPP)
    "person": (
        "Personne physique",
        '<circle cx="12" cy="8" r="4"/><path d="M4 21c0-4.4 3.6-7 8-7s8 2.6 8 7"/>',
    ),
    # Société
    "company": (
        "Société",
        '<rect x="4" y="3" width="11" height="18" rx="1"/><path d="M15 9h5v12h-5M8 7h3M8 11h3'
        'M8 15h3"/>',
    ),
    # ASBL, fondation
    "nonprofit": (
        "ASBL ou fondation",
        '<circle cx="8" cy="8" r="3"/><circle cx="16" cy="8" r="3"/>'
        '<path d="M2 20c0-3.3 2.7-5.5 6-5.5s6 2.2 6 5.5M12 20c0-3.3 2.2-5.5 5-5.5s5 2.2 5 5.5"/>',
    ),
}


@register.simple_tag
def client_icon(client: object) -> SafeString:
    """Petite icône distinguant d'un coup d'œil une société, une personne (IPP), une ASBL."""
    kind = getattr(client, "kind", "company")
    if kind not in _ICONS:
        kind = "company"
    title, paths = _ICONS[kind]
    return mark_safe(  # noqa: S308 (contenu fixe, défini ci-dessus)
        f'<svg class="kind-icon kind-{kind}" viewBox="0 0 24 24" width="16" height="16" '
        f'fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" '
        f'stroke-linejoin="round" role="img" aria-label="{title}">'
        f"<title>{title}</title>{paths}</svg>"
    )


@register.filter
def iso_date(value: object) -> str:
    """« 2026-10-13 » → « 13/10/2026 » (dates lues sur les sites officiels)."""
    text = str(value or "")[:10]
    if len(text) == 10 and text[4] == "-" and text[7] == "-":
        return f"{text[8:10]}/{text[5:7]}/{text[:4]}"
    return text


@register.filter
def get_item(mapping: object, key: str) -> object:
    """Valeur d'un dictionnaire dans un gabarit (compteurs du panneau du dossier)."""
    return mapping.get(key) if isinstance(mapping, dict) else None


@register.filter
def euros(value: object) -> str:
    """Decimal('6632.44') → « 6 632,44 € » (montants des déclarations)."""
    from decimal import Decimal, InvalidOperation

    try:
        amount = Decimal(str(value)).quantize(Decimal("0.01"))
    except (InvalidOperation, ValueError):
        return ""
    whole, _, cents = f"{abs(amount):,.2f}".partition(".")
    sign = "-" if amount < 0 else ""
    return f"{sign}{whole.replace(',', ' ')},{cents} €"
