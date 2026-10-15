from django.apps import AppConfig


class DocumentsConfig(AppConfig):
    name = "apps.documents"
    label = "documents"
    verbose_name = "Documents"

    def ready(self) -> None:
        from . import identity  # noqa: F401  (lecture des cartes d'identité reçues)
