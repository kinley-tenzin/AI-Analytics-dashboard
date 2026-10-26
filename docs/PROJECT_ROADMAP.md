# Project Roadmap

Milestones are delivered **one at a time**. Each one ends with tests, documentation updates and an
end-of-milestone report, then waits for approval (see `CLAUDE.md` §5 and §9). A milestone is complete
only when its acceptance criteria are met, or it is explicitly documented as blocked.

The order follows the proposal's advice to build a small vertical slice first (one ERP, HR, one
dashboard), then widen it. Milestone 2 was redefined by the team on 2026-10-22 (data analysis and
contracts before sandboxes), and later milestones were renumbered.

| # | Milestone | Main owner(s) | Key acceptance criteria | Status |
|---|-----------|---------------|-------------------------|--------|
| 1 | **Engineering foundation**: repo structure, PostgreSQL, config, docs, smoke tests | all | PostgreSQL healthy; DB + 4 schemas exist; secrets not in Git; smoke tests pass; setup reproducible | ✅ complete |
| 2 | **ERP data analysis & contracts**: source analysis, extraction contracts, canonical models, KPI catalogue, synthetic fixtures, contract/fixture tests | M1, M2 | Both ERP structures documented; KPI source fields identified; explicit testable mappings; edge-case fixtures; independently calculable expected KPIs | ✅ complete |
| 3 | **ERP integration framework**: connector interface, Odoo + ERPNext adapters, raw ingestion (idempotent, versioned), incremental extraction, retries/recovery, CLI; local sandboxes + live read-only tests | M1, M2 | Both adapters implement the interface; HR + Accounts extraction; raw preserves source records; repeatable without duplication; failure/pagination tests pass; live connectivity verified or marked pending | ✅ complete (live = local sandboxes) |
| 4 | *(merged into 3: sandboxes and contract-assumption verification)* | | | |
| 5 | *(merged into 3)* | | | |
| 4 *(was 6–8)* | **Dimensional warehouse + dbt**: staging, intermediate integration, Kimball marts (HR + Accounts), KPI datasets, data tests, reconciliation | M2 | dbt builds with all tests passing; marts reproduce every figure in `expected_kpis.json` at both snapshot dates; documented grains | ✅ complete |
| 6 | *(merged into 4)* | | | |
| 7 | *(merged into 4)* | | | |
| 8 | *(merged into 4)* | | | |
| 5 *(was 9)* | **Airflow orchestration** | M2 | Scheduled DAG: extract → load → dbt build/test → publish; failures visible and retryable; recovery and idempotency demonstrated | ✅ complete |
| 6 *(was 10)* | **Superset**: approved datasets with governed metrics, roles, row-level security, HR + Accounts dashboards, export/restore | M3 | Role/branch restrictions verified for view, SQL Lab and export; KPIs equal the warehouse; templates; native authoring; restorable assets | ✅ complete |
| 7 *(was 11–12)* | **Django backend + bounded AI**: auth, roles/scope, approved KPI function registry, NL questions (rules + Gemini function calling), UI, evaluation | M4 | KPI functions equal Superset; scope enforced before execution; no SQL generation; unsupported handled; answers validated against independent expected values | ✅ complete (Gemini not verified live) |
| 8 *(was 13)* | **System integration & evaluation**: integration assessment, end-to-end on sandboxes, cross-layer reconciliation, reliability, access, performance, usability protocol, regression suite | all | E2E demonstrated; KPIs verified against independent references; recovery and access tested; measured performance; reproducible suite + report | ✅ complete (no usability participants yet) |
| 9 *(was 14)* | **Deployment, documentation & handover** | all | Reproducible Compose deployment (clean-start tested), backup/restore tested, technical/user docs, demo script with synthetic fallback, handover report | ✅ complete (pending review) |
| opt | Forecasting (TimesFM) and advanced notifications | M4 | Only after 1–14; compared against simple baselines | ⬜ |

Business decisions DS-HR-01 … DS-SEC-01 (see `docs/data/KPI_CATALOGUE.md`) should be confirmed
with DrukSmart before Milestones 7–8 build the marts.
