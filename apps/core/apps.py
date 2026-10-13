from django.apps import AppConfig


class CoreConfig(AppConfig):
    name = "apps.core"
    label = "core"
    verbose_name = "Cabinet"

    def ready(self) -> None:
        from . import signals  # noqa: F401  (branche les signaux de connexion)
