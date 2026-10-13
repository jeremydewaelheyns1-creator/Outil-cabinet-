from django.apps import AppConfig


class TasksConfig(AppConfig):
    name = "apps.tasks"
    label = "tasks"
    verbose_name = "Échéances"

    def ready(self) -> None:
        from . import handlers  # noqa: F401  (génération des échéances sur événements clients)
