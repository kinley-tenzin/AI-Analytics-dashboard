# frontend/: DrukSmart Analytics web application

React 19 + TypeScript (Vite) single-page application that is **the** DrukSmart website: Overview,
HR Analytics, Accounts Analytics, Ask AI, Reports and Administration. Django serves the built app at
**http://127.0.0.1:8000/app/** on the same origin as its API, so the app uses Django's session and
CSRF protection. Owners: Member 3 (BI pages) and Member 4 (backend integration, Ask AI).

```powershell
cd frontend
npm ci              # exact versions from package-lock.json
npm run dev         # http://127.0.0.1:5173/app/ (forwards /api and /accounts to Django on :8000)
npm test            # Vitest unit and routing tests
npm run lint        # ESLint
npm run build       # type-check + production build into frontend/dist
```

Full guide (structure, design system, integration points, testing, deployment):
[docs/web/FRONTEND.md](../docs/web/FRONTEND.md).
