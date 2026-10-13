"""Administration (paramétrage) : utilisateurs, profils, portefeuilles, journaux en lecture."""

from typing import Any

from django.contrib import admin
from django.contrib.auth.admin import UserAdmin as BaseUserAdmin
from django.http import HttpRequest
from simple_history.admin import SimpleHistoryAdmin

from .models import AccessLog, Event, EventHandling, Portfolio, SecurityProfile, User


@admin.register(User)
class UserAdmin(BaseUserAdmin):  # type: ignore[type-arg]
    ordering = ("last_name", "first_name", "email")
    list_display = ("email", "first_name", "last_name", "initials", "profile", "is_active")
    list_filter = ("is_active", "is_staff", "is_superuser", "profile")
    search_fields = ("email", "first_name", "last_name", "initials")
    fieldsets = (
        (None, {"fields": ("email", "password")}),
        ("Identité", {"fields": ("first_name", "last_name", "initials")}),
        ("Droits", {"fields": ("profile", "is_active", "is_staff", "is_superuser")}),
        ("Dates", {"fields": ("last_login", "date_joined")}),
    )
    add_fieldsets = (
        (
            None,
            {
                "classes": ("wide",),
                "fields": (
                    "email",
                    "first_name",
                    "last_name",
                    "initials",
                    "profile",
                    "password1",
                    "password2",
                ),
            },
        ),
    )
    readonly_fields = ("last_login", "date_joined")
    filter_horizontal = ()


@admin.register(SecurityProfile)
class SecurityProfileAdmin(SimpleHistoryAdmin):
    list_display = ("name", "description")


@admin.register(Portfolio)
class PortfolioAdmin(SimpleHistoryAdmin):
    list_display = ("name", "is_private", "order")
    filter_horizontal = ("members",)


class ReadOnlyAdmin(admin.ModelAdmin):  # type: ignore[type-arg]
    def has_add_permission(self, request: HttpRequest) -> bool:
        return False

    def has_change_permission(self, request: HttpRequest, obj: Any = None) -> bool:
        return False

    def has_delete_permission(self, request: HttpRequest, obj: Any = None) -> bool:
        return False


@admin.register(AccessLog)
class AccessLogAdmin(ReadOnlyAdmin):
    list_display = ("at", "user_email", "action", "object_type", "object_repr", "ip_address")
    list_filter = ("action", "object_type")
    search_fields = ("user_email", "object_repr")
    date_hierarchy = "at"


class EventHandlingInline(admin.TabularInline):  # type: ignore[type-arg]
    model = EventHandling
    extra = 0
    readonly_fields = ("handler", "status", "attempts", "last_error", "finished_at")
    can_delete = False

    def has_add_permission(self, request: HttpRequest, obj: Any = None) -> bool:
        return False


@admin.register(Event)
class EventAdmin(ReadOnlyAdmin):
    list_display = ("occurred_at", "type", "subject_type", "subject_id", "status")
    list_filter = ("status", "type")
    inlines = (EventHandlingInline,)
    actions = ("reprocess",)

    @admin.action(description="Relancer les traitements en échec")
    def reprocess(self, request: HttpRequest, queryset: Any) -> None:
        from . import events

        for event in queryset:
            event.handlings.filter(status=EventHandling.Status.FAILED).update(attempts=0)
            events.process(event.pk)
        self.message_user(request, f"{queryset.count()} événement(s) relancé(s).")
