from django.apps import AppConfig


class ClosingConfig(AppConfig):
    name = "apps.closing"
    label = "closing"
    verbose_name = "Clôture"

    def ready(self) -> None:
        from . import deposits  # noqa: F401  (enregistre les automatismes)
