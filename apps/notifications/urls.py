from django.urls import path

from . import views

app_name = "notifications"

urlpatterns = [
    path("", views.notification_list, name="list"),
    path("digest/", views.digest_preview, name="digest"),
    path("digest/send/", views.digest_send, name="digest_send"),
    path("<int:pk>/read/", views.mark_read, name="mark_read"),
    path("mark-all-read/", views.mark_all_read, name="mark_all_read"),
]
