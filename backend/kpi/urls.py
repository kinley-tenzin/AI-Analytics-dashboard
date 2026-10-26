from django.urls import path

from . import views

app_name = "kpi"
urlpatterns = [
    path("me/", views.me, name="me"),
    path("kpis/", views.list_kpis, name="list"),
    path("kpis/run/", views.run_kpi, name="run"),
]
