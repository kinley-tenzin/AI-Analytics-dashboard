# Development Setup (Windows)

This guide takes a team member from a fresh Windows machine to a verified local environment.
For the **complete platform** (Airflow, Superset, backend) in one command, use
`python deploy\druksmart.py setup` ([DEPLOYMENT.md](DEPLOYMENT.md)); this page covers the developer setup.
Every step lists the command and the expected result.

## 1. Prerequisites

Versions below are the ones **verified on the reference machine in Milestone 1** (2026-10-21).
Newer patch versions are fine.

| Tool | Verified version | Why it is needed | Check with |
|------|------------------|------------------|------------|
| Windows 11 (64-bit) | 10.0.26200 | Host OS | `winver` |
| WSL2 | default version 2 | Docker Desktop's Linux engine runs inside WSL2 | `wsl --status` |
| Docker Desktop | Engine 29.7.2, Compose v5.4.0 | Runs PostgreSQL now; Airflow, Superset and ERP sandboxes later | `docker --version`, `docker compose version` |
| Python | 3.14.3 (3.12+ supported) | Connectors, ingestion, dbt, Django, tests | `python --version` |
| Git | 2.53 | Version control | `git --version` |
| Node.js + npm | 24.14.0 LTS + npm 11.9 | Only for **developing** the web app (`frontend/`); the backend image builds it itself | `node --version`, `npm --version` |
| VS Code | 1.142 | Editor (any editor works) | `code --version` |
| `psql` client | optional | Manual SQL inspection | see §6 |

Hardware: 16 GB RAM is the practical minimum once Airflow, Superset and the two ERP sandboxes
run together. Keep **at least 25 GB free disk** for Docker images and volumes.

### Installing a missing tool

- **WSL2** (PowerShell as Administrator): `wsl --install`, then reboot.
  Expected: `wsl --status` shows `Default Version: 2`.
- **Docker Desktop**: install from <https://www.docker.com/products/docker-desktop/> using the WSL2
  backend. Start it and wait until the whale icon says *Engine running*.
  Expected: `docker run --rm hello-world` prints `Hello from Docker!`.
- **Python**: `winget install Python.Python.3.12` (or 3.13/3.14) and tick *Add to PATH* if prompted.
  Open a new terminal. Expected: `python --version` prints 3.12 or newer.
- **Node.js** (web app development only): `winget install OpenJS.NodeJS.LTS`, then open a new terminal.
  Expected: `node --version` prints v24.x. Then `cd frontend; npm ci` (see docs/web/FRONTEND.md).
- **Git**: `winget install Git.Git`, then set your identity once:
  `git config --global user.name "Your Name"` and `git config --global user.email "you@example.com"`.

## 2. Get the code

```powershell
git clone <repository-url> FYP
cd FYP
```

Keep the repository **outside OneDrive/Google Drive** synced folders (e.g. `C:\Users\<you>\FYP`).
Syncing `.venv` and Docker-related files causes slowdowns and file-lock errors.

## 3. Python environment

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
python -m pip install -e ".[dev,warehouse]"
```

`warehouse` installs dbt (about 60 MB; one wheel is 54 MB). On a slow connection pip may stall: see
Troubleshooting.

Expected: the prompt starts with `(.venv)`, and `pip list` shows `psycopg 3.3.6`, `pytest 9.1.1`,
`ruff 0.17.1`, `druksmart-platform 0.1.0`.

If `Activate.ps1` is blocked ("running scripts is disabled"), run once:
`Set-ExecutionPolicy -Scope CurrentUser RemoteSigned`.

## 4. Local configuration (.env)

```powershell
python infrastructure\scripts\create_local_env.py
```

Expected: `Created ...\.env` and `Generated random values for: POSTGRES_PASSWORD, ...`.
The script never prints passwords and refuses to overwrite an existing `.env`.
Each team member has their **own** `.env`. Never commit it or share it in chat.

## 5. Start PostgreSQL

```powershell
docker compose up -d --wait
docker compose ps
```

Expected: `druksmart-postgres-1  postgres:17.11-bookworm  Up ... (healthy)  127.0.0.1:5433->5432/tcp`.

On the very first start the container runs
`infrastructure/postgres/init/01_init_databases_roles_schemas.sh`; `docker compose logs postgres`
shows `[init] done`.

## 6. Verify

```powershell
python -m druksmart_common.healthchecks
python -m ingestion migrate          # creates the raw extraction tables (safe to repeat)
pytest
```

Expected:

```
[PASS] pipeline connection: PostgreSQL 17.11 ..., druksmart_analytics as druksmart_pipeline
[PASS] warehouse schemas: found ['intermediate', 'marts', 'raw', 'staging']
[PASS] pipeline write to raw: create/insert succeeded (rolled back)
[PASS] bi_reader limited to marts (read-only): ...
[PASS] app role separated from analytics: ...
5/5 checks passed
```

and all tests passing from pytest (live ERP tests are **skipped** until an ERP is configured; with
both local sandboxes running, 238 tests pass). Run only the database smoke tests with `pytest -m smoke`,
only unit tests (no Docker needed) with `pytest tests/unit`, and the live ERP tests with `pytest -m live -v`.

Optional local ERP sandboxes (Odoo 19 + ERPNext 16 with synthetic data, ~3 GB RAM, ~9 GB disk):
see [connectors/SANDBOXES.md](connectors/SANDBOXES.md).

Optional Airflow (~1 GB RAM, ~4 GB disk for the image): `python infrastructure\scripts\create_local_env.py
--add-missing`, pre-download the wheels and `docker compose --profile airflow up -d`. See
[orchestration/ORCHESTRATION.md](orchestration/ORCHESTRATION.md).

Optional Superset BI (~2 GB RAM, ~1.5 GB disk): `docker compose --profile superset up -d --build --wait`,
then `python superset\scripts\bootstrap.py`. See [bi/SUPERSET.md](bi/SUPERSET.md). The headless
browser check needs `pip install -e ".[bi-test]"` (uses the installed Microsoft Edge).

Optional Django backend + KPI assistant: `pip install -e ".[dev,backend]"`, then
`python backend\manage.py migrate`, `python backend\manage.py seed_demo_users` and
`python backend\manage.py runserver 127.0.0.1:8000`. See [backend/BACKEND.md](backend/BACKEND.md).

Optional manual SQL access. This opens a shell inside the container, so no local `psql` is needed:

```powershell
docker compose exec postgres psql -U druksmart_admin -d druksmart_analytics -c "\dn+"
```

## 7. Daily use

| Task | Command |
|------|---------|
| Start database | `docker compose up -d --wait` |
| Stop (data kept) | `docker compose stop` |
| Logs | `docker compose logs -f postgres` |
| Lint / format | `ruff check .` / `ruff format .` |
| Web app: dev server / tests / build | `cd frontend`, then `npm run dev` / `npm test` / `npm run build` |

**Destructive (deletes all local database data):** `docker compose down -v`. Only use it to rebuild
from scratch, and only when nobody needs the local data.

## 8. Troubleshooting

| Symptom | Cause | Fix |
|---------|-------|-----|
| `Docker Desktop is unable to start` / `docker info` errors | Docker backend stuck (seen on the reference machine) | Quit Docker Desktop from the tray icon, run `wsl --shutdown`, start Docker Desktop again, wait for *Engine running* |
| `port is already allocated` on 5433 | Another service uses the port | Set `DRUKSMART_PG_PORT=5434` (or another free port) in `.env`, then `docker compose up -d` |
| Each DB connection takes ~5 s | `DRUKSMART_PG_HOST=localhost` tries IPv6 first on Windows | Use `DRUKSMART_PG_HOST=127.0.0.1` (the default in `.env.example`) |
| `password authentication failed` after editing `.env` | Init script only runs on an empty volume | Re-apply: `docker compose exec postgres bash /docker-entrypoint-initdb.d/01_init_databases_roles_schemas.sh` |
| `CONFIG ERROR: Missing required settings` | `.env` missing or incomplete | Re-create from `.env.example` (§4) |
| `docker pull` timeouts | Slow or unstable network | Re-run the command; the pull resumes |
| `pip install ".[warehouse]"` hangs on `dbt_core_experimental_parser…whl` | Slow network, pip cannot resume | `curl -L -C - --retry 30 -o <dir>\<wheel name> <url from pip log>`, then `pip install --find-links <dir> -e ".[dev,warehouse]"` |
| pip tries to *build* `dbt-core-experimental-parser` | A newer, source-only release was chosen | Use the pinned `pyproject.toml` (2.0.0a4 has a Windows wheel) |
| Machine slow once more containers run | Docker Desktop Kubernetes or other projects' containers running | Disable *Settings → Kubernetes* and stop unused containers in Docker Desktop |
