from django.urls import path

from apps.vat import views as vat_views

from . import extension_views, views

app_name = "tasks"

urlpatterns = [
    path("", views.board, name="board"),
    path("<int:pk>/statut/", views.set_status, name="status"),
    path("<int:pk>/etapes/<int:step_pk>/", views.toggle_step, name="step"),
    path("<int:pk>/responsable/", views.set_assignee, name="assignee"),
    path("dossier/<int:pk>/ajouter/", views.add_manual_task, name="add"),
    path("tva/", vat_views.my_vat, name="vat_board"),
    path("delais-spf/", extension_views.extensions_page, name="extensions"),
    path("delais-spf/<int:pk>/vu/", extension_views.extension_seen, name="extension_seen"),
]
