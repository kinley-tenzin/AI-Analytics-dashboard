#!/usr/bin/env bash
# Initialise DrukSmart databases, least-privilege roles and analytical schemas.
#
# The official postgres image runs this automatically the FIRST time the
# container starts with an empty data volume. It is idempotent, so it can also
# be re-run manually (e.g. after changing passwords in .env):
#   docker compose exec postgres bash /docker-entrypoint-initdb.d/01_init_databases_roles_schemas.sh
#
# All names and passwords come from environment variables (see .env.example);
# nothing secret is stored in this file.
set -euo pipefail

: "${POSTGRES_USER:?}" "${DRUKSMART_ANALYTICS_DB:?}" "${DRUKSMART_APP_DB:?}"
: "${DRUKSMART_PIPELINE_USER:?}" "${DRUKSMART_PIPELINE_PASSWORD:?}"
: "${DRUKSMART_BI_READER_USER:?}" "${DRUKSMART_BI_READER_PASSWORD:?}"
: "${DRUKSMART_APP_USER:?}" "${DRUKSMART_APP_PASSWORD:?}"
# Superset's own warehouse account (Milestone 6). Optional for older .env files.
DRUKSMART_SUPERSET_READER_USER="${DRUKSMART_SUPERSET_READER_USER:-druksmart_superset_reader}"
DRUKSMART_SUPERSET_READER_PASSWORD="${DRUKSMART_SUPERSET_READER_PASSWORD:-}"
# Django KPI service's warehouse account (Milestone 7). Optional for older .env files.
DRUKSMART_KPI_READER_USER="${DRUKSMART_KPI_READER_USER:-druksmart_kpi_reader}"
DRUKSMART_KPI_READER_PASSWORD="${DRUKSMART_KPI_READER_PASSWORD:-}"

# Connect over the container's local socket as the bootstrap superuser.
run_sql() {
  local dbname="$1"
  # Hide "already exists, skipping" notices on re-runs; warnings and errors still show.
  PGOPTIONS="-c client_min_messages=warning" psql -v ON_ERROR_STOP=1 --no-psqlrc --quiet \
    --username "$POSTGRES_USER" --dbname "$dbname" \
    -v analytics_db="$DRUKSMART_ANALYTICS_DB" \
    -v app_db="$DRUKSMART_APP_DB" \
    -v pipeline_user="$DRUKSMART_PIPELINE_USER" \
    -v pipeline_password="$DRUKSMART_PIPELINE_PASSWORD" \
    -v bi_user="$DRUKSMART_BI_READER_USER" \
    -v bi_password="$DRUKSMART_BI_READER_PASSWORD" \
    -v app_user="$DRUKSMART_APP_USER" \
    -v app_password="$DRUKSMART_APP_PASSWORD" \
    -v superset_user="$DRUKSMART_SUPERSET_READER_USER" \
    -v superset_password="$DRUKSMART_SUPERSET_READER_PASSWORD" \
    -v kpi_user="$DRUKSMART_KPI_READER_USER" \
    -v kpi_password="$DRUKSMART_KPI_READER_PASSWORD"
}

echo "[init] roles and application database"
run_sql postgres <<'SQL'
-- Login roles: create if missing, then (re)set the password from .env.
SELECT format('CREATE ROLE %I LOGIN', r)
FROM unnest(ARRAY[:'pipeline_user', :'bi_user', :'app_user']) AS r
WHERE NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = r)
\gexec
SELECT format('ALTER ROLE %I WITH LOGIN PASSWORD %L', :'pipeline_user', :'pipeline_password') \gexec
SELECT format('ALTER ROLE %I WITH LOGIN PASSWORD %L', :'bi_user', :'bi_password') \gexec
SELECT format('ALTER ROLE %I WITH LOGIN PASSWORD %L', :'app_user', :'app_password') \gexec

-- Application metadata lives in its own database, separate from ERP analytics.
SELECT format('CREATE DATABASE %I OWNER %I', :'app_db', :'app_user')
WHERE NOT EXISTS (SELECT 1 FROM pg_database WHERE datname = :'app_db')
\gexec

-- Isolated copy of the analytics database for automated warehouse tests (synthetic data only).
SELECT format('CREATE DATABASE %I', :'analytics_db' || '_test')
WHERE NOT EXISTS (SELECT 1 FROM pg_database WHERE datname = :'analytics_db' || '_test')
\gexec

-- Only explicitly granted roles may connect to each database.
SELECT format('REVOKE ALL ON DATABASE %I FROM PUBLIC', db),
       format('GRANT CONNECT, CREATE, TEMPORARY ON DATABASE %I TO %I', db, :'pipeline_user'),
       format('GRANT CONNECT ON DATABASE %I TO %I', db, :'bi_user')
FROM unnest(ARRAY[:'analytics_db', :'analytics_db' || '_test']) AS db
\gexec
SELECT format('REVOKE ALL ON DATABASE %I FROM PUBLIC', :'app_db') \gexec
SELECT format('GRANT ALL ON DATABASE %I TO %I', :'app_db', :'app_user') \gexec

-- Superset's dedicated read-only login (only when a password is configured). It gets CONNECT and
-- USAGE on marts here; SELECT only on the APPROVED datasets (superset/approved_datasets.yml),
-- granted by warehouse/publish.py at every publication.
SELECT format('CREATE ROLE %I LOGIN', :'superset_user')
WHERE :'superset_password' <> ''
  AND NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = :'superset_user')
\gexec
SELECT format('ALTER ROLE %I WITH LOGIN PASSWORD %L', :'superset_user', :'superset_password')
WHERE :'superset_password' <> ''
\gexec
SELECT format('GRANT CONNECT ON DATABASE %I TO %I', db, :'superset_user')
FROM unnest(ARRAY[:'analytics_db', :'analytics_db' || '_test']) AS db
WHERE :'superset_password' <> ''
\gexec

-- Django KPI service's read-only login (Milestone 7): same pattern, list backend/approved_datasets.yml.
SELECT format('CREATE ROLE %I LOGIN', :'kpi_user')
WHERE :'kpi_password' <> ''
  AND NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = :'kpi_user')
\gexec
SELECT format('ALTER ROLE %I WITH LOGIN PASSWORD %L', :'kpi_user', :'kpi_password')
WHERE :'kpi_password' <> ''
\gexec
SELECT format('GRANT CONNECT ON DATABASE %I TO %I', db, :'kpi_user')
FROM unnest(ARRAY[:'analytics_db', :'analytics_db' || '_test']) AS db
WHERE :'kpi_password' <> ''
\gexec
SQL

for db in "$DRUKSMART_ANALYTICS_DB" "${DRUKSMART_ANALYTICS_DB}_test"; do
echo "[init] analytical schemas in ${db}"
run_sql "$db" <<'SQL'
-- Layered warehouse schemas, owned by the pipeline role (ingestion + dbt).
SELECT format('CREATE SCHEMA IF NOT EXISTS %I AUTHORIZATION %I', s, :'pipeline_user')
FROM unnest(ARRAY['raw', 'staging', 'intermediate', 'marts']) AS s
\gexec

COMMENT ON SCHEMA raw IS
  'Landing area: ERP records as extracted, with source ERP/instance/id, batch and timestamp metadata.';
COMMENT ON SCHEMA staging IS
  'dbt staging models: one cleaned, renamed, type-cast model per source entity.';
COMMENT ON SCHEMA intermediate IS
  'dbt intermediate models: cross-ERP standardisation and verified entity mapping.';
COMMENT ON SCHEMA marts IS
  'Validated Kimball star schemas and KPI datasets; the only schema BI and AI services may read.';

-- Nobody but the pipeline may create objects in public.
REVOKE CREATE ON SCHEMA public FROM PUBLIC;

-- BI/AI reader: marts only, read-only, including tables dbt creates later.
SELECT format('GRANT USAGE ON SCHEMA marts TO %I', :'bi_user') \gexec
SELECT format('GRANT SELECT ON ALL TABLES IN SCHEMA marts TO %I', :'bi_user') \gexec
SELECT format('ALTER DEFAULT PRIVILEGES FOR ROLE %I IN SCHEMA marts GRANT SELECT ON TABLES TO %I',
              :'pipeline_user', :'bi_user') \gexec
SELECT format('GRANT USAGE ON SCHEMA marts TO %I', :'superset_user')
WHERE :'superset_password' <> '' \gexec
SELECT format('GRANT USAGE ON SCHEMA marts TO %I', :'kpi_user')
WHERE :'kpi_password' <> '' \gexec
SQL
done

echo "[init] done"
