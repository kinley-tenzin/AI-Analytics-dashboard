"""Which database account does each component ACTUALLY use? (Milestone 8, Task 1)

    python evaluation/db_connections.py

Each component runs `select current_user, current_database()` through ITS OWN connection code:
  Superset  : SQL Lab as admin on the registered "DrukSmart Warehouse" connection
  Django    : backend kpi.warehouse.connect() (manage.py shell)
  Airflow   : druksmart_common connect(settings.pipeline()) inside the scheduler container
plus a pg_stat_activity snapshot of current sessions. Results: docs/evaluation/results/db_connections.json.
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

import evaltools as et  # noqa: E402

PROBE = "select current_user || '@' || current_database()"


def superset() -> str:
    """Account on Superset's registered warehouse connection (password masked by Superset).

    SQL Lab cannot report the session user: Superset rejects identity/system functions such as
    current_user and pg_backend_pid (DISALLOWED_SQL_FUNCTIONS), a defence recorded as a finding.
    """
    api = et.superset("admin")
    db = api.find_one("database", "database_name", "DrukSmart Warehouse")
    uri = api.get(f"/api/v1/database/{db['id']}/connection")["result"]["sqlalchemy_uri"]
    return "configured: " + uri.split("//", 1)[1].split(":", 1)[0] + "@" + uri.rsplit("/", 1)[1]


def django() -> str:
    code = f'from kpi import warehouse; c = warehouse.connect(); print(c.execute("{PROBE}").fetchone()[0])'
    out = subprocess.run(
        [sys.executable, str(et.REPO / "backend/manage.py"), "shell", "-c", code],
        capture_output=True,
        text=True,
        check=True,
    ).stdout
    return out.strip().splitlines()[-1]


def airflow() -> str:
    code = (
        "from druksmart_common.config import load_settings; from druksmart_common.db import connect; "
        f'c = connect(load_settings().pipeline()); print(c.execute("{PROBE}").fetchone()[0])'
    )
    out = et.compose(
        "exec",
        "-T",
        "-w",
        "/opt/druksmart",
        "airflow-scheduler",
        "/opt/druksmart-venv/bin/python",
        "-c",
        code,
    ).stdout
    return out.strip().splitlines()[-1]


def main() -> int:
    observed = {
        "superset": superset(),
        "django_kpi_service": django(),
        "airflow_pipeline": airflow(),
    }
    query = (
        "select usename, datname, count(*) from pg_stat_activity where datname is not null "
        "and pid <> pg_backend_pid() group by 1, 2 order by 1, 2"
    )
    out = et.compose(
        "exec",
        "-T",
        "postgres",
        "psql",
        "-U",
        "druksmart_admin",
        "-d",
        "postgres",
        "-tA",
        "-F",
        "|",
        "-c",
        query,
    ).stdout
    sessions = [
        dict(zip(("user", "database", "sessions"), line.split("|"), strict=True)) for line in out.strip().splitlines()
    ]
    et.save_result("db_connections", {"observed_current_user": observed, "pg_stat_activity": sessions})
    for k, v in observed.items():
        print(f"{k:<20} {v}")
    print(sessions)
    return 0


if __name__ == "__main__":
    sys.exit(main())
