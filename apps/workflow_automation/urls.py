from django.urls import path

from . import views

app_name = "workflow_automation"

urlpatterns = [
    path("", views.workflow_list, name="list"),
    path("create/", views.workflow_create, name="create"),
    path("hooks/<str:token>/", views.webhook_receive, name="webhook"),
    path("executions/", views.execution_list, name="executions"),
    path("executions/<int:pk>/", views.execution_detail, name="execution"),
    path("<int:pk>/", views.workflow_detail, name="detail"),
    path("<int:pk>/edit/", views.workflow_edit, name="edit"),
    path("<int:pk>/toggle/", views.workflow_toggle, name="toggle"),
    path("<int:pk>/run/", views.workflow_run, name="run"),
    path("<int:pk>/preview/", views.workflow_preview, name="preview"),
    path("<int:pk>/webhook/regenerate/", views.webhook_regenerate, name="webhook_regenerate"),
    path("<int:pk>/delete/", views.workflow_delete, name="delete"),
]
