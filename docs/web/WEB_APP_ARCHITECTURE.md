# Unified DrukSmart web application: audit and integration architecture (Task 10.1)

Status: **APPROVED** by the team (2026-10-25, ADR-040), with decisions 1–3 as recommended. Implementation
progress: **all tasks 10.1–10.9 done** (2026-10-25). The implemented system follows this design;
details in [FRONTEND.md](FRONTEND.md), [AUTHENTICATION.md](AUTHENTICATION.md), [EMBEDDING.md](EMBEDDING.md)
and ADR-040…043. Differences from the plan below:
- **Export:** Superset's own chart downloads (CSV/Excel/image) work in embedded mode, and the Reports page adds 9 registry reports.
- **Drill to detail** is not offered (no role has `can_samples`); **Drill by** is.
- **Templates:** creators build new dashboards; they cannot copy the official templates (Superset `DASHBOARD_RBAC` owner rule).

**Proposal review (2026-10-25, `docs/reference/Group8_DrukSmart.pdf`).** The proposal SUPPORTS this design, with no conflict:
- **Aim:** "a single, user-friendly interface"; Objective 7 / FR1–FR2: secure authentication and role-based access.
- **§4.A.4:** log in, then modules by role and organisation scope; Superset enforces dashboard data, Django enforces AI requests, "neither system may bypass" the other.
- **Scope 3, §4.A.3:** a "low overhead embed option for consumption interface"; "signed access and access control for embedded dashboards will be set up and tested separately"; Django does not proxy Superset chart queries.
- **Lit. review:** "Django backend and react dashboard".
- **Ask AI (§4.A.3b):** results as text, charts or tables.

Carried forward:
- **Task 10.7:** distinguish **official dashboard templates** from **customer-created dashboards**.
- **Out of the minimum prototype:** in-app notifications and forecasting.

## 1. Audit of what exists (inspected 2026-10-25)

| Component | State | Reuse in the web app |
|---|---|---|
| PostgreSQL warehouse, dbt (43 models, 164 tests), Airflow build–test–swap publication | Working, healthy | Unchanged. Every number in the web app still comes from published `marts` |
| Superset 6.1.0 (`druksmart/superset:6.1.0`, 127.0.0.1:8088): HR and Accounts dashboards, certified metrics, native filters, 5 roles, branch RLS, configuration as code (`superset/definitions/`, `bootstrap.py`) | Working | **The BI engine of the web app**, embedded. Dashboards, charts, filters, drill-down and export stay Superset's |
| Superset embedding support (checked inside the container) | **Off.** `EMBEDDED_SUPERSET` is `False`; guest role is the default `Public`; guest token lifetime 300 s; `POST /api/v1/security/guest_token/` exists, with per-dataset RLS clauses in the token | Must be enabled and configured (Task 10.5) |
| Django 5.2.18 backend (gunicorn, 127.0.0.1:8000): KPI registry (8 functions), `KpiService` with stale/synthetic flags, `scope_for()` (roles → domains → branch keys), `/api/v1/me/`, `/api/v1/kpis/`, `/api/v1/kpis/run/`, `/api/v1/ask/`, health endpoints, Django admin | Working, 128 tests | **The web app's backend and identity provider.** Existing APIs reused as they are; new endpoints only for the gaps |
| Existing frontend | One server-rendered Django page (`assistant/home.html`, ~285 lines of template/JS/CSS) and the stock Django login | Too small to extend into a multi-page product. Replaced by the new web app; the old page is kept until Task 10.9 |
| Authentication | **Two separate account systems:** Django users (KPI assistant) and Superset users (dashboards); roles kept in sync by tests, no single sign-on | Django becomes the single login for the web app (see §4) |
| Tooling on this machine | Node 24.14.0, npm 11.9.0, npm registry reachable; `@superset-ui/embedded-sdk` 0.4.0 (2026-06-18) | React + TypeScript build is feasible |
| Proposal PDF | Still missing from `docs/reference/` | Requirements taken from the Milestone 10 brief |

**Missing for a unified website:** a multi-page frontend; a branded login and session API for it; guest-token
minting; embedding configuration in Superset; dashboard metadata and visibility; an overview built from KPIs;
a reports page; an administration/status page; end-to-end tests of the whole journey.

## 2. Recommended architecture

```
Browser ── http://127.0.0.1:8000 (ONE origin, ONE login) ─────────────────────────────
│  React + TypeScript single-page app (built by Vite, served by Django)
│   Login · Overview · HR Analytics · Accounts Analytics · Ask AI · Reports · Admin
│        │ fetch /api/v1/* (Django session cookie + CSRF)
│        │ Superset Embedded SDK → <iframe src="http://127.0.0.1:8088/embedded/<uuid>">
▼        ▼
Django (gunicorn, Compose service "backend")                 Superset 6.1.0 (embedded mode)
 ├ auth API: login / logout / me (session)                    ├ dashboards render with a GUEST TOKEN
 ├ KPI API (existing registry + KpiService)  ─┐               │  (resource = one dashboard,
 ├ Ask AI API (existing assistant pipeline)   ├─ kpi_reader   │   RLS clauses added by Django)
 ├ portal API: dashboards, guest token,       │               └ queries as superset_reader
 │   status, reports, admin                    │                        │
 └ server-to-server: Superset service account ─┼── http://superset:8088 │
                                               ▼                        ▼
                                  PostgreSQL warehouse: published marts (approved datasets only)
Superset native UI (127.0.0.1:8088) remains ONLY for authoring (since ADR-044: the HR and Accounts Managers) and Admins.
```

### 2.1 Frontend: React + TypeScript (Vite), new top-level `frontend/`
- **Why not extend the Django templates:** the brief needs seven pages, conversation state, embedded
  dashboards with token renewal, charts and responsive layouts. A component-based SPA is easier to maintain
  and test. The Embedded SDK is an npm package designed for this use.
- **Served by Django on the same origin** (127.0.0.1:8000): it uses the existing session and CSRF protection,
  needs no CORS configuration, and adds no extra container. In development, the Vite dev server proxies
  `/api` to Django.
- **Libraries (pinned):**
  - React 19 and React Router;
  - `@superset-ui/embedded-sdk` 0.4.0;
  - Apache ECharts, the chart library Superset itself uses, so the overview charts look like the dashboards;
  - Vitest and Testing Library for tests.
  - No UI kit: a small design system of our own (tokens, layout, cards, tables), which avoids the
    generic-admin-template look.
- **Build:** a multi-stage `backend/docker/Dockerfile`. A pinned Node image runs `npm ci && npm run build`
  from `package-lock.json`, and the output is copied into the backend image. A host build is documented as
  a fallback if the network fails.

### 2.2 One login: Django is the identity for the web app
- The branded React login page posts to a new JSON login endpoint, which creates a Django session (HttpOnly
  cookie). The navigation comes from `/api/v1/me/`, which already returns roles and domains.
- **Superset's own login is NOT used for viewing.** Django decides which dashboards a user may see, then
  asks Superset for a short-lived guest token **for that dashboard only**.
- **Permissions stay enforced by the systems that query data.** Django enforces them for the KPI, AI and
  token APIs; Superset enforces the token (dashboard resource plus RLS) and the guest role's dataset
  permissions. Hiding a menu item is cosmetic only, and tests cover the API checks.

### 2.3 Secure Superset embedding (Task 10.5)

| Item | Design |
|---|---|
| Feature | `EMBEDDED_SUPERSET: True` in `superset_config.py`; each dashboard gets an embedded configuration created by `bootstrap.py`, with allowed domains `http://127.0.0.1:8000` |
| Service account | New Superset user `druksmart_portal_service`, role **DrukSmart Portal Service** with only `can_grant_guest_token` plus read access to dashboard metadata. Its password is generated into `.env` by `create_local_env.py` and given **only** to the backend container. Never sent to the browser |
| Guest role | `GUEST_ROLE_NAME = "DrukSmart Embedded Guest"`: viewer base, approved datasets only (no SQL Lab, no Explore editing). Bootstrap sets its permissions exactly, like the other roles |
| Token minting | `POST /api/v1/portal/dashboards/<key>/guest-token/` (Django, login required). It (1) checks the user's scope allows the dashboard's domain, (2) adds RLS for branch managers, (3) calls Superset server-to-server and (4) returns only the token |
| Branch RLS | **Important finding:** Superset role-based RLS does **not** apply to guest users. Django therefore puts `branch_key IN (...)` clauses into the token, for the branch-filtered datasets listed in `access.yml`. Keys come from the user's `BranchScope` rows (validated format), never from request text. A branch manager without branches gets no token |
| Expiry/renewal | Token lifetime 5 min; the SDK calls `fetchGuestToken` again before expiry. A Django logout stops renewal, so the embedded view stops working within 5 min |
| Framing/CSP | Superset's Talisman CSP gets `frame-ancestors http://127.0.0.1:8000`; Django keeps `X-Frame-Options: DENY` (it is the parent, never framed) |
| Cookies/CORS | Guest tokens travel in a header, not cookies. Both origins are 127.0.0.1 (same site), so a Lax session cookie is unaffected. The SPA never calls Superset's API directly, so no CORS is needed |
| Export | Embedded chart menus ("Download as CSV/image") depend on guest-role permissions. **To be verified in 10.5**; if a download is not supported in embedded mode, the Reports page provides it (§2.5) |

### 2.4 Pages

| Page | Data source | Notes |
|---|---|---|
| Login | Django auth API | Branded; errors without revealing whether a user exists |
| Overview | Existing KPI registry via a new `/api/v1/portal/overview/` endpoint that runs registry functions for the user's domains | Headcount, by department, AR, AP, overdue, ageing; ECharts; reporting date, publication age, stale and synthetic badges. No business rules in the frontend |
| HR Analytics / Accounts Analytics | Embedded Superset dashboards | Inside the app's layout; Superset filters, cross-filter and drill-down. Shown only for permitted domains |
| Ask AI | Existing `/api/v1/ask/` | Conversation view, suggestions from the registry examples, loading/error states, result tables and small charts, "Open in dashboard" links by domain |
| Reports | Registry functions as CSV downloads (`/api/v1/portal/reports/<function>.csv`), plus embedded-dashboard exports if supported | Same scope checks and branch filtering; no new report engine |
| Admin (Administrator only) | Django admin for users/roles (existing), plus a status page showing services, last publication, dashboard visibility | Dashboard visibility = a small Django model (`PortalDashboard`: Superset dashboard, domain, visible) |

### 2.5 Dashboard creation and editing: evaluation

| Option | Assessment |
|---|---|
| **1. Embedded viewing + native Superset authoring for creators** | **Recommended.** Uses Superset's tested editor; matches CLAUDE.md §2 ("do not build a custom dashboard designer"). A Dashboard Creator sees an "Open editor" link that opens Superset in a new tab. Superset asks for a **separate login** there; this limitation is shown in the UI and documented. When an Admin registers a creator's new dashboard in the web app, Django checks that it only uses datasets of the chosen domain, then it can be embedded |
| 2. Custom builder using Superset REST APIs | **Rejected.** It would recreate Superset's chart editor (forms for every chart type, layout grid, filters) and conflicts with CLAUDE.md §2. Not feasible to make robust within the milestone |
| (Optional later) Single sign-on into Superset for creators (Django as an OIDC provider, Superset `AUTH_OAUTH`) | Removes the second login, but adds a dependency (django-oauth-toolkit) and auth complexity. Proposed as a later task only if the team wants it |

The web app will claim only what is tested: **viewing and filtering in the app; creating and editing in Superset's native editor.**

## 3. Task plan

| Task | Delivers | Verification |
|---|---|---|
| 10.2 Frontend and navigation | `frontend/` (Vite, React, TS), design tokens, app shell, routing, role-aware navigation, Django serving the build | `tsc`, ESLint, Vitest; served at :8000 |
| 10.3 Authentication | JSON login/logout/session/CSRF endpoints, login page, route guards | pytest (sessions, CSRF, inactive users); Vitest |
| 10.4 Overview, HR, Accounts pages | Overview endpoint and charts; analytics page frames | Values equal the warehouse (existing reconciliation) |
| 10.5 Superset embedding | Feature flag, CSP, guest role, service account, embedded configurations, token endpoint, branch RLS | pytest with mocked and live Superset; browser checks per role, including an HR user denied an Accounts token and branch manager values |
| 10.6 Ask AI | Conversation UI on `/api/v1/ask/`, result tables and charts, dashboard links | Existing 128 backend tests plus UI tests; evaluation set unchanged |
| 10.7 Reports and dashboard management | CSV report downloads, `PortalDashboard` visibility, admin/status page, creator editor link | pytest scope tests; creator workflow tested manually and documented |
| 10.8 Polish | Responsive 360/768/1280 px, accessibility (keyboard, contrast, labels), empty/error/loading states | Playwright screenshots, axe checks |
| 10.9 Integration test | Full 12-step journey for each role; deployment through `deploy/druksmart.py`; docs, ADRs | Playwright journey added to `run_regression.py`; regression must stay 12/12 plus the new stage |

## 4. What does not change
- The warehouse, dbt, Airflow and publication; the KPI registry and AI pipeline (only called from the new UI).
- Superset's dashboards and native UI (embedding is added, not replaced).
- Existing endpoints and tests. The old assistant page stays until 10.9, then redirects to the new app.
- Security rules: `.env` secrets only server-side, no SQL from users, ERPs never written.
