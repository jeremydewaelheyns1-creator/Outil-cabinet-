from django.contrib import admin
from django.db.models import QuerySet
from django.http import HttpRequest

from apps.clients.models import Client

from .models import GenerationRun, Task, TaskStep


class StepInline(admin.TabularInline[TaskStep, Task]):
    model = TaskStep
    extra = 0


@admin.register(Task)
class TaskAdmin(admin.ModelAdmin[Task]):
    list_display = ("due_date", "title", "client", "status", "assignee", "kind")
    list_filter = ("status", "category", "kind")
    raw_id_fields = ("client",)
    inlines = (StepInline,)

    def get_queryset(self, request: HttpRequest) -> QuerySet[Task]:
        return Task.objects.filter(client__in=Client.objects.visible_to(request.user))


@admin.register(GenerationRun)
class GenerationRunAdmin(admin.ModelAdmin[GenerationRun]):
    list_display = ("started_at", "clients", "created", "removed", "finished_at")
