from django.urls import path

from . import views

app_name = "integrations"

urlpatterns = [
    path("", views.integration_center, name="center"),
    path("step-up/", views.step_up, name="step_up"),
    path("whatsapp/connect/", views.whatsapp_connect, name="whatsapp_connect"),
    path("whatsapp/qr/status/", views.whatsapp_qr_status, name="whatsapp_qr_status"),
    path("whatsapp/pair/", views.whatsapp_pair, name="whatsapp_pair"),
    path("whatsapp/panel/", views.whatsapp_panel, name="whatsapp_panel"),
    path("whatsapp/send/", views.whatsapp_send, name="whatsapp_send"),
    path("whatsapp/webhook/", views.whatsapp_webhook, name="whatsapp_webhook"),
    path("call/", views.call_room, name="call_room"),
    path("credentials/", views.provider_credentials, name="provider_credentials"),
    path("<str:provider>/connect/", views.connect, name="connect"),
    path("<str:provider>/callback/", views.callback, name="callback"),
    path("<str:provider>/sync/", views.sync, name="sync"),
    path("<str:provider>/disconnect/", views.disconnect, name="disconnect"),
    path("<str:provider>/", views.integration_detail, name="detail"),
]
