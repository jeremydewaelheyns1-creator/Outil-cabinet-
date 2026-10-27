from django.apps import AppConfig


class VatConfig(AppConfig):
    name = "apps.vat"
    label = "vat"
    verbose_name = "Déclarations TVA"

    def ready(self) -> None:
        from . import handlers  # noqa: F401  (enregistre les automatismes)
