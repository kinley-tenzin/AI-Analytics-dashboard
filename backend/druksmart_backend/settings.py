"""Django settings for the DrukSmart backend (KPI service + bounded AI assistant).

Every secret and environment-specific value comes from environment variables, which local
development loads from the git-ignored `.env` at the repository root (see .env.example).
Application metadata (users, scopes, question log) lives in DRUKSMART_APP_DB as the `app` role;
the warehouse is read separately by the KPI service as DRUKSMART_KPI_READER_USER (kpi/warehouse.py).
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

from dotenv import load_dotenv

BACKEND_DIR = Path(__file__).resolve().parent.parent
REPO_ROOT = BACKEND_DIR.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))  # druksmart_common

load_dotenv(REPO_ROOT / ".env", override=False)


def env(name: str, default: str = "") -> str:
    return os.environ.get(name, default).strip()


def env_bool(name: str, default: bool = False) -> bool:
    return env(name, str(default)).lower() in ("1", "true", "yes", "on")


SECRET_KEY = env("DJANGO_SECRET_KEY")
if not SECRET_KEY or SECRET_KEY == "CHANGE_ME":
    raise RuntimeError(
        "DJANGO_SECRET_KEY is not set: run infrastructure/scripts/create_local_env.py --add-missing"
    )
DEBUG = env_bool("DJANGO_DEBUG", False)
ALLOWED_HOSTS = [h.strip() for h in env("DJANGO_ALLOWED_HOSTS", "127.0.0.1,localhost").split(",")]

INSTALLED_APPS = [
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
    "django.contrib.admin",
    "access",
    "kpi",
    "assistant",
    "health",
    "portal",
]

MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
    # JSON errors for /api/ even when the database is down (Milestone 8, D10).
    "kpi.middleware.ApiErrorMiddleware",
]

ROOT_URLCONF = "druksmart_backend.urls"
WSGI_APPLICATION = "druksmart_backend.wsgi.application"

TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "DIRS": [],
        "APP_DIRS": True,
        "OPTIONS": {
            "context_processors": [
                "django.template.context_processors.request",
                "django.contrib.auth.context_processors.auth",
                "django.contrib.messages.context_processors.messages",
            ],
        },
    },
]

# Application metadata database (NOT the warehouse).
DATABASES = {
    "default": {
        "ENGINE": "django.db.backends.postgresql",
        "HOST": env("DRUKSMART_PG_HOST", "127.0.0.1"),
        "PORT": env("DRUKSMART_PG_PORT", "5433"),
        "NAME": env("DRUKSMART_APP_DB", "druksmart_app"),
        "USER": env("DRUKSMART_APP_USER"),
        "PASSWORD": env("DRUKSMART_APP_PASSWORD"),
        "CONN_MAX_AGE": 60,
        "OPTIONS": {"connect_timeout": 5},
    }
}

AUTH_PASSWORD_VALIDATORS = [
    {"NAME": "django.contrib.auth.password_validation.UserAttributeSimilarityValidator"},
    {"NAME": "django.contrib.auth.password_validation.MinimumLengthValidator"},
    {"NAME": "django.contrib.auth.password_validation.CommonPasswordValidator"},
    {"NAME": "django.contrib.auth.password_validation.NumericPasswordValidator"},
]
# Sign-in throttling (access/throttle.py) wraps Django's username/password backend.
AUTHENTICATION_BACKENDS = ["access.throttle.ThrottledModelBackend"]
LOGIN_URL = "login"
# The website signs in through /api/v1/auth/; Django's own sign-in page (kept for the evaluation
# tools and Django-rendered pages) also leads into the website.
LOGIN_REDIRECT_URL = "/app/"
LOGOUT_REDIRECT_URL = "/app/login"

LANGUAGE_CODE = "en"
TIME_ZONE = "Asia/Thimphu"
USE_I18N = False
USE_TZ = True

STATIC_URL = "static/"

# The built React web application (frontend/, Milestone 10), served by `portal` under /app/.
# The backend image builds it into its own directory; local development uses frontend/dist.
DRUKSMART_FRONTEND_DIST = Path(env("DRUKSMART_FRONTEND_DIST", str(REPO_ROOT / "frontend" / "dist")))

# Embedded Superset dashboards (Milestone 10, portal/superset.py, docs/web/EMBEDDING.md).
# INTERNAL_URL: how the backend reaches Superset (Compose network in the container);
# PUBLIC_URL: what the browser loads the embedded dashboard from. The service account only
# issues guest tokens; its password stays in the backend's environment.
DRUKSMART_SUPERSET = {
    "INTERNAL_URL": env("DRUKSMART_SUPERSET_INTERNAL_URL", "http://127.0.0.1:8088"),
    "PUBLIC_URL": env("DRUKSMART_SUPERSET_PUBLIC_URL", "http://127.0.0.1:8088").rstrip("/"),
    "SERVICE_USER": env("SUPERSET_PORTAL_SERVICE_USER", "druksmart_portal_service"),
    "SERVICE_PASSWORD": env("SUPERSET_PORTAL_SERVICE_PASSWORD"),
    "WEB_ORIGIN": env("DRUKSMART_WEB_ORIGIN", "http://127.0.0.1:8000").rstrip("/"),
    "ACCESS_FILE": REPO_ROOT / "superset" / "definitions" / "access.yml",
    "GUEST_TOKEN_SECONDS": 300,
}
DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"

# Local development over http://127.0.0.1 (no TLS). A deployment behind HTTPS sets these to True.
SESSION_COOKIE_SECURE = env_bool("DJANGO_SECURE_COOKIES", False)
CSRF_COOKIE_SECURE = SESSION_COOKIE_SECURE
SESSION_COOKIE_HTTPONLY = True
SESSION_COOKIE_AGE = 8 * 3600
X_FRAME_OPTIONS = "DENY"

# --- DrukSmart AI assistant -------------------------------------------------------------------
DRUKSMART_AI = {
    # "rules" = deterministic parser (no LLM); "gemini" = Google Gemini function calling.
    "PROVIDER": env("DRUKSMART_AI_PROVIDER", "rules").lower(),
    "GEMINI_API_KEY": env("GEMINI_API_KEY"),
    "GEMINI_MODEL": env("GEMINI_MODEL", "gemini-2.5-flash"),
    "GEMINI_TIMEOUT_SECONDS": float(env("GEMINI_TIMEOUT_SECONDS", "20")),
    # Let the LLM phrase the answer (numbers are verified against the result afterwards).
    "LLM_PHRASING": env_bool("DRUKSMART_AI_LLM_PHRASING", True),
    "MAX_QUESTION_LENGTH": 500,
}

LOGGING = {
    "version": 1,
    "disable_existing_loggers": False,
    "handlers": {"console": {"class": "logging.StreamHandler"}},
    "loggers": {"druksmart": {"handlers": ["console"], "level": env("DJANGO_LOG_LEVEL", "INFO")}},
}
