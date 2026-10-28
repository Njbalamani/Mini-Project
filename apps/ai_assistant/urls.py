from django.urls import path

from . import views

app_name = "ai_assistant"

urlpatterns = [
    path("", views.assistant_home, name="home"),
    path("new/", views.new_conversation, name="new_conversation"),
    path("search/", views.conversation_search, name="search"),
    path("search/quick/", views.quick_search, name="quick_search"),
    path("settings/", views.ai_settings, name="settings"),
    path("insights/", views.assistant_insights, name="insights"),
    path("autocomplete/", views.autocomplete, name="autocomplete"),
    path("action/execute/", views.execute_action, name="execute_action"),
    path("c/<int:pk>/", views.conversation_detail, name="conversation"),
    path("c/<int:pk>/send/", views.send_message, name="send_message"),
    path("c/<int:pk>/delete/", views.delete_conversation, name="delete_conversation"),
    path("c/<int:pk>/export/", views.export_conversation, name="export"),
    path("m/<int:pk>/feedback/", views.message_feedback, name="message_feedback"),
    path("m/<int:pk>/correction/", views.message_correction, name="message_correction"),
]
