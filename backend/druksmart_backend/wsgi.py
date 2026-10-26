"""WSGI entry point (a production server such as waitress/gunicorn imports `application`)."""

import os

from django.core.wsgi import get_wsgi_application

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "druksmart_backend.settings")
application = get_wsgi_application()
