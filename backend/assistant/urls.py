from django.urls import path
from django.views.generic import RedirectView

from . import views

app_name = "assistant"
urlpatterns = [
    # Decision 3 (Milestone 10): the assistant lives in the website's Ask AI page now; the old
    # server-rendered page redirects there. The JSON API below is what the website calls.
    path("", RedirectView.as_view(url="/app/", permanent=False), name="home"),
    path("assistant/", RedirectView.as_view(url="/app/ask", permanent=False), name="assistant"),
    path("api/v1/ask/", views.ask, name="ask"),
]
