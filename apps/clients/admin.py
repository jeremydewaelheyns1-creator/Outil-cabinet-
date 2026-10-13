"""Administration des fiches clients (dépannage). L'historique s'affiche dans l'application,
où le numéro national est masqué : l'historique de l'administration n'est pas activé ici."""

from django.contrib import admin
from django.db.models import QuerySet
from django.http import HttpRequest

from .models import Assignment, Client, ContactPoint, Relation


class ContactInline(admin.TabularInline[ContactPoint, Client]):
    model = ContactPoint
    extra = 0


class AssignmentInline(admin.TabularInline[Assignment, Client]):
    model = Assignment
    extra = 0


@admin.register(Client)
class ClientAdmin(admin.ModelAdmin[Client]):
    list_display = ("name", "first_name", "kind", "status", "portfolio", "enterprise_number")
    list_filter = ("status", "kind", "portfolio")
    search_fields = ("name", "first_name", "enterprise_number", "reference")
    exclude = ("national_number",)
    inlines = (ContactInline, AssignmentInline)

    def get_queryset(self, request: HttpRequest) -> QuerySet[Client]:
        # Les droits par portefeuille s'appliquent aussi dans l'administration.
        return Client.objects.visible_to(request.user)


@admin.register(Relation)
class RelationAdmin(admin.ModelAdmin[Relation]):
    list_display = ("entity", "role", "person", "share_percentage", "start_date", "end_date")
    list_filter = ("role",)
    raw_id_fields = ("entity", "person")

    def get_queryset(self, request: HttpRequest) -> QuerySet[Relation]:
        visible = Client.objects.visible_to(request.user)
        return Relation.objects.filter(entity__in=visible, person__in=visible)
