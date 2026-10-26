"""DrukSmart platform operations: check, set up, start, verify, back up and restore (Milestone 9).

    python deploy/druksmart.py check                  # prerequisites (tools, RAM, disk, ports, .env)
    python deploy/druksmart.py setup                  # first-time / repeat-safe setup of everything
    python deploy/druksmart.py up [--minimal]         # start services in order, wait for health
    python deploy/druksmart.py status                 # health of every service + data freshness
    python deploy/druksmart.py run-pipeline [--synthetic]
    python deploy/druksmart.py demo-data live|synthetic   # what Superset and the assistant show
    python deploy/druksmart.py backup [--include-env]
    python deploy/druksmart.py restore-check <backup dir> # restore into TEMPORARY databases, compare
    python deploy/druksmart.py restore <backup dir> --yes # REPLACE the databases (destructive)
    python deploy/druksmart.py stop                   # stop containers; ALL data is kept

Common option: --env-file PATH (default: .env). A different file with another COMPOSE_PROJECT_NAME
and ports deploys a second, fully separate stack (used for the clean-start test).

Safety: no command except `restore --yes` deletes or overwrites data; `stop` never removes volumes.
Run with the project virtual environment (`.venv`), which has the Superset bootstrap dependencies.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import socket
import subprocess
import sys
import time
import urllib.request
from datetime import datetime
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
PY = sys.executable
DAG = "druksmart_elt"
REQUIRED_KEYS = (
    "POSTGRES_PASSWORD",
    "DRUKSMART_PIPELINE_PASSWORD",
    "DRUKSMART_BI_READER_PASSWORD",
    "DRUKSMART_APP_PASSWORD",
    "DRUKSMART_SUPERSET_READER_PASSWORD",
    "DRUKSMART_KPI_READER_PASSWORD",
    "SUPERSET_ADMIN_PASSWORD",
    "SUPERSET_SECRET_KEY",
    "SUPERSET_DB_PASSWORD",
    "SUPERSET_GUEST_TOKEN_SECRET",  # Milestone 10: embedded dashboards in the website
    "SUPERSET_PORTAL_SERVICE_PASSWORD",
    "AIRFLOW_ADMIN_PASSWORD",
    "AIRFLOW_DB_PASSWORD",
    "AIRFLOW_JWT_SECRET",
    "AIRFLOW_FERNET_KEY",
    "DJANGO_SECRET_KEY",
)


# ----------------------------------------------------------------------------- environment
def read_env(path: Path) -> dict[str, str]:
    values = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            key, _, value = line.partition("=")
            values[key.strip()] = value.strip()
    return values


class Platform:
    def __init__(self, env_file: Path):
        self.env_file = env_file.resolve()
        if not self.env_file.exists():
            raise SystemExit(f"{self.env_file} not found: run `python deploy/druksmart.py setup` first")
        self.cfg = read_env(self.env_file)
        self.project = self.cfg.get("COMPOSE_PROJECT_NAME", "druksmart")
        # Host-side tools (bootstrap, evaluation) read these instead of the repository .env.
        self.env = {**os.environ, **self.cfg}
        self.env.pop("COMPOSE_PROJECT_NAME", None)

    def port(self, key: str, default: int) -> int:
        return int(self.cfg.get(key, default))

    # ---------------------------------------------------------------- docker compose
    def compose(
        self, *args: str, profiles=("airflow", "superset", "backend"), check=True, capture=True, timeout=1800
    ) -> subprocess.CompletedProcess:
        cmd = ["docker", "compose", "--env-file", str(self.env_file), "-p", self.project]
        for p in profiles:
            cmd += ["--profile", p]
        proc = subprocess.run(
            cmd + list(args), cwd=REPO, env=self.env, capture_output=capture, text=True, timeout=timeout
        )
        if check and proc.returncode:
            raise SystemExit(
                f"docker compose {' '.join(args)} failed:\n{(proc.stdout or '')[-1500:]}{(proc.stderr or '')[-1500:]}"
            )
        return proc

    def airflow(self, *args: str, check=True) -> str:
        return self.compose("exec", "-T", "airflow-scheduler", "airflow", *args, check=check).stdout

    def psql(self, database: str, sql: str) -> str:
        return self.compose(
            "exec",
            "-T",
            "postgres",
            "psql",
            "-U",
            self.cfg["POSTGRES_USER"],
            "-d",
            database,
            "-tA",
            "-c",
            sql,
            profiles=(),
        ).stdout.strip()

    def python(self, *args: str, check=True) -> subprocess.CompletedProcess:
        proc = subprocess.run([PY, *args], cwd=REPO, env=self.env, capture_output=True, text=True)
        if check and proc.returncode:
            raise SystemExit(f"{' '.join(args)} failed:\n{proc.stdout[-2000:]}{proc.stderr[-2000:]}")
        return proc

    def url_ok(self, url: str, timeout: float = 5) -> bool:
        try:
            with urllib.request.urlopen(url, timeout=timeout) as r:
                return r.status == 200
        except Exception:
            return False


def say(msg: str) -> None:
    print(f"[druksmart] {msg}", flush=True)


# ----------------------------------------------------------------------------- check
def cmd_check(p: Platform | None, env_file: Path) -> int:
    problems, warnings = [], []

    def tool(cmd):
        try:
            return subprocess.run(cmd, capture_output=True, text=True, timeout=60).stdout.strip()
        except Exception:
            return ""

    docker = tool(["docker", "version", "--format", "{{.Server.Version}}"])
    compose = tool(["docker", "compose", "version", "--short"])
    print(f"  Docker engine      {docker or 'NOT RUNNING'}")
    print(f"  Docker Compose     {compose or 'missing'}")
    print(f"  Python             {sys.version.split()[0]} ({PY})")
    if not docker:
        problems.append("Docker Desktop is not running (start it; if stuck: wsl --shutdown, restart)")
    import importlib.util

    missing = [m for m in ("django", "dotenv", "httpx", "psycopg", "yaml") if importlib.util.find_spec(m) is None]
    if missing:
        problems.append(f"project venv incomplete ({', '.join(missing)}): pip install -e .[dev,warehouse,backend]")
    free = shutil.disk_usage(REPO).free / 1024**3
    print(f"  Free disk          {free:.0f} GB (need >= 25 GB)")
    if free < 25:
        problems.append("less than 25 GB free disk")
    mem = (
        tool(["powershell", "-NoProfile", "-Command", "(Get-CimInstance Win32_ComputerSystem).TotalPhysicalMemory"])
        if os.name == "nt"
        else ""
    )
    if mem.isdigit():
        gb = int(mem) / 1024**3
        print(f"  RAM                {gb:.1f} GB (16 GB recommended for the full stack)")
        if gb < 15:
            warnings.append("less than 16 GB RAM: use `up --minimal` and run the ERP sandboxes only when needed")
    for wheels in ("orchestration/docker/wheels", "backend/docker/wheels"):
        if not any((REPO / wheels).glob("*.whl")):
            warnings.append(f"{wheels}/ is empty: needed only to BUILD images (see deploy/README.md)")
    if not env_file.exists():
        problems.append(f"{env_file.name} missing: run setup (it creates one with random passwords)")
    else:
        cfg = read_env(env_file)
        bad = [k for k in REQUIRED_KEYS if cfg.get(k, "CHANGE_ME") in ("", "CHANGE_ME")]
        if bad:
            problems.append(f"{env_file.name}: not set: {', '.join(bad)} (create_local_env.py --add-missing)")
        project = cfg.get("COMPOSE_PROJECT_NAME", "druksmart")
        ours = tool(
            ["docker", "ps", "--filter", f"label=com.docker.compose.project={project}", "--format", "{{.Ports}}"]
        )
        for key, default in (
            ("DRUKSMART_PG_PORT", 5433),
            ("AIRFLOW_PORT", 8085),
            ("SUPERSET_PORT", 8088),
            ("BACKEND_PORT", 8000),
        ):
            port = int(cfg.get(key, default))
            with socket.socket() as s:
                busy = s.connect_ex(("127.0.0.1", port)) == 0
            if busy and f":{port}->" not in ours:
                problems.append(f"port {port} ({key}) is used by another program")
            print(f"  Port {port:<6}        {'in use by this platform' if busy else 'free'}")
    for w in warnings:
        print(f"  WARNING: {w}")
    for pr in problems:
        print(f"  PROBLEM: {pr}")
    print("check:", "OK" if not problems else f"{len(problems)} problem(s)")
    return 1 if problems else 0


# ----------------------------------------------------------------------------- up / setup
def wait_for(predicate, timeout: int, poll: float = 5) -> bool:
    end = time.monotonic() + timeout
    while time.monotonic() < end:
        try:
            if predicate():
                return True
        except Exception:
            pass
        time.sleep(poll)
    return False


def cmd_up(p: Platform, minimal: bool = False) -> int:
    say("1/4 PostgreSQL warehouse")
    p.compose("up", "-d", "--wait", "postgres", profiles=())
    if not minimal:
        say("2/4 Airflow (metadata DB, init, api-server, scheduler, dag-processor, synthetic ERP)")
        p.compose(
            "up",
            "-d",
            "--wait",
            "airflow-apiserver",
            "airflow-scheduler",
            "airflow-dag-processor",
            "synthetic-erp",
            profiles=("airflow",),
            timeout=2400,
        )
    else:
        say("2/4 Airflow skipped (--minimal)")
    say("3/4 Superset (metadata DB, init, web)")
    p.compose("up", "-d", "--wait", "superset", profiles=("superset",), timeout=2400)
    say("4/4 Django backend (migrations, gunicorn)")
    p.compose("up", "-d", "--wait", "backend", profiles=("backend",))
    return cmd_status(p)


def cmd_setup(p_env: Path, args) -> int:
    if not p_env.exists():
        say(f"creating {p_env.name} with random passwords (values are never printed)")
        subprocess.run([PY, str(REPO / "infrastructure/scripts/create_local_env.py")], check=True, cwd=REPO)
    elif p_env == REPO / ".env":
        subprocess.run(
            [PY, str(REPO / "infrastructure/scripts/create_local_env.py"), "--add-missing"], check=True, cwd=REPO
        )
    p = Platform(p_env)
    if cmd_check(p, p_env):
        return 1
    if args.build:
        say("building images (offline wheels)")
        p.compose("build", "airflow-init", "superset", "backend", timeout=3600)
    say("starting PostgreSQL and (re)applying roles/databases (idempotent)")
    p.compose("up", "-d", "--wait", "postgres", profiles=())
    p.compose(
        "exec", "-T", "postgres", "bash", "/docker-entrypoint-initdb.d/01_init_databases_roles_schemas.sh", profiles=()
    )
    cmd_up(p)
    say("raw-table migrations (idempotent)")
    p.compose(
        "exec",
        "-T",
        "airflow-scheduler",
        "bash",
        "/opt/druksmart/orchestration/bin/run_step.sh",
        "migrate",
        profiles=("airflow",),
    )
    if not published(p):
        if erps_reachable(p):
            say("no published marts yet: running the pipeline once (configured ERP sources)")
            cmd_run_pipeline(p, synthetic=False)
        else:
            # Fresh install without reachable ERPs: show the labelled SYNTHETIC dataset instead of
            # empty dashboards (switch back later with `demo-data live`).
            say("ERP sources not reachable: loading the SYNTHETIC demonstration dataset")
            cmd_run_pipeline(p, synthetic=True)
            set_env_value(p.env_file, "DRUKSMART_CONSUMER_DATA", "synthetic")
            p = Platform(p.env_file)
            p.compose("up", "-d", "--wait", "backend", profiles=("backend",))  # picks up the switch
    say("Superset: database connection, governed datasets, roles, RLS, dashboards (bootstrap)")
    p.python(str(REPO / "superset/scripts/bootstrap.py"))
    if p.cfg.get("BACKEND_DEMO_USER_PASSWORD", "CHANGE_ME") not in ("", "CHANGE_ME"):
        say("Django: role groups + LOCAL demo users")
        p.compose("exec", "-T", "backend", "python", "manage.py", "seed_demo_users", profiles=("backend",))
    if erps_reachable(p) and p.cfg.get("DRUKSMART_ELT_SCHEDULE", "0 2 * * *") != "none":
        p.airflow("dags", "unpause", DAG)
        say("daily schedule enabled (ERP sources reachable)")
    else:
        say("DAG left PAUSED (ERP sources not reachable): use `run-pipeline --synthetic` for demos")
    return cmd_status(p)


# ----------------------------------------------------------------------------- pipeline / data
def erps_reachable(p: Platform) -> bool:
    return p.url_ok(f"{p.cfg.get('ODOO_BASE_URL', '')}/web/login") and p.url_ok(
        f"{p.cfg.get('ERPNEXT_BASE_URL', '')}/api/method/ping"
    )


def published(p: Platform, database: str | None = None) -> bool:
    db = database or p.cfg["DRUKSMART_ANALYTICS_DB"]
    out = p.psql(
        db,
        "select count(*) from pg_tables where schemaname = 'marts' and tablename = 'data_freshness'",
    )
    return out == "1" and p.psql(db, "select count(*) from marts.data_freshness where published_at is not null") != "0"


def dag_paused(p: Platform) -> bool:
    dags = json.loads(p.airflow("dags", "list", "-o", "json") or "[]")
    return any(d["dag_id"] == DAG and str(d["is_paused"]).lower() == "true" for d in dags)


def trigger_and_wait(p: Platform, run_id: str, conf: dict, timeout: int = 2400) -> str:
    # A run of a PAUSED DAG stays queued in Airflow 3 (found by the clean-start test): unpause for
    # the run and restore the previous state afterwards.
    was_paused = dag_paused(p)
    if was_paused:
        p.airflow("dags", "unpause", DAG)
    try:
        return _trigger_and_wait(p, run_id, conf, timeout)
    finally:
        if was_paused:
            p.airflow("dags", "pause", DAG)


def _trigger_and_wait(p: Platform, run_id: str, conf: dict, timeout: int = 2400) -> str:
    p.airflow("dags", "trigger", DAG, "--run-id", run_id, "-c", json.dumps(conf))
    state = "queued"

    def done():
        nonlocal state
        runs = json.loads(p.airflow("dags", "list-runs", DAG, "-o", "json") or "[]")
        state = next((r["state"] for r in runs if r["run_id"] == run_id), "queued")
        return state in ("success", "failed")

    wait_for(done, timeout, 10)
    return state


def cmd_run_pipeline(p: Platform, synthetic: bool) -> int:
    stamp = datetime.now().strftime("%Y%m%dT%H%M%S")
    if synthetic:
        say("SYNTHETIC mode: replaying the fictional fixture batches (writes <analytics db>_test)")
        for as_of in ("2026-09-30T17:30:00Z", "2026-10-31T17:30:00Z"):
            state = trigger_and_wait(
                p, f"deploy_synthetic_{as_of[:10]}_{stamp}", {"source_mode": "synthetic", "as_of": as_of}
            )
            say(f"  synthetic replay {as_of[:10]}: {state}")
            if state != "success":
                return 1
        return 0
    state = trigger_and_wait(p, f"deploy_configured_{stamp}", {"source_mode": "configured"})
    say(f"configured run (ERP sources from .env): {state}")
    return 0 if state == "success" else 1


def set_env_value(path: Path, key: str, value: str) -> None:
    """Replace or append KEY=value in place (no value is printed)."""
    lines = path.read_text(encoding="utf-8").splitlines()
    for i, line in enumerate(lines):
        if line.partition("=")[0].strip() == key:
            lines[i] = f"{key}={value}"
            break
    else:
        lines.append(f"{key}={value}")
    path.write_text("\n".join(lines) + "\n", encoding="utf-8", newline="\n")


def cmd_demo_data(p: Platform, mode: str) -> int:
    test_db = p.cfg["DRUKSMART_ANALYTICS_DB"] + "_test"
    if mode == "synthetic" and not published(p, test_db):
        say("no published SYNTHETIC marts yet: replaying the synthetic batches first")
        if cmd_run_pipeline(p, synthetic=True):
            return 1
    set_env_value(p.env_file, "DRUKSMART_CONSUMER_DATA", mode)
    p = Platform(p.env_file)
    say(f"Superset and the assistant now read {'SYNTHETIC (fictional)' if mode == 'synthetic' else 'LIVE'} data")
    p.python(str(REPO / "superset/scripts/bootstrap.py"))
    p.compose("up", "-d", "--wait", "backend", profiles=("backend",))
    return cmd_status(p)


# ----------------------------------------------------------------------------- status
def cmd_status(p: Platform) -> int:
    rows = []
    ps = p.compose("ps", "--all", "--format", "json", check=False).stdout
    containers = {}
    for line in ps.splitlines():
        try:
            c = json.loads(line)
        except json.JSONDecodeError:
            continue
        for item in c if isinstance(c, list) else [c]:
            containers[item["Service"]] = item.get("Health") or item.get("State")
    for service in (
        "postgres",
        "airflow-db",
        "airflow-apiserver",
        "airflow-scheduler",
        "airflow-dag-processor",
        "synthetic-erp",
        "superset-db",
        "superset",
        "backend",
    ):
        rows.append((service, containers.get(service, "not created")))
    checks = {
        "Superset UI": p.url_ok(f"http://127.0.0.1:{p.port('SUPERSET_PORT', 8088)}/health"),
        "Airflow API": p.url_ok(f"http://127.0.0.1:{p.port('AIRFLOW_PORT', 8085)}/api/v2/monitor/health"),
        "Django /health/ready": p.url_ok(f"http://127.0.0.1:{p.port('BACKEND_PORT', 8000)}/health/ready/"),
        "Website /app/": p.url_ok(f"http://127.0.0.1:{p.port('BACKEND_PORT', 8000)}/app/"),
        "ERP sandboxes reachable": erps_reachable(p),
    }
    print(f"\nProject {p.project} ({p.env_file.name})")
    for service, state in rows:
        print(f"  {service:<24} {state}")
    for name, ok in checks.items():
        print(f"  {name:<24} {'OK' if ok else 'not available'}")
    try:
        mode = p.cfg.get("DRUKSMART_CONSUMER_DATA", "live")
        db = p.cfg["DRUKSMART_ANALYTICS_DB"] + ("_test" if mode == "synthetic" else "")
        fresh = p.psql(
            db,
            "select string_agg(source_instance || '/' || domain || ' ' || latest_snapshot_date "
            "|| ' (' || coalesce(source_mode, 'unpublished') || ')', '; ') from marts.data_freshness",
        )
        print(f"  Consumers read          {mode.upper()} data ({db})")
        print(f"  Data freshness          {fresh or 'nothing published'}")
    except SystemExit:
        print("  Data freshness          nothing published yet (or warehouse not reachable)")
    try:
        dags = json.loads(p.airflow("dags", "list", "-o", "json", check=False) or "[]")
        for d in dags:
            paused = str(d["is_paused"]).lower() == "true"  # the CLI returns the text 'True'/'False'
            print(f"  DAG {d['dag_id']:<20} {'paused' if paused else 'scheduled'}")
    except (json.JSONDecodeError, SystemExit):
        print("  DAG                     Airflow not running")
    return 0


# ----------------------------------------------------------------------------- backup / restore
def sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


DUMPS = {  # file -> (compose service, user key or literal, database key or literal, profiles)
    "warehouse.dump": ("postgres", "POSTGRES_USER", "DRUKSMART_ANALYTICS_DB", ()),
    "app.dump": ("postgres", "POSTGRES_USER", "DRUKSMART_APP_DB", ()),
    "superset_meta.dump": ("superset-db", "=superset", "=superset", ("superset",)),
    "airflow_meta.dump": ("airflow-db", "=airflow", "=airflow", ("airflow",)),
}


def _v(p: Platform, key: str) -> str:
    return key[1:] if key.startswith("=") else p.cfg[key]


def cmd_backup(p: Platform, include_env: bool) -> int:
    dest = REPO / "backups" / datetime.now().strftime("%Y%m%dT%H%M%S")
    dest.mkdir(parents=True)
    manifest = {
        "created": datetime.now().isoformat(timespec="seconds"),
        "project": p.project,
        "files": {},
    }
    for name, (service, user, db, profiles) in DUMPS.items():
        cmd = [
            "docker",
            "compose",
            "--env-file",
            str(p.env_file),
            "-p",
            p.project,
            *[x for pr in profiles for x in ("--profile", pr)],
            "exec",
            "-T",
            service,
            "pg_dump",
            "-U",
            _v(p, user),
            "-d",
            _v(p, db),
            "--format=custom",
        ]
        with (dest / name).open("wb") as out:
            proc = subprocess.run(cmd, cwd=REPO, env=p.env, stdout=out, stderr=subprocess.PIPE)
        if proc.returncode:
            (dest / name).unlink()
            manifest["files"][name] = {"skipped": proc.stderr.decode(errors="replace")[-300:]}
            say(f"  {name}: skipped ({service} not running?)")
            continue
        manifest["files"][name] = {
            "bytes": (dest / name).stat().st_size,
            "sha256": sha256(dest / name),
        }
        say(f"  {name}: {manifest['files'][name]['bytes']:,} bytes")
    proc = p.python(str(REPO / "superset/scripts/assets.py"), "export", check=False)
    if proc.returncode == 0:
        shutil.copytree(REPO / "superset/assets/dashboards", dest / "superset_assets")
        manifest["files"]["superset_assets/"] = {"note": "Superset native YAML export (no passwords)"}
    if include_env:
        shutil.copy2(p.env_file, dest / "env.SECRET")
        manifest["files"]["env.SECRET"] = {"note": "ALL PLATFORM SECRETS: store like a password"}
    counts = {}
    for table in (
        "raw.source_record",
        "marts.fct_headcount_snapshot",
        "marts.fct_receivable_payable_snapshot",
        "marts.data_freshness",
    ):
        counts[table] = p.psql(p.cfg["DRUKSMART_ANALYTICS_DB"], f"select count(*) from {table}")
    counts["app:auth_user"] = p.psql(p.cfg["DRUKSMART_APP_DB"], "select count(*) from auth_user")
    manifest["row_counts_at_backup"] = counts
    (dest / "manifest.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    say(f"backup written to {dest.relative_to(REPO)} (git-ignored; contains password hashes and data)")
    return 0


def _restore_into(p: Platform, dump: Path, service: str, user: str, database: str, profiles) -> None:
    cmd = [
        "docker",
        "compose",
        "--env-file",
        str(p.env_file),
        "-p",
        p.project,
        *[x for pr in profiles for x in ("--profile", pr)],
        "exec",
        "-T",
        service,
        "pg_restore",
        "-U",
        user,
        "-d",
        database,
        # Ownership and grants come from the dump (roles have the same names in every deployment).
        # `--no-owner` made the superuser own everything and locked the pipeline out (found by the
        # clean-start restore test).
        "--clean",
        "--if-exists",
    ]
    with dump.open("rb") as f:
        proc = subprocess.run(cmd, cwd=REPO, env=p.env, stdin=f, capture_output=True)
    errors = [ln for ln in proc.stderr.decode(errors="replace").splitlines() if "error" in ln.lower()]
    if errors:
        raise SystemExit(f"pg_restore into {database} reported errors:\n" + "\n".join(errors[:10]))


def cmd_restore_check(p: Platform, backup: Path) -> int:
    """Restore the warehouse and app dumps into TEMPORARY databases and compare row counts."""
    manifest = json.loads((backup / "manifest.json").read_text(encoding="utf-8"))
    for name, meta in manifest["files"].items():
        if "sha256" in meta and sha256(backup / name) != meta["sha256"]:
            raise SystemExit(f"{name}: checksum mismatch")
    say("checksums OK")
    admin = p.cfg["POSTGRES_USER"]
    ok = True
    for name, table_db in (("warehouse.dump", "warehouse"), ("app.dump", "app")):
        temp = f"druksmart_restorecheck_{table_db}"
        p.psql("postgres", f"drop database if exists {temp}")
        p.psql("postgres", f"create database {temp}")
        try:
            _restore_into(p, backup / name, "postgres", admin, temp, ())
            tables = [k for k in manifest["row_counts_at_backup"] if (k.startswith("app:") == (table_db == "app"))]
            for t in tables:
                restored = p.psql(temp, f"select count(*) from {t.split(':')[-1]}")
                expected = manifest["row_counts_at_backup"][t]
                ok &= restored == expected
                verdict = "OK" if restored == expected else "MISMATCH"
                say(f"  {t:<45} backup {expected:>6}  restored {restored:>6}  {verdict}")
        finally:
            p.psql("postgres", f"drop database if exists {temp}")
    say("restore check " + ("PASSED (temporary databases removed)" if ok else "FAILED"))
    return 0 if ok else 1


def cmd_restore(p: Platform, backup: Path, yes: bool) -> int:
    if not yes:
        raise SystemExit("restore REPLACES the current databases; re-run with --yes to confirm")
    admin = p.cfg["POSTGRES_USER"]
    say("restoring warehouse, app and Superset metadata (stop Airflow/Superset/backend first is safest)")
    _restore_into(p, backup / "warehouse.dump", "postgres", admin, p.cfg["DRUKSMART_ANALYTICS_DB"], ())
    _restore_into(p, backup / "app.dump", "postgres", admin, p.cfg["DRUKSMART_APP_DB"], ())
    if (backup / "superset_meta.dump").exists():
        _restore_into(p, backup / "superset_meta.dump", "superset-db", "superset", "superset", ("superset",))
    say("re-applying roles and grants (passwords from the CURRENT env file)")
    p.compose(
        "exec", "-T", "postgres", "bash", "/docker-entrypoint-initdb.d/01_init_databases_roles_schemas.sh", profiles=()
    )
    p.compose(
        "exec",
        "-T",
        "airflow-scheduler",
        "/opt/druksmart-venv/bin/python",
        "/opt/druksmart/warehouse/publish.py",
        "grant-consumers",
        profiles=("airflow",),
        check=False,
    )
    p.compose("restart", "superset", "backend", profiles=("superset", "backend"))
    p.python(str(REPO / "superset/scripts/bootstrap.py"))
    return cmd_status(p)


def cmd_stop(p: Platform) -> int:
    p.compose("stop")
    say("containers stopped; volumes and data are kept (start again with `up`)")
    return 0


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--env-file", type=Path, default=REPO / ".env")
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("check")
    s = sub.add_parser("setup")
    s.add_argument("--build", action="store_true", help="(re)build the images first")
    u = sub.add_parser("up")
    u.add_argument("--minimal", action="store_true", help="no Airflow (saves ~1 GB RAM)")
    sub.add_parser("status")
    r = sub.add_parser("run-pipeline")
    r.add_argument("--synthetic", action="store_true")
    d = sub.add_parser("demo-data")
    d.add_argument("mode", choices=["live", "synthetic"])
    b = sub.add_parser("backup")
    b.add_argument("--include-env", action="store_true", help="also copy the env file (SECRETS)")
    rc = sub.add_parser("restore-check")
    rc.add_argument("backup", type=Path)
    rs = sub.add_parser("restore")
    rs.add_argument("backup", type=Path)
    rs.add_argument("--yes", action="store_true")
    sub.add_parser("stop")
    args = parser.parse_args(argv)
    env_file = args.env_file.resolve()
    if args.command == "check":
        return cmd_check(None, env_file)
    if args.command == "setup":
        return cmd_setup(env_file, args)
    p = Platform(env_file)
    return {
        "up": lambda: cmd_up(p, args.minimal),
        "status": lambda: cmd_status(p),
        "run-pipeline": lambda: cmd_run_pipeline(p, args.synthetic),
        "demo-data": lambda: cmd_demo_data(p, getattr(args, "mode", "live")),
        "backup": lambda: cmd_backup(p, getattr(args, "include_env", False)),
        "restore-check": lambda: cmd_restore_check(p, args.backup),
        "restore": lambda: cmd_restore(p, args.backup, getattr(args, "yes", False)),
        "stop": lambda: cmd_stop(p),
    }[args.command]()


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
