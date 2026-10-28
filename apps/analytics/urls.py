from django.urls import path

from . import views

app_name = "analytics"

urlpatterns = [
    path("", views.analytics_home, name="home"),
    path("data/", views.analytics_data, name="data"),
]
