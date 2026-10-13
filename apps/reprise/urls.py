from django.urls import path

from . import views

app_name = "reprise"

urlpatterns = [
    path("", views.index, name="index"),
    path("<int:pk>/", views.detail, name="detail"),
    path("<int:pk>/importer/", views.apply, name="apply"),
    path("<int:pk>/abandonner/", views.discard, name="discard"),
]
