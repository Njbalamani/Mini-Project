from django.urls import path

from . import views

app_name = "subscriptions"

urlpatterns = [
    path("", views.subscription_home, name="home"),
    path("plan/<slug:slug>/switch/", views.switch_plan, name="switch"),
]
