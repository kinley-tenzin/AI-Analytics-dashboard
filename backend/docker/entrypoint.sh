#!/usr/bin/env bash
# Start the Django backend: apply migrations (idempotent), make sure the role groups exist, then
# serve with gunicorn. Demo users are NOT created here (run `manage.py seed_demo_users` on purpose).
set -euo pipefail
cd /opt/druksmart/backend
python manage.py migrate --noinput
python manage.py seed_roles
exec gunicorn druksmart_backend.wsgi:application \
  --bind 0.0.0.0:8000 --workers "${BACKEND_WORKERS:-2}" --timeout 60 \
  --access-logfile - --error-logfile -
