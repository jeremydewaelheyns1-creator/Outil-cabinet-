from django.apps import AppConfig


class ClientsConfig(AppConfig):
    name = "apps.clients"
    label = "clients"
    verbose_name = "Clients"

    def ready(self) -> None:
        from . import prospects  # noqa: F401  (prospect → client à la signature, D-077)
