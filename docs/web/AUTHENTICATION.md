# Authentication and access in the DrukSmart website (Task 10.3)

**Status: working and tested** (pytest, Vitest, Edge on the live stack, live throttle check).

## 1. Model

- **One login for the website.** Users sign in once, with a DrukSmart (Django) account, on the website's own sign-in page at `/app/login`.
- **Credential.** A Django **session**: an HttpOnly, SameSite=Lax cookie, valid for 8 hours. The browser never receives a token or password, and page scripts cannot read the session cookie.
- **Permissions come from Django.** After sign-in the website receives the user's **scope** (roles, modules `hr`/`accounts`, and whether they are branch-restricted) from `access/scope.py`.
  - The menu is built from it, but menus are presentation only.
  - Every API call is authorised again by Django.
  - Embedded dashboards (Task 10.5) will be authorised by guest tokens that Django mints per user and per dashboard.
- **Roles** are Django groups with the same names as the Superset roles (`seed_roles`): HR Manager, Accounts Manager, Executive and Branch Manager (with assigned branches). A superuser is the Administrator.
  - A user without a role can sign in but sees no module.
  - An inactive user cannot sign in.
- **Prototype limitation (approved, ADR-040):** The HR and Accounts Managers build dashboards in Superset's native editor, which still has its **own Superset login**. Viewers never need it.

## 2. API (`backend/access/auth_api.py`, JSON, same origin)

| Endpoint | Method | Answer |
|---|---|---|
| `/api/v1/auth/session/` | GET | `200 {"authenticated": false, "user": null}` or `200 {"authenticated": true, "user": {scope}}`; also sets the CSRF cookie |
| `/api/v1/auth/login/` | POST `{"username", "password"}` + `X-CSRFToken` | `200` with the scope (new session id, new CSRF token) · `400 invalid_request` (missing fields) · `401 invalid_credentials` (the **same** message for a wrong password, an unknown user and an inactive account) · `429 throttled` with `Retry-After` · `403` without CSRF |
| `/api/v1/auth/logout/` | POST + `X-CSRFToken` | `200`; the session is deleted. Without CSRF: `403`, so a foreign page cannot sign the user out |

**Other sign-in paths:**
- The old sign-in page `/accounts/login/` still works, for the old assistant page until Task 10.9.
- `/admin/` keeps Django's admin login.
- Both use the same authentication backend, so throttling applies to them too.

## 3. Sign-in throttling (defect D6, fixed)

`access/throttle.py` (`ThrottledModelBackend`) works as follows:
- **Lock rule:** 5 failed sign-ins for one username within 15 minutes lock that username until enough failures age out. While it is locked, even the correct password is refused.
- **Storage:** failures are kept in the database (`access_loginfailure`: username, IP and time; never a password). All gunicorn workers therefore share the count. Old rows are pruned, and a successful sign-in clears the user's failures.
- **Per username, not per IP address.** Behind Docker's port mapping, all browsers arrive from the same gateway address, so an IP limit would lock out everyone.
  - Trade-off: someone who knows a username can lock it for 15 minutes.
  - An administrator can unlock it at once in Django admin, or with `manage.py shell` deleting that user's `LoginFailure` rows.

## 4. Website behaviour (`frontend/src/auth/`, `pages/LoginPage.tsx`)

- **Session check.** On load the website asks `/auth/session/`; a signed-out visitor is a normal state, not an error.
  - Opening a page while signed out leads to `/app/login?next=<page>`, and after sign-in back to that page.
  - `next` only accepts in-app paths (`safeNextPath`), which protects against open redirects.
- **The form:**
  - labelled fields with `autocomplete` (password managers work) and a show/hide password button;
  - empty fields are checked locally;
  - while submitting, the button reads "Signing in…" and the form is disabled;
  - on an error, the password is cleared and the backend's message is shown (generic, lock-out, server unreachable, expired CSRF).
- **Session expiry.** If any API call answers `401 unauthenticated` (timeout, or sign-out in another tab), the website returns to sign-in with "Your session has ended" and keeps the page to return to.
- **Sign-out** (top bar) calls the logout API, then shows the sign-in page. Pressing Back afterwards shows the sign-in page, not the previous content.

## 5. Tests

| Suite | What |
|---|---|
| `tests/backend/test_auth_api.py` (24) | Session states; HttpOnly/Lax cookie; session id rotation (no fixation); CSRF on login and logout; one generic answer for wrong, unknown and inactive; malformed bodies; user without role; logout ends API access; throttling: lock at 5, not at 4, success clears it, expiry, applies to `/accounts/login/` too, per username, no credentials stored, administrator unlock in admin |
| `frontend/src/auth/auth.test.tsx` (12) | Form posts JSON with CSRF and opens the requested page; generic error clears the password; lock-out message; empty-field validation; server unreachable; disabled while submitting; show/hide password; unsafe `next` ignored; sign-out through the API; session expiry returns to sign-in with the page kept; wrong password is not treated as expiry; header shows the user and branch restriction |
| `frontend/scripts/browser_check.py` (Edge) | Per demo role: redirect, sign-in with the form, HttpOnly cookie not readable by scripts, menus, denied pages, sign-out, Back after sign-out; wrong credentials with a throwaway username; layouts. Results: `docs/web/results/task_10_3_browser.json` |
| Live check (curl, running container) | Attempts 1–5 → 401, attempt 6 → 429 `Retry-After`; no CSRF → 403 |
