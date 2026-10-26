# backend/: Django KPI service and bounded AI assistant

**Owner:** Member 4 (Django backend, AI and system integration) · **Status:** working (Milestone 7),
with the Gemini provider implemented but not yet verified live. Full guide:
[docs/backend/BACKEND.md](../docs/backend/BACKEND.md) · Evaluation: [docs/backend/EVALUATION.md](../docs/backend/EVALUATION.md)

| Path | What |
|---|---|
| `druksmart_backend/` | Settings (all from `.env`), URLs, WSGI; `settings_test.py` for pytest |
| `access/` | Roles (Django groups named like the Superset roles), `BranchScope`, `scope_for(user)`; `seed_roles`, `seed_demo_users` commands |
| `portal/` | **The website (Milestone 10):** serves `frontend/` under `/app/`; website API `/api/v1/portal/` (overview, dashboards + Superset guest tokens, reports, assistant info, administration); `PortalDashboard` model. See docs/web/ |
| `access/auth_api.py`, `access/throttle.py` | Website sign-in API (`/api/v1/auth/`) and sign-in throttling |
| `kpi/registry.py` | **The allowlist** of KPI functions (module, parameters, filters, dataset, aggregates, output) |
| `kpi/service.py` | Validate → authorise → parameterised query on approved datasets |
| `kpi/warehouse.py` | Restricted, read-only warehouse connection (`DRUKSMART_KPI_READER_USER`) |
| `assistant/` | Rules + Gemini interpreters, pipeline, answer composer, UI page, `QuestionLog`, `evaluate_assistant` |
| `health/` | `/health/`, `/health/ready/` |
| `approved_datasets.yml` | Relations the KPI reader may SELECT (granted by `warehouse/publish.py`) |
| `evaluation/` | Evaluation questions (main + held-out) and independent reference queries |

Deployment: the Compose service `backend` (gunicorn, `docker compose --profile backend up -d`, or
`python deploy\druksmart.py up`). The development server below is for coding only. Port 8000
belongs to the container, so stop it first (`docker compose stop backend`) or use another port.

```powershell
python backend\manage.py migrate
python backend\manage.py seed_demo_users          # local testing only
python backend\manage.py runserver 127.0.0.1:8000 # http://127.0.0.1:8000/
pytest tests\backend -v                           # unit + API + warehouse + Superset consistency
python backend\manage.py evaluate_assistant --provider rules
```

Rules:
- The AI only *proposes* a registry function. The backend authorises, validates and executes it, and verifies every number before answering.
- No SQL from users or models.
- No individual employee records, pay, bank or identity data.
- Django never serves dashboards; Superset does.
