# warehouse/: dbt project and analytical models

**Owner:** Member 2 (data engineering) · **Status:** working (Milestone 4)

dbt Core 1.12.0 + dbt-postgres 1.11.0 (Kimball star schemas) on `druksmart_analytics`.

| Path | Contents |
|------|----------|
| `dbt_project.yml`, `profiles/profiles.yml` | Project and connection profile (`dev`, `test`); credentials only via `env_var()` |
| `run_dbt.py` | Runs dbt with `.env` loaded: `python warehouse/run_dbt.py build [--target test]` |
| `scripts/generate_seeds.py` | Renders mapping seeds from `contracts/` (never edit `seeds/*.csv` by hand) |
| `models/staging/` | `stg_<erp>__<entity>`: one view per source entity, every record version |
| `models/intermediate/` | `int_*`: cross-ERP canonical models (organisation, departments, employees, leave, partners, documents, payments, snapshot dates) |
| `models/marts/core|hr|accounts/` | `dim_*` and `fct_*` star schemas (grains documented in `_marts.yml`) |
| `models/marts/kpi/` | `kpi_*` views: governed KPI datasets for Superset and AI |
| `tests/` | Reconciliation and consistency tests |
| `macros/` | Raw JSON helpers, schema naming, `unique_combination` test |

Full documentation: [docs/warehouse/WAREHOUSE.md](../docs/warehouse/WAREHOUSE.md).
End-to-end KPI check: `pytest -m warehouse -v`.
