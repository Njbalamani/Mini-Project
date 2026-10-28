from django.urls import path

from . import views

app_name = "audit_logs"

urlpatterns = [
    path("", views.audit_list, name="list"),
]
