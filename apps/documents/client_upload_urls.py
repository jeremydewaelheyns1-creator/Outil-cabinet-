from django.urls import path

from . import client_upload

app_name = "depot_client"

urlpatterns = [
    path("<str:token>/", client_upload.page, name="page"),
    path("<str:token>/page-<int:number>.png", client_upload.sign_page_image, name="page_image"),
]
