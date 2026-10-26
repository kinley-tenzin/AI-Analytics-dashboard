from django.urls import path, re_path

from . import views

app_name = "portal"
urlpatterns = [
    # Hashed build files (JS, CSS, fonts): cacheable forever, a new build gets new names.
    path("app/assets/<path:path>", views.asset, name="asset"),
    # Other files at the build root (favicon.svg). Client-side routes never contain a dot.
    re_path(r"^app/(?P<path>[\w-]+\.[A-Za-z0-9]+)$", views.root_file, name="root-file"),
    # Every other /app/... path is a client-side route of the React app: answer with index.html.
    re_path(r"^app(?:/.*)?$", views.index, name="index"),
]
