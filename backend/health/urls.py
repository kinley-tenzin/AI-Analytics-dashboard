from django.urls import path

from . import views

app_name = "health"
urlpatterns = [
    path("", views.live, name="live"),
    path("ready/", views.ready, name="ready"),
]
