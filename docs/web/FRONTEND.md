# DrukSmart Analytics website: frontend guide

**Status after Milestone 10: working and tested.**
- **Architecture and decisions:** [WEB_APP_ARCHITECTURE.md](WEB_APP_ARCHITECTURE.md) (ADR-040…043).
- **Sign-in:** [AUTHENTICATION.md](AUTHENTICATION.md).
- **Embedded Superset:** [EMBEDDING.md](EMBEDDING.md).
- **End users:** [../USER_GUIDE.md](../USER_GUIDE.md).

## 1. How it fits together

```
Browser ── http://127.0.0.1:8000 ─────────────────────────────────────────────────────────
  /app/...                       React website (index.html + hashed JS/CSS/fonts)   backend/portal
  /api/v1/auth/...               session / login / logout                            backend/access
  /api/v1/portal/overview/       overview tiles (approved KPI functions)             backend/portal
  /api/v1/portal/dashboards/...  dashboard list, guest tokens for embedding           backend/portal
  /api/v1/portal/reports/...     report catalogue, preview, CSV                       backend/portal
  /api/v1/portal/assistant/      Ask AI suggestions and provider                      backend/portal
  /api/v1/portal/admin/...       status, dashboard visibility, users (administrator)  backend/portal
  /api/v1/ask/, /api/v1/kpis/    assistant and KPI API (Milestone 7, unchanged)       backend/assistant, kpi
  /, /assistant/                 redirect to /app/ and /app/ask (Decision 3)
Superset (127.0.0.1:8088, separate origin) is embedded in an iframe with a guest token.
```

- **One origin.** The website and its API share 127.0.0.1:8000.
  - The HttpOnly session cookie goes with every API call, and every POST, PATCH or DELETE carries Django's CSRF token (`X-CSRFToken`).
  - No tokens are kept in the browser and no CORS is needed.
- **Security headers on the app page:**
  - a strict Content-Security-Policy: own scripts, styles, fonts and API only; `frame-src` = Superset only; `frame-ancestors 'none'`;
  - `X-Frame-Options: DENY`; `index.html` is not cached; hashed assets are cached for a year.
- **The Superset iframe is a different origin.** It never gets the Django session; it works with a guest token that Django mints per user and dashboard (EMBEDDING.md).

## 2. Pages

| Page | What it shows | Data from |
|---|---|---|
| Sign in (`/app/login`) | Branded form; generic errors; lock-out message; "session ended" notice | `/api/v1/auth/` |
| Overview (`/app/`) | HR tiles (active employees, departments, approved leave), department chart; Accounts tiles (receivables, payables, overdue per ledger and currency), ageing charts; reporting date, refresh age, stale/synthetic/branch labels | `/api/v1/portal/overview/` = 7 registry functions under the user's scope |
| HR / Accounts Analytics | The module's visible dashboards (tabs if several), embedded Superset with filters, cross-filtering, Drill by, View as table and downloads. The module's manager also gets "Edit in Superset (separate sign-in)" and "Manage dashboards" | Superset via guest token |
| Ask AI | Conversation (kept for the session), suggested questions of the user's modules, status per answer, chart and table of the result, "Explore in … Analytics" link, provider disclosure | `/api/v1/ask/` (Milestone 7 pipeline) |
| Reports | 9 downloadable reports of the user's modules: date or period, preview (chart and table), CSV download | `/api/v1/portal/reports/` = registry functions |
| Manage dashboards (HR / Accounts Manager: own module; administrator: both) | Publish a dashboard built in Superset (module check), show/hide, remove; link to Superset | `/api/v1/portal/manage/dashboards/` (ADR-044) |
| Administration (administrator) | Platform status; users with roles, modules and branches; link to Django admin and to Manage dashboards | `/api/v1/portal/admin/` |

**Access in the interface** comes from Django's scope:
- **Overview:** every signed-in user (with an explanation when they have no module).
- **HR / Accounts:** users with that module.
- **Ask AI and Reports:** users with at least one module.
- **Administration:** the Django superuser.

This is presentation only. Every API call is authorised again by Django, and every embedded chart by Superset with the guest token.

## 3. Source layout

| Path | Purpose |
|---|---|
| `src/main.tsx`, `src/routes.tsx` | Entry point; route table (basename `/app`) |
| `src/navigation.ts` | **Single list of pages** (path, label, description, icon, access rule) for the sidebar, routes and headers |
| `src/api/client.ts` | Same-origin fetch: session cookie, CSRF header, JSON error contract (`ApiError`), session-expiry event |
| `src/api/endpoints.ts`, `types.ts` | Typed calls and response types for every endpoint above |
| `src/auth/` | `SessionProvider` (sign-in, sign-out, expiry), `access.ts` (page access, safe `next`), guards |
| `src/components/layout/` | App shell (sidebar, top bar, mobile drawer), page header, brand mark |
| `src/components/ui/` | Buttons, card, badge, loading/empty/error states |
| `src/components/data/` | `BarChart` (single-series bars, values at tips, table view, negative values), `StatTile`, `DataStatus` (as-of, refresh age, stale/synthetic/branch), `ResultView` (KPI result as table and chart) |
| `src/components/dashboard/EmbeddedDashboard.tsx` | Superset Embedded SDK: guest token from Django, renewal, iframe sizing, error states |
| `src/lib/` | `format.ts` (presentation-only formatting; ageing prefix), `useApi.ts` (load/reload/abort), `conversation.tsx` (Ask AI conversation for the session) |
| `src/pages/` | One file per page (+ tests) |
| `src/styles/` | `tokens.css` (design tokens), `base.css`, `layout.css`, `components.css` |
| `scripts/browser_check.py` | Edge end-to-end check of the whole website (§6) |

## 4. Design system

- **Brand and type:**
  - navy (`--brand-800`) with a saffron accent; Inter Variable, self-hosted.
  - All colours, spacing, radii and shadows are tokens in `src/styles/tokens.css`.
- **Charts** follow the dataviz method:
  - one series per chart in one validated hue (`--brand-600`, which passes the palette validator's lightness, chroma and ≥ 3:1 contrast checks), so no legend is needed;
  - values at the bar tips, hover highlight, and a **table view** for every chart;
  - amounts in different currencies are never on one scale or added together;
  - negative balances (unapplied credit) extend left of a zero line.
- **States:** every data view has loading, empty and error states with retry. Stale and synthetic data are always labelled.
- **Layout:**
  - **≥ 1024 px:** fixed sidebar.
  - **< 1024 px:** drawer navigation.
  - **< 640 px:** compact header.
  - Wide tables scroll inside their box; there is no horizontal page scrolling (tested at 375, 820 and 1440 px).
- **Accessibility** (axe-core WCAG 2.1 A/AA audit of every page: no violations):
  - skip link, landmarks, `aria-current`, labelled controls, visible focus, 44 px targets;
  - charts with a text summary and a table, `role="log"` for the conversation;
  - the visible text is part of every control's accessible name.
  - The Superset iframe content is Superset's own interface and is not part of the audit.

## 5. Development

```powershell
cd C:\Users\ASUS\FYP\frontend
npm ci                  # exact versions from package-lock.json (Node 24 LTS)
npm run dev             # http://127.0.0.1:5173/app/ (API forwarded to Django on :8000)
npm run verify          # tsc + eslint + vitest (also a regression stage)
npm run build           # into frontend/dist (used by a host-run Django)
```

- **Versions:** all packages are pinned exactly (`.npmrc` `save-exact`).
  - TypeScript 6.0.x: typescript-eslint 8.71 supports TypeScript < 6.1.
  - jsdom 29: jsdom 30 needs Node ≥ 24.15.
  - Embedded SDK `@superset-ui/embedded-sdk` 0.4.0; axe-core 4.14.0 for the audit only.
- **Docker:** the running backend serves the build **inside its image** (`/opt/druksmart-frontend`). After frontend changes, run `docker compose --profile backend build backend` and then `python deploy/druksmart.py up`.

## 6. Tests

| Check | Command | Result (2026-10-25) |
|---|---|---|
| Type check, lint, unit/page tests | `npm run verify` | clean; **97/97** Vitest tests |
| Django API for the website | `pytest tests/backend` | **236 passed** (portal serving, auth, overview, embedding, reports, admin, assistant info) |
| Live Superset embedding and authoring | `pytest -m superset` | **58 passed** (incl. 10 embedding and 4 authoring tests) |
| Whole website in Edge | `python frontend/scripts/browser_check.py` | **161/161**: roles and navigation, sign-in/out, embedded values = KPI service per user (4 roles), Ask AI, Reports, Administration, axe audit of 8 pages (sign-in, overview, HR, Accounts, Ask AI, Reports, not-found, Administration), the 12-step journey for an executive and a branch manager, layouts at three widths |
| Platform regression | `python evaluation/run_regression.py` | **14/14 stages** (new: `frontend`, `website_browser`) |

Evidence: `docs/web/results/task_10_*_browser.json` and `docs/web/screenshots/task-10.*/`.
