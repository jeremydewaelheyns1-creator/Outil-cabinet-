from django.contrib import admin

from .models import ImportBatch


@admin.register(ImportBatch)
class ImportBatchAdmin(admin.ModelAdmin[ImportBatch]):
    list_display = ("created_at", "file_name", "status", "uploaded_by")
    list_filter = ("status",)
    readonly_fields = ("analysis", "result")
