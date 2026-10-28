from django.urls import path

from . import views

app_name = "tasks"

urlpatterns = [
    path("", views.task_list, name="list"),
    path("create/", views.task_create, name="create"),
    path("bulk/", views.task_bulk_action, name="bulk_action"),
    path("saved-filters/save/", views.task_saved_filter_save, name="saved_filter_save"),
    path("saved-filters/<int:pk>/delete/", views.task_saved_filter_delete, name="saved_filter_delete"),
    path("tags/", views.tag_list, name="tags"),
    path("tags/<int:pk>/edit/", views.tag_edit, name="tag_edit"),
    path("tags/<int:pk>/delete/", views.tag_delete, name="tag_delete"),
    path("export.csv", views.task_export_csv, name="export_csv"),
    path("<int:pk>/", views.task_detail, name="detail"),
    path("<int:pk>/edit/", views.task_edit, name="edit"),
    path("<int:pk>/status/", views.task_set_status, name="set_status"),
    path("<int:pk>/delete/", views.task_delete, name="delete"),
    path("<int:pk>/activity/", views.task_activity, name="activity"),
    path("<int:pk>/comments/add/", views.task_comment_add, name="comment_add"),
    path("<int:pk>/comments/<int:comment_pk>/delete/", views.task_comment_delete, name="comment_delete"),
]
