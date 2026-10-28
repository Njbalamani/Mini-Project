from django.urls import path

from . import views

app_name = "documents"

urlpatterns = [
    path("", views.document_list, name="list"),
    path("upload/", views.document_upload, name="upload"),
    path("<int:pk>/", views.document_detail, name="detail"),
    path("<int:pk>/reprocess/", views.document_reprocess, name="reprocess"),
    path("<int:pk>/analyze/", views.document_analyze, name="analyze"),
    path("<int:pk>/ask/", views.document_ask, name="ask"),
    path("<int:pk>/delete/", views.document_delete, name="delete"),
    path("analysis/<int:pk>/delete/", views.analysis_delete, name="analysis_delete"),
]
