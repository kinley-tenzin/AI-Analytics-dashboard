from django.urls import path

from . import auth_api

app_name = "auth"
urlpatterns = [
    path("session/", auth_api.session, name="session"),
    path("login/", auth_api.sign_in, name="login"),
    path("logout/", auth_api.sign_out, name="logout"),
]
