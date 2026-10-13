from django.contrib import admin
from django.http import HttpRequest

from .models import ImportRun


@admin.register(ImportRun)
class ImportRunAdmin(admin.ModelAdmin[ImportRun]):
    list_display = ("started_at", "kind", "extract_number", "snapshot_date", "status")
    list_filter = ("kind", "status")
    readonly_fields = tuple(f.name for f in ImportRun._meta.fields)

    def has_add_permission(self, request: HttpRequest) -> bool:
        return False

    def has_change_permission(self, request: HttpRequest, obj: object = None) -> bool:
        return False
