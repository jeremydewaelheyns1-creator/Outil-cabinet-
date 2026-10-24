from django.urls import path

from . import compliance_views

app_name = "conformite"

urlpatterns = [
    path("", compliance_views.board, name="board"),
    path("demander/", compliance_views.ask, name="ask"),
    path("sans-reponse/", compliance_views.unanswered, name="unanswered"),
]
