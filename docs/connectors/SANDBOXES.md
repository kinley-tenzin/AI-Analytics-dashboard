# Local ERP sandboxes (Odoo 19, ERPNext 16)

The sandboxes are **local test ERPs holding synthetic data only**. They let the team develop and
test connectors without DrukSmart's systems. They are not part of the platform.

| Sandbox | Compose project | URL | Images | RAM (approx.) |
|---------|-----------------|-----|--------|---------------|
| Odoo 19 Community | `druksmart-odoo-sandbox` | http://127.0.0.1:8069 | `odoo:19.0`, `postgres:17.11-bookworm` | ~0.8 GB |
| ERPNext 16 + Frappe HR 16 | `druksmart-erpnext-sandbox` | http://127.0.0.1:8090 | `frappe/erpnext:v16.52.0`, `mariadb:11.8`, `redis:6.2-alpine` | ~2 GB |

Disk: the images are about 8.5 GB together (`frappe/erpnext` 4.5 GB, `odoo` 3.3 GB). Keep at least
10 GB free before the first start.

## Why a helper script?

`.env` sets `COMPOSE_PROJECT_NAME=druksmart` for the platform. If a sandbox were started with
`--env-file .env` but without `-p`, it would **join the platform's project**, and a later
`down --remove-orphans` could delete the warehouse database (this nearly happened in Milestone 3).
`infrastructure/sandboxes/sandbox.py` always passes an explicit `-p <sandbox project>`.

## Step by step (Windows, repo root, `.venv` active, Docker Desktop running)

1. Add the sandbox settings to your `.env` (random passwords, never printed):
   ```powershell
   python infrastructure\scripts\create_local_env.py --add-missing
   ```
2. Start Odoo (the first start creates the database with HR, Time Off and Invoicing; ~2 minutes):
   ```powershell
   python infrastructure\sandboxes\sandbox.py up odoo
   ```
   Expected: `druksmart-odoo-sandbox-odoo-1 ... Started`.
   Check: http://127.0.0.1:8069/web/version shows `"version": "19.0-…"`.
3. Seed synthetic data and create the read-only bot user:
   ```powershell
   python infrastructure\sandboxes\sandbox.py seed odoo
   ```
   Expected: `employees: 10 · leaves: 6 · invoices: 11 payments: 4 · SEED COMPLETE ·
   ODOO_API_KEY written to .env (not displayed).`
4. Start ERPNext (site creation takes ~3–5 minutes):
   ```powershell
   python infrastructure\sandboxes\sandbox.py up erpnext
   docker logs -f druksmart-erpnext-sandbox-create-site-1     # wait for "Current Site set to frontend"
   ```
5. Install the Frappe HR app (needed for Leave Application). The `frappe/erpnext` image does not include it:
   ```powershell
   docker exec druksmart-erpnext-sandbox-backend-1 bash -c "cd /home/frappe/frappe-bench && git clone --depth 1 --branch version-16 https://github.com/frappe/hrms apps/hrms && uv pip install --python env/bin/python -e apps/hrms && (grep -qx hrms sites/apps.txt || echo hrms >> sites/apps.txt) && bench --site frontend install-app hrms"
   docker cp druksmart-erpnext-sandbox-backend-1:/home/frappe/frappe-bench/apps/hrms $env:TEMP\hrms
   docker cp $env:TEMP\hrms druksmart-erpnext-sandbox-queue-short-1:/home/frappe/frappe-bench/apps/hrms
   docker exec druksmart-erpnext-sandbox-queue-short-1 bash -c "cd /home/frappe/frappe-bench && uv pip install --python env/bin/python -e apps/hrms"
   docker restart druksmart-erpnext-sandbox-backend-1 druksmart-erpnext-sandbox-queue-short-1
   ```
   Expected: `Thank you for installing Frappe HR!`. If `git clone` fails on a slow network, re-run it.
   **Note:** HRMS lives in the containers' file systems. Recreating those containers (not just
   restarting them) removes it; repeat this step afterwards.
6. Seed ERPNext (setup wizard, synthetic data, read-only role and user):
   ```powershell
   python infrastructure\sandboxes\sandbox.py seed erpnext
   ```
   Expected: `employees: 9 · leave applications: 6 · sales invoices: 8 ... · SEED COMPLETE`.
7. Verify both sandboxes from the platform side:
   ```powershell
   python -m ingestion check --source odoo
   python -m ingestion check --source erpnext
   pytest -m live -v
   ```

## Everyday use

| Task | Command |
|------|---------|
| Status | `python infrastructure\sandboxes\sandbox.py status` |
| Stop (keep data, free RAM) | `python infrastructure\sandboxes\sandbox.py stop` |
| Start again | `python infrastructure\sandboxes\sandbox.py up odoo` / `up erpnext` |
| **Delete a sandbox completely** | `python infrastructure\sandboxes\sandbox.py destroy odoo --yes` (asks for `--yes`) |
| Odoo admin UI | http://127.0.0.1:8069, user `admin`, password = `ODOO_SANDBOX_ADMIN_PASSWORD` in `.env` (set by `seed odoo`) |
| ERPNext admin UI | http://127.0.0.1:8090, user `Administrator`, password = `ERPNEXT_SANDBOX_ADMIN_PASSWORD` in `.env` |

Odoo API keys expire after at most 3 months. Re-run `seed odoo` to issue a new one.

## Users created by the seeds

| ERP | User | Rights | Read-only enforced by |
|-----|------|--------|-----------------------|
| Odoo | `druksmart_bot` | Employees Officer, Time Off Officer, Accounting Read-only | Connector whitelist (Odoo has no read-only HR group) + Odoo ACLs (verified: company and invoice writes refused) |
| ERPNext | `druksmart.readonly@example.com` | Role *DrukSmart Read Only*: read at permlevels 0 and 1 on the 10 contracted DocTypes | ERPNext role permissions (verified: create/update refused) + connector (GET only) |

## Sandbox simplifications (not ERP limitations)

* Odoo: branch-company invoices are booked on the head office (branch accounting not configured).
* ERPNext: leave types are *Leave Without Pay* (no allocations needed). Holidays come from one company-wide
  Holiday List Assignment (new in HRMS 16).
* ERPNext returns use the v16 default `update_outstanding_for_self = 1`.

## Restoring your other coursework clusters

Milestone 3 **stopped** (not deleted) these containers to free memory: `minikube`,
`cte412-02230133-control-plane`, `cte412-02230133-worker`, `cte412-02230133-worker2`, `4it-control-plane`.
Bring them back with:

```powershell
python infrastructure\sandboxes\sandbox.py stop
docker start minikube cte412-02230133-control-plane cte412-02230133-worker cte412-02230133-worker2 4it-control-plane
```
