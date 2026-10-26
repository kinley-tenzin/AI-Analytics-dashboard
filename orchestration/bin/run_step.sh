#!/usr/bin/env bash
# Run ONE pipeline step with the project's own CLIs. Airflow tasks call this script, so the DAG
# contains no connector, transformation or publication logic.
#
#   run_step.sh check   <odoo|erpnext>
#   run_step.sh migrate
#   run_step.sh extract <odoo|erpnext> <hr|accounts>
#   run_step.sh dbt     <dbt arguments...>
#   run_step.sh publish <pipeline run id>
#   run_step.sh report
#
# Source mode (DRUKSMART_SOURCE_MODE):
#   configured - ERP settings from the environment (.env): real ERPs or the local sandboxes;
#                writes to DRUKSMART_ANALYTICS_DB.
#   synthetic  - the synthetic-erp service with FICTIONAL data (orchestration/synthetic_mode.env);
#                writes to the isolated "<DRUKSMART_ANALYTICS_DB>_test" database.
# Optional: AS_OF (synthetic replays only), FULL_REFRESH=true (ignore checkpoints).
set -euo pipefail

REPO="${DRUKSMART_REPO:-/opt/druksmart}"
PY="${DRUKSMART_PYTHON:-/opt/druksmart-venv/bin/python}"
MODE="${DRUKSMART_SOURCE_MODE:-configured}"
export PYTHONPATH="${REPO}"

case "${MODE}" in
  configured) ;;
  synthetic)
    set -a; . "${REPO}/orchestration/synthetic_mode.env"; set +a
    export DRUKSMART_ANALYTICS_DB="${DRUKSMART_ANALYTICS_DB}_test"
    ;;
  *) echo "unknown DRUKSMART_SOURCE_MODE '${MODE}' (configured|synthetic)" >&2; exit 2 ;;
esac
echo "[step] mode=${MODE} database=${DRUKSMART_ANALYTICS_DB} step=$*"

step="${1:?step required}"; shift
case "${step}" in
  check)
    exec "${PY}" -m ingestion check --source "${1:?source}"
    ;;
  migrate)
    exec "${PY}" -m ingestion migrate
    ;;
  extract)
    args=(-m ingestion -v extract --source "${1:?source}" --module "${2:?module}")
    [ -n "${AS_OF:-}" ] && [ "${AS_OF}" != "None" ] && args+=(--as-of "${AS_OF}")
    [ "${FULL_REFRESH:-false}" = "True" ] || [ "${FULL_REFRESH:-false}" = "true" ] && args+=(--full)
    exec "${PY}" "${args[@]}"
    ;;
  dbt)
    exec "${PY}" "${REPO}/warehouse/run_dbt.py" "$@"
    ;;
  publish)
    exec "${PY}" "${REPO}/warehouse/publish.py" publish --run-id "${1:?run id}"
    ;;
  report)
    "${PY}" "${REPO}/warehouse/publish.py" status
    exec "${PY}" -m ingestion summary
    ;;
  *)
    echo "unknown step '${step}'" >&2; exit 2
    ;;
esac
