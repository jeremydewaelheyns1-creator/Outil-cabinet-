from django.apps import AppConfig


class BceConfig(AppConfig):
    name = "apps.bce"
    label = "bce"
    verbose_name = "Banque-Carrefour des Entreprises"

    def ready(self) -> None:
        from . import handlers  # noqa: F401  (abonne l'enrichissement aux événements clients)
