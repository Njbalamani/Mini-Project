from django.urls import path

from . import views

app_name = "calendar_manager"

urlpatterns = [
    path("", views.calendar_view, name="calendar"),
    path("create/", views.event_create, name="create"),
    path("export.ics", views.calendar_export, name="export"),
    path("feed/<str:token>.ics", views.calendar_feed, name="feed"),
    path("feed/reset/", views.calendar_feed_reset, name="feed_reset"),
    path("free-slots/", views.free_slots, name="free_slots"),
    path("<int:pk>/", views.event_detail, name="detail"),
    path("<int:pk>/edit/", views.event_edit, name="edit"),
    path("<int:pk>/move/", views.event_move, name="event_move"),
    path("<int:pk>/delete/", views.event_delete, name="delete"),
]
