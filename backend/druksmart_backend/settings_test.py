"""Settings for the automated tests (pytest-django).

Django's own tables (users, scopes, question log) use an in-memory SQLite database, because the
`app` PostgreSQL role is deliberately not allowed to create databases. The KPI service still
reads the REAL PostgreSQL warehouse as the KPI reader (tests marked `backend`).
"""

import os

os.environ.setdefault("DJANGO_SECRET_KEY", "test-only-secret-key-not-used-anywhere-else")

from .settings import *  # noqa: E402,F403
from .settings import DRUKSMART_AI  # noqa: E402

DATABASES = {"default": {"ENGINE": "django.db.backends.sqlite3", "NAME": ":memory:"}}
PASSWORD_HASHERS = ["django.contrib.auth.hashers.MD5PasswordHasher"]  # fast, tests only
DRUKSMART_AI = {**DRUKSMART_AI, "PROVIDER": "rules", "GEMINI_API_KEY": "", "LLM_PHRASING": False}
DEBUG = False
ALLOWED_HOSTS = ["testserver", "127.0.0.1", "localhost"]
