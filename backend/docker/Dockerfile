# DrukSmart Django backend (KPI service + AI assistant + web application) for the deployment.
# Python source code is NOT baked in: the repository is mounted read-only at /opt/druksmart, like
# the Airflow image. Python packages are installed OFFLINE from pre-downloaded Linux wheels.

# Stage 1 (Milestone 10): build the React web application (frontend/) with a pinned Node image.
# `npm ci` installs exactly package-lock.json; the result is static files only (no Node at run time).
FROM node:24.14.0-bookworm-slim AS frontend
WORKDIR /build
COPY frontend/package.json frontend/package-lock.json frontend/.npmrc ./
RUN npm ci
COPY frontend/ ./
RUN npm run build

# Stage 2: the Django backend, serving the built web application under /app/.
FROM python:3.12.15-slim-bookworm

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    DJANGO_SETTINGS_MODULE=druksmart_backend.settings

RUN useradd --create-home --uid 10001 druksmart

COPY backend/docker/requirements-backend.txt /tmp/requirements-backend.txt
COPY orchestration/docker/wheels/ /tmp/wheels/
COPY backend/docker/wheels/ /tmp/wheels/
RUN pip install --no-cache-dir --no-index --find-links /tmp/wheels -r /tmp/requirements-backend.txt \
    && rm -rf /tmp/wheels \
    && python -c "import django, gunicorn, psycopg; print('django', django.get_version())"

COPY --from=frontend /build/dist /opt/druksmart-frontend
ENV DRUKSMART_FRONTEND_DIST=/opt/druksmart-frontend

COPY backend/docker/entrypoint.sh /usr/local/bin/druksmart-backend
USER druksmart
WORKDIR /opt/druksmart/backend
EXPOSE 8000
HEALTHCHECK --interval=30s --timeout=10s --start-period=40s --retries=5 \
  CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/health/', timeout=5)"
ENTRYPOINT ["bash", "/usr/local/bin/druksmart-backend"]
