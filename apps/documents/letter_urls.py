from django.urls import path

from . import letter_views

app_name = "lettre"

urlpatterns = [
    path("", letter_views.models_page, name="models"),
    path("<int:template_id>/", letter_views.model_page, name="model"),
    path("<int:template_id>/word/", letter_views.model_download, name="download"),
]
