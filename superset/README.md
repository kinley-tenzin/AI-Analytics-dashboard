# superset/: Apache Superset BI configuration and dashboard assets

**Owner:** Member 3 (BI dashboards and reporting) · **Status:** working (Milestone 6). Full guide:
[docs/bi/SUPERSET.md](../docs/bi/SUPERSET.md)

| Path | What | Edit when |
|---|---|---|
| `approved_datasets.yml` | The ONLY warehouse relations Superset's DB account may read (granted at every publication) | A new KPI dataset is approved |
| `definitions/datasets.yml` | Labels, date/filter columns, **certified metrics** (re-aggregations of dbt KPI columns) | A metric or label changes |
| `definitions/access.yml` | Roles, permission bases, dataset domains, row-level security, demo users | Roles or branch restrictions change |
| `definitions/dashboards.py` | Default HR and Accounts dashboard templates (charts, layout, native filters) | Templates change |
| `definitions/access.yml` → `embedding` | Embedding in the website (Milestone 10): guest role, portal service account, branch-neutral datasets ([docs/web/EMBEDDING.md](../docs/web/EMBEDDING.md)) | Embedding rules change |
| `assets/dashboards/` | Exported dashboards/charts/datasets (Superset's native YAML format), committed | After every change: `assets.py export` |
| `docker/` | Image (`apache/superset:6.1.0` + PostgreSQL driver) and `superset_config.py` | Upgrades, config |
| `scripts/bootstrap.py` | Applies `definitions/` to a running Superset (idempotent) | |
| `scripts/assets.py` | `export` / `import` the version-controlled assets | |
| `scripts/browser_check.py` | Headless-Edge check: dashboards per role + KPI cards = warehouse | |

```powershell
docker compose --profile superset up -d --build --wait
python superset\scripts\bootstrap.py
python superset\scripts\assets.py export      # then commit superset/assets/
pytest -m superset -v                         # access boundary + KPI correctness (API)
python superset\scripts\browser_check.py      # needs: pip install -e ".[bi-test]"
```

Rules:
- Dashboards are authored with Superset's own editor; no custom designer exists.
- Charts use only the certified metrics.
- Superset never reads raw, staging or employee-level data.
- Its database account is read-only and limited to `approved_datasets.yml`.
