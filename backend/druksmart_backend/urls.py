from django.contrib import admin
from django.contrib.auth import views as auth_views
from django.contrib.staticfiles.views import serve as serve_static
from django.urls import include, path, re_path

urlpatterns = [
    path("", include("assistant.urls")),
    path("api/v1/auth/", include("access.urls")),
    path("api/v1/portal/", include("portal.api_urls")),
    path("api/v1/", include("kpi.urls")),
    path("health/", include("health.urls")),
    path("", include("portal.urls")),
    path("accounts/login/", auth_views.LoginView.as_view(), name="login"),
    path("accounts/logout/", auth_views.LogoutView.as_view(), name="logout"),
    path("admin/", admin.site.urls),
    # Prototype: the app's own CSS/JS served by Django even with DEBUG off. A deployment serves
    # `collectstatic` output from a web server or whitenoise instead (deployment milestone).
    re_path(r"^static/(?P<path>.*)$", serve_static, {"insecure": True}),
]
