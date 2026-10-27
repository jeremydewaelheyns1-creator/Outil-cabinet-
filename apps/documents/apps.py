from django.apps import AppConfig


class DocumentsConfig(AppConfig):
    name = "apps.documents"
    label = "documents"
    verbose_name = "Documents"

    def ready(self) -> None:
        from . import (  # noqa: F401  (traitements sur événements)
            freshness,  # « modifié depuis » recalculé après un changement de fiche (D-080)
            identity,  # lecture des cartes d'identité reçues
        )
