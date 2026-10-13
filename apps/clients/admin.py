from django.contrib import admin
from django.db.models import QuerySet
from django.http import HttpRequest
from simple_history.admin import SimpleHistoryAdmin

from .models import Assignment, Client, ContactPoint, Relation


class ContactInline(admin.TabularInline):  # type: ignore[type-arg]
    model = ContactPoint
    extra = 0


class AssignmentInline(admin.TabularInline):  # type: ignore[type-arg]
    model = Assignment
    extra = 0


@admin.register(Client)
class ClientAdmin(SimpleHistoryAdmin):
    list_display = ("name", "first_name", "kind", "status", "portfolio", "enterprise_number")
    list_filter = ("status", "kind", "portfolio")
    search_fields = ("name", "first_name", "enterprise_number", "reference")
    exclude = ("national_number",)
    inlines = (ContactInline, AssignmentInline)

    def get_queryset(self, request: HttpRequest) -> QuerySet[Client]:
        # Les droits par portefeuille s'appliquent aussi dans l'administration.
        return Client.objects.visible_to(request.user)


@admin.register(Relation)
class RelationAdmin(SimpleHistoryAdmin):
    list_display = ("entity", "role", "person", "share_percentage", "start_date", "end_date")
    list_filter = ("role",)
    raw_id_fields = ("entity", "person")
