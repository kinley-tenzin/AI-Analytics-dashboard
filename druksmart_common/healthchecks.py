"""Database health checks for the development environment.

Run from the repository root:
    python -m druksmart_common.healthchecks

Exit code 0 means every check passed. The same checks back the pytest smoke
tests in tests/smoke/.
"""

from __future__ import annotations

import sys
from collections.abc import Callable
from dataclasses import dataclass

import psycopg

from druksmart_common.config import ConfigError, Settings, load_settings
from druksmart_common.db import connect

EXPECTED_SCHEMAS = ("raw", "staging", "intermediate", "marts")


@dataclass(frozen=True)
class CheckResult:
    name: str
    passed: bool
    detail: str


def check_pipeline_connection(settings: Settings) -> CheckResult:
    """The pipeline role can log in to the analytics database."""
    with connect(settings.pipeline()) as conn:
        version = conn.execute("SHOW server_version").fetchone()[0]
        db, user = conn.execute("SELECT current_database(), current_user").fetchone()
    return CheckResult("pipeline connection", True, f"PostgreSQL {version}, {db} as {user}")


def check_schemas(settings: Settings) -> CheckResult:
    """All layered warehouse schemas exist and are owned by the pipeline role."""
    with connect(settings.pipeline()) as conn:
        rows = conn.execute(
            """
            SELECT n.nspname, pg_get_userbyid(n.nspowner)
            FROM pg_namespace n
            WHERE n.nspname = ANY(%s)
            """,
            (list(EXPECTED_SCHEMAS),),
        ).fetchall()
    owners = dict(rows)
    missing = [s for s in EXPECTED_SCHEMAS if s not in owners]
    wrong_owner = [s for s, o in owners.items() if o != settings.pipeline_user]
    passed = not missing and not wrong_owner
    detail = f"found {sorted(owners)}"
    if missing:
        detail += f"; missing {missing}"
    if wrong_owner:
        detail += f"; not owned by {settings.pipeline_user}: {wrong_owner}"
    return CheckResult("warehouse schemas", passed, detail)


def check_pipeline_can_write(settings: Settings) -> CheckResult:
    """The pipeline role can create tables in raw (rolled back, leaves nothing behind)."""
    with connect(settings.pipeline()) as conn:
        with conn.transaction(force_rollback=True):
            conn.execute("CREATE TABLE raw._healthcheck (id int)")
            conn.execute("INSERT INTO raw._healthcheck VALUES (1)")
    return CheckResult("pipeline write to raw", True, "create/insert succeeded (rolled back)")


def check_bi_reader_isolation(settings: Settings) -> CheckResult:
    """The BI reader may use marts but must not see raw, staging or intermediate."""
    with connect(settings.bi_reader()) as conn:
        privileges = dict(
            conn.execute(
                "SELECT s, has_schema_privilege(current_user, s, 'USAGE') "
                "FROM unnest(%s::text[]) AS s",
                (list(EXPECTED_SCHEMAS),),
            ).fetchall()
        )
        can_create_in_marts = conn.execute(
            "SELECT has_schema_privilege(current_user, 'marts', 'CREATE')"
        ).fetchone()[0]
    leaked = [s for s in ("raw", "staging", "intermediate") if privileges[s]]
    passed = privileges["marts"] and not leaked and not can_create_in_marts
    detail = f"usage={privileges}, create_in_marts={can_create_in_marts}"
    return CheckResult("bi_reader limited to marts (read-only)", passed, detail)


def check_app_database_isolation(settings: Settings) -> CheckResult:
    """The app role reaches its own database and cannot connect to analytics."""
    with connect(settings.application()) as conn:
        db = conn.execute("SELECT current_database()").fetchone()[0]
        can_connect_analytics = conn.execute(
            "SELECT has_database_privilege(current_user, %s, 'CONNECT')",
            (settings.analytics_db,),
        ).fetchone()[0]
    passed = db == settings.app_db and not can_connect_analytics
    detail = f"connected to {db}; CONNECT on {settings.analytics_db}={can_connect_analytics}"
    return CheckResult("app role separated from analytics", passed, detail)


ALL_CHECKS: tuple[Callable[[Settings], CheckResult], ...] = (
    check_pipeline_connection,
    check_schemas,
    check_pipeline_can_write,
    check_bi_reader_isolation,
    check_app_database_isolation,
)


def run_all(settings: Settings) -> list[CheckResult]:
    results = []
    for check in ALL_CHECKS:
        try:
            results.append(check(settings))
        except psycopg.Error as exc:
            name = check.__name__.removeprefix("check_").replace("_", " ")
            results.append(CheckResult(name, False, f"{type(exc).__name__}: {exc}".strip()))
    return results


def main() -> int:
    try:
        settings = load_settings()
    except ConfigError as exc:
        print(f"CONFIG ERROR: {exc}")
        return 2

    print(f"Checking PostgreSQL at {settings.pg_host}:{settings.pg_port}\n")
    results = run_all(settings)
    for r in results:
        print(f"[{'PASS' if r.passed else 'FAIL'}] {r.name}: {r.detail}")
    failed = sum(not r.passed for r in results)
    print(f"\n{len(results) - failed}/{len(results)} checks passed")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
