from django.urls import path

from . import views

app_name = "email_manager"

urlpatterns = [
    path("", views.email_home, name="home"),
    path("fetch/", views.fetch_metadata, name="fetch"),
    path("settings/", views.email_settings, name="settings"),
    path("rules/add/", views.add_rule, name="add_rule"),
    path("m/<int:pk>/", views.message_detail, name="detail"),
    path("m/<int:pk>/summarize/", views.summarize, name="summarize"),
    path("m/<int:pk>/draft/", views.draft_reply, name="draft_reply"),
    path("d/<int:pk>/", views.draft_detail, name="draft"),
    path("d/<int:pk>/approve/", views.approve_send, name="approve_send"),
]
