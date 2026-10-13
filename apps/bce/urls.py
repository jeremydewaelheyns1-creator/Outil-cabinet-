from django.urls import path

from . import views

app_name = "bce"

urlpatterns = [
    path("recherche/", views.search, name="search"),
    path("imports/", views.imports, name="imports"),
]
