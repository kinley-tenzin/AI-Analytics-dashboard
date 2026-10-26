"""Real-browser check of the DrukSmart web application (Milestone 10), in Microsoft Edge.

For each demo role it signs in with the app's sign-in form, checks the HttpOnly session cookie,
the role-aware navigation, every page through the sidebar, that pages outside the role are
denied, that the browser reports no console errors (including Content-Security-Policy
violations) and that signing out ends the Django session (also after pressing Back). It checks
sign-in errors with a throwaway username (never locking a demo account), then the layout at
phone, tablet and desktop widths (no horizontal scrolling, working menu drawer), with screenshots.
Tasks 10.5-10.9 add: embedded dashboard values per user, the Ask AI / Reports / Administration
pages against the live backend, an axe-core accessibility audit (WCAG 2.1 A/AA) of every page and
the complete 12-step user journey of the brief for an executive and a branch manager.

The Administration page needs an administrator: the script creates a TEMPORARY Django superuser
in the backend container with a random password (never printed or stored) and deletes it again.

Usage (stack running, `pip install -e ".[bi-test]"`):
    python frontend/scripts/browser_check.py [--base http://127.0.0.1:8000] [--task 10.3]
Demo passwords are read from .env (BACKEND_DEMO_USER_PASSWORD) and never printed.
"""

from __future__ import annotations

import argparse
import contextlib
import csv
import io
import json
import os
import secrets
import subprocess
import sys
from datetime import UTC, datetime
from pathlib import Path

from dotenv import load_dotenv
from playwright.sync_api import Page, sync_playwright

REPO = Path(__file__).resolve().parents[2]
SHOTS = REPO / "docs" / "web" / "screenshots" / "task-10.9"  # set from --task in main()
RESULTS = REPO / "docs" / "web" / "results" / "task_10_9_browser.json"
AXE = REPO / "frontend" / "node_modules" / "axe-core" / "axe.min.js"
TEMP_ADMIN = "browser_check_admin"
ENV_FILE = REPO / ".env"  # --env-file: which Compose stack the temporary admin is created in
# A username that does not exist, new for every run: wrong-password checks never count against a
# demo account, and repeated runs never reach the sign-in throttle (5 failures in 15 minutes).
THROWAWAY_USER = f"browser_check_nobody_{secrets.token_hex(4)}"

ALL_PAGES = {
    "Overview": "/app/",
    "HR Analytics": "/app/hr",
    "Accounts Analytics": "/app/accounts",
    "Ask AI": "/app/ask",
    "Reports": "/app/reports",
    "Manage dashboards": "/app/manage",
    "Administration": "/app/admin",
}
# ADR-044: the HR / Accounts Managers also manage their module's dashboards.
ROLES = {
    "demo_hr": ["Overview", "HR Analytics", "Ask AI", "Reports", "Manage dashboards"],
    "demo_accounts": ["Overview", "Accounts Analytics", "Ask AI", "Reports", "Manage dashboards"],
    "demo_executive": ["Overview", "HR Analytics", "Accounts Analytics", "Ask AI", "Reports"],
    "demo_branch": ["Overview", "HR Analytics", "Accounts Analytics", "Ask AI", "Reports"],
}
VIEWPORTS = {"phone": (375, 812), "tablet": (820, 1180), "desktop": (1440, 900)}


class Check:
    def __init__(self) -> None:
        self.results: list[dict] = []

    def __call__(self, name: str, ok: bool, detail: str = "") -> bool:
        self.results.append({"check": name, "ok": bool(ok), "detail": detail})
        print(f"  [{'PASS' if ok else 'FAIL'}] {name}{f' ({detail})' if detail and not ok else ''}")
        return ok


# The only expected failing request: the explicit /api/v1/me/ probe after signing out.
EXPECTED_FAILURES = {
    (401, "/api/v1/me/"),  # explicit probes after signing out
    (401, "/api/v1/portal/overview/"),
    (404, "/static/service-worker.js"),
}
# Superset 6.1's image has no service-worker.js (also in native Superset; not caused by embedding).
KNOWN_SUPERSET_CONSOLE = (
    "service-worker.js",
    "ServiceWorker",
    "A bad HTTP response code (404) was received when fetching the script.",
)


def watch_console(page: Page, sink: list[str]) -> None:
    """Collect console errors (e.g. CSP violations), script errors and unexpected HTTP failures."""

    def on_console(message) -> None:
        # Browsers log every non-2xx response as "Failed to load resource"; those are judged
        # by URL in on_response instead.
        if message.type != "error" or message.text.startswith("Failed to load resource"):
            return
        # The website registers no service worker, so service-worker messages can only come from
        # the Superset iframe (whatever its port; the browser does not always attach the URL).
        if any(k in message.text for k in KNOWN_SUPERSET_CONSOLE):
            return
        sink.append(message.text)

    def on_response(response) -> None:
        path = "/" + response.url.split("/", 3)[-1].split("?")[0]
        if response.status >= 400 and (response.status, path) not in EXPECTED_FAILURES:
            sink.append(f"HTTP {response.status} {path}")

    page.on("console", on_console)
    page.on("pageerror", lambda e: sink.append(str(e)))
    page.on("response", on_response)


def sign_in(page: Page, base: str, username: str, password: str, start: str | None = None) -> None:
    """Use the app's own sign-in form (optionally opening `start` first)."""
    if start:
        page.goto(f"{base}{start}")
    page.get_by_label("Username").fill(username)
    page.get_by_label("Password", exact=True).fill(password)
    page.get_by_role("button", name="Sign in").click()


def at(page: Page, url: str) -> None:
    """Wait for a client-side (history API) navigation, which fires no load event."""
    # The router writes the overview as /app (no trailing slash); Django serves both forms.
    page.wait_for_function(
        r"u => location.href.replace(/\/$/, '') === u.replace(/\/$/, '')", arg=url, timeout=30_000
    )


def h1(page: Page) -> str:
    page.wait_for_selector("main h1", timeout=30_000)
    return page.locator("main h1").first.inner_text().strip()


def nav_labels(page: Page) -> list[str]:
    return [t.strip() for t in page.locator("nav[aria-label=Main] a").all_inner_texts()]


def check_role(browser, base: str, username: str, password: str, check: Check) -> None:
    print(f"- {username}")
    context = browser.new_context(viewport={"width": 1440, "height": 900})
    page = context.new_page()
    errors: list[str] = []
    watch_console(page, errors)

    expected = ROLES[username]
    start = "/app/hr" if "HR Analytics" in expected else "/app/accounts"
    page.goto(f"{base}{start}")
    page.wait_for_url("**/app/login?next=*")
    check(
        f"{username}: anonymous visit redirected to sign-in",
        "/app/login?next=" in page.url,
        page.url,
    )

    sign_in(page, base, username, password)
    page.wait_for_url(f"{base}{start}")
    check(
        f"{username}: returned to the requested page after sign-in",
        page.url == f"{base}{start}",
        page.url,
    )

    cookies = {c["name"]: c for c in context.cookies()}
    session = cookies.get("sessionid", {})
    check(
        f"{username}: session cookie is HttpOnly and SameSite=Lax",
        session.get("httpOnly") is True and session.get("sameSite") == "Lax",
        str({k: session.get(k) for k in ("httpOnly", "sameSite")}),
    )
    check(
        f"{username}: page scripts cannot read the session cookie",
        "sessionid" not in page.evaluate("document.cookie"),
    )

    page.goto(f"{base}/app/")
    check(f"{username}: overview heading", h1(page) == "Overview")
    labels = nav_labels(page)
    check(f"{username}: navigation shows exactly the role's pages", labels == expected, str(labels))

    for label in expected:
        page.locator("nav[aria-label=Main] a", has_text=label).click()
        at(page, f"{base}{ALL_PAGES[label]}")
        current = page.locator("nav[aria-label=Main] a[aria-current=page]").inner_text().strip()
        check(f"{username}: sidebar opens {label}", h1(page) == label and current == label)

    for label, path in ALL_PAGES.items():
        if label in expected:
            continue
        page.goto(f"{base}{path}")
        denied = page.get_by_role("heading", name="You do not have access to this page")
        denied.wait_for(timeout=10_000)
        check(f"{username}: {label} denied", denied.is_visible())

    if username == "demo_branch":
        check(
            f"{username}: branch restriction shown",
            "branch-restricted" in page.inner_text("header"),
        )

    me = page.evaluate("fetch('/api/v1/me/').then(r => r.json())")
    check(
        f"{username}: /api/v1/me/ matches the user", me.get("scope", {}).get("username") == username
    )

    page.get_by_role("button", name="Sign out").click()
    page.wait_for_url(f"{base}/app/login")
    status = page.evaluate("fetch('/api/v1/me/').then(r => r.status)")
    check(f"{username}: sign out ends the session", status == 401, f"me -> {status}")
    page.go_back()
    page.get_by_role("heading", name="Sign in").wait_for(timeout=10_000)
    check(
        f"{username}: Back after sign-out shows sign-in, not the page",
        page.locator("main").count() == 0,
    )

    check(f"{username}: no console errors (incl. CSP)", not errors, "; ".join(errors)[:300])
    context.close()


# Embedded dashboards (Task 10.5): big numbers inside the Superset iframe must equal the backend's
# KPI service figures for the SAME user (the KPI service is tested equal to the warehouse), which
# proves the guest token's RLS filters aggregated charts for branch-restricted users.
EMBED_ROLES = {
    "demo_executive": ["hr", "accounts"],
    "demo_branch": ["hr", "accounts"],
    "demo_hr": ["hr"],
    "demo_accounts": ["accounts"],
}
BIG_NUMBERS = {
    "hr": {"Active headcount": ("headcount", "active_headcount", None)},
    "accounts": {
        "Outstanding receivables": ("receivables", "outstanding_amount", None),
        "Outstanding payables": ("payables", "outstanding_amount", None),
        "Overdue receivables": ("overdue", "overdue_amount", "receivable"),
        "Overdue payables": ("overdue", "overdue_amount", "payable"),
    },
}


def expected_value(overview: dict, tile: str, measure: str, ledger: str | None) -> float:
    rows = overview["tiles"][tile]["result"]["rows"]
    return sum(float(r[measure]) for r in rows if ledger is None or r.get("ledger") == ledger)


def embedded_frame(page: Page):
    for _ in range(60):
        frame = next((f for f in page.frames if "/embedded/" in f.url), None)
        if frame:
            return frame
        page.wait_for_timeout(500)
    raise TimeoutError("no embedded Superset frame")


def check_embedded(browser, base: str, password: str, check: Check, values: dict) -> None:
    print("- embedded Superset dashboards (values vs the KPI service, per user)")
    for username, modules in EMBED_ROLES.items():
        context = browser.new_context(viewport={"width": 1440, "height": 1000})
        page = context.new_page()
        errors: list[str] = []
        watch_console(page, errors)
        page.goto(f"{base}/app/login")
        sign_in(page, base, username, password)
        at(page, f"{base}/app/")
        overview = page.evaluate("fetch('/api/v1/portal/overview/').then(r => r.json())")
        for module in modules:
            page.goto(f"{base}/app/{module}")
            frame = embedded_frame(page)
            for chart, (tile, measure, ledger) in BIG_NUMBERS[module].items():
                cell = frame.locator(f'[data-test-chart-name="{chart}"] .header-line')
                cell.wait_for(timeout=30_000)
                shown = float(cell.inner_text().replace(",", ""))
                want = expected_value(overview, tile, measure, ledger)
                values[(username, chart)] = shown
                check(
                    f"{username}: embedded {chart!r} = KPI service",
                    shown == want,
                    f"{shown} vs {want}",
                )
            if module == "hr" and username == "demo_executive":
                page.screenshot(path=SHOTS / "embedded-hr-desktop.png", full_page=True)
        check(
            f"{username}: no console errors with embedded dashboards",
            not errors,
            "; ".join(errors)[:300],
        )
        context.close()
    for chart in ("Active headcount", "Outstanding receivables"):
        everyone, branch = values[("demo_executive", chart)], values[("demo_branch", chart)]
        check(
            f"branch manager sees less than the organisation: {chart}",
            branch < everyone,
            f"{branch} vs {everyone}",
        )


def check_sign_in_errors(browser, base: str, check: Check) -> None:
    print("- sign-in errors (throwaway username)")
    context = browser.new_context(viewport={"width": 1440, "height": 900})
    page = context.new_page()
    page.goto(f"{base}/app/login")
    page.get_by_role("button", name="Sign in").click()
    alert = page.get_by_role("alert")
    check(
        "empty form is rejected in the browser",
        "Enter your username and password" in alert.inner_text(),
    )
    sign_in(page, base, THROWAWAY_USER, "not-a-password")
    page.get_by_text("Username or password is incorrect.").wait_for(timeout=10_000)
    check("wrong credentials give the generic message", True)
    check(
        "password field is cleared", page.get_by_label("Password", exact=True).input_value() == ""
    )
    check("still on the sign-in page", page.url.startswith(f"{base}/app/login"), page.url)
    context.close()


def check_layouts(browser, base: str, password: str, check: Check) -> None:
    print("- responsive layout (demo_executive)")
    SHOTS.mkdir(parents=True, exist_ok=True)
    for name, (width, height) in VIEWPORTS.items():
        context = browser.new_context(viewport={"width": width, "height": height})
        page = context.new_page()
        errors: list[str] = []
        watch_console(page, errors)

        page.goto(f"{base}/app/login")
        page.get_by_role("heading", name="Sign in").wait_for()
        page.screenshot(path=SHOTS / f"login-{name}.png", full_page=True)
        sign_in(page, base, "demo_executive", password)
        at(page, f"{base}/app/")
        h1(page)

        overflow = page.evaluate("document.documentElement.scrollWidth - window.innerWidth")
        check(f"{name} {width}px: no horizontal scrolling", overflow <= 0, f"overflow {overflow}px")
        page.screenshot(path=SHOTS / f"overview-{name}.png", full_page=True)

        menu = page.get_by_role("button", name="Open menu")
        sidebar = page.locator("#app-sidebar")
        if width < 1024:
            check(
                f"{name}: sidebar hidden, menu button shown",
                menu.is_visible() and not sidebar.is_visible(),
            )
            menu.click()
            sidebar.wait_for(state="visible")
            page.wait_for_timeout(300)  # let the 200 ms slide-in finish before the screenshot
            page.screenshot(path=SHOTS / f"menu-{name}.png")
            page.locator("nav[aria-label=Main] a", has_text="Accounts Analytics").click()
            at(page, f"{base}/app/accounts")
            sidebar.wait_for(state="hidden")
            check(f"{name}: drawer navigates and closes", h1(page) == "Accounts Analytics")
            menu.click()
            sidebar.wait_for(state="visible")
            page.keyboard.press("Escape")
            sidebar.wait_for(state="hidden")
            check(f"{name}: Escape closes the drawer", not sidebar.is_visible())
        else:
            close = page.get_by_role("button", name="Close menu")
            check(
                f"{name}: sidebar always visible, no menu/close buttons",
                sidebar.is_visible() and not menu.is_visible() and not close.is_visible(),
            )
            page.goto(f"{base}/app/hr")
            h1(page)
            page.screenshot(path=SHOTS / f"hr-{name}.png", full_page=True)

        page.goto(f"{base}/app/no-such-page")  # a client-side route: Django answers 200
        page.get_by_role("heading", name="Page not found").wait_for()
        check(f"{name}: unknown page shows not-found inside the app", sidebar.count() == 1)
        check(f"{name}: no console errors", not errors, "; ".join(errors)[:300])
        context.close()


# ------------------------------------------------------------------ temporary administrator
@contextlib.contextmanager
def temporary_admin():
    """A throwaway superuser in the running backend container (random password, deleted after)."""
    password = secrets.token_urlsafe(24)
    compose = [
        "docker",
        "compose",
        "--env-file",
        str(ENV_FILE),
        "--profile",
        "backend",
        "exec",
        "-T",
    ]
    create = (
        "import os;from django.contrib.auth import get_user_model as g;U=g();"
        f"U.objects.filter(username='{TEMP_ADMIN}').delete();"
        f"U.objects.create_superuser('{TEMP_ADMIN}', password=os.environ['TMP_PW'])"
    )
    shell = ["backend", "python", "manage.py", "shell", "-c"]
    subprocess.run(
        [*compose, "-e", f"TMP_PW={password}", *shell, create],
        cwd=REPO,
        check=True,
        capture_output=True,
    )
    try:
        yield TEMP_ADMIN, password
    finally:
        delete = (
            "from django.contrib.auth import get_user_model as g;"
            f"g().objects.filter(username='{TEMP_ADMIN}').delete()"
        )
        subprocess.run([*compose, *shell, delete], cwd=REPO, capture_output=True)


def signed_in_page(browser, base: str, username: str, password: str, **context_args) -> Page:
    context = browser.new_context(viewport={"width": 1440, "height": 1000}, **context_args)
    page = context.new_page()
    page.goto(f"{base}/app/login")
    sign_in(page, base, username, password)
    at(page, f"{base}/app/")
    h1(page)
    return page


def ask(page: Page, question: str) -> str:
    """Ask the assistant in the page and return the text of the new answer."""
    answers = page.get_by_role("article", name="Assistant answer")
    before = answers.count()
    page.get_by_label("Your question").fill(question)
    page.keyboard.press("Enter")
    answers.nth(before).wait_for(timeout=20_000)
    return answers.nth(before).inner_text()


def download_text(page: Page, click) -> str:
    with page.expect_download(timeout=30_000) as info:
        click()
    return Path(info.value.path()).read_text(encoding="utf-8-sig")


def open_chart_download(frame, chart):
    """Superset chart menu -> Download; returns the visible "Export to .CSV" item. Superset places
    the menu popups while the page may still be scrolling to the chart, so the whole sequence is
    retried (menu closed with Escape) until the item is visible. The caller clicks it with a DOM
    click event: a pointer move from "Download" to the item can cross another entry and close the
    submenu (depends on the menu's position on the page)."""
    item = frame.get_by_text("Export to .CSV")
    for _ in range(4):
        chart.scroll_into_view_if_needed()
        chart.hover()
        chart.locator(
            '[aria-label="More Options"], [data-test="slice-header-controls-trigger"]'
        ).first.click()
        frame.get_by_text("Download", exact=True).hover()
        try:
            item.wait_for(state="visible", timeout=4_000)
            return item
        except Exception:
            chart.page.keyboard.press("Escape")
            chart.page.wait_for_timeout(500)
    raise TimeoutError("the chart's Download -> Export to .CSV menu did not open")


def money(value: float) -> str:
    return f"{value:,.2f}"


# --------------------------------------------------------- Ask AI, Reports, Administration
def check_pages(browser, base: str, password: str, admin: tuple[str, str], check: Check) -> None:
    print("- Ask AI, Reports and Administration against the live backend")
    page = signed_in_page(browser, base, "demo_executive", password, accept_downloads=True)
    errors: list[str] = []
    watch_console(page, errors)
    overview = page.evaluate("fetch('/api/v1/portal/overview/').then(r => r.json())")
    overdue = expected_value(overview, "overdue", "overdue_amount", "receivable")
    headcount = expected_value(overview, "headcount", "active_headcount", None)

    page.goto(f"{base}/app/ask")
    text = ask(page, "How much is overdue?")
    check(
        "Ask AI: answer contains the KPI service's overdue receivables",
        f"BTN {money(overdue)}" in text,
        text[:200],
    )
    check(
        "Ask AI: labelled as warehouse data and as no language model",
        "Answer from warehouse data" in text and "no language model" in text,
    )
    text = ask(page, "what is the weather tomorrow")
    check(
        "Ask AI: an unsupported question is refused without data",
        "Not supported" in text and "BTN" not in text,
        text[:200],
    )
    text = ask(page, "what is the weather")
    check(
        "Ask AI: a vague question gets a clarification and no data",
        "Needs clarification" in text and "BTN" not in text,
        text[:200],
    )
    answers = page.get_by_role("article", name="Assistant answer")
    answers.nth(2).get_by_role("button", name="How many active employees are there?").click()
    answers.nth(3).wait_for(timeout=20_000)
    third = answers.nth(3).inner_text()
    check(
        "Ask AI: a clarification option is answered with the KPI value",
        f" {int(headcount)} " in f" {third} ".replace(".", " "),
        third[:200],
    )
    page.screenshot(path=SHOTS / "ask-desktop.png", full_page=True)

    page.goto(f"{base}/app/reports")
    card = page.locator(
        "section.report", has=page.get_by_role("heading", name="Active headcount by department")
    )
    content = download_text(page, lambda: card.get_by_role("link", name="Download CSV").click())
    rows = list(csv.reader(io.StringIO(content)))
    total = sum(int(r[1]) for r in rows[1:])
    check(
        "Reports: the CSV download sums to the KPI headcount",
        rows[0] == ["Department", "Active headcount"] and total == headcount,
        f"{total} vs {headcount}",
    )
    card.get_by_role("button", name="Preview").click()
    card.get_by_role("table").wait_for(timeout=15_000)
    check("Reports: the preview shows a table", card.get_by_role("table").count() == 1)
    page.screenshot(path=SHOTS / "reports-desktop.png", full_page=True)
    check("Ask AI and Reports: no console errors", not errors, "; ".join(errors)[:300])
    page.context.close()

    page = signed_in_page(browser, base, *admin)
    errors = []
    watch_console(page, errors)
    check("Administration: in the administrator's menu", "Administration" in nav_labels(page))
    page.goto(f"{base}/app/admin")
    page.get_by_text("Embedding service account works").wait_for(timeout=20_000)
    check(
        "Administration: status shows Superset and the service account",
        page.get_by_text("Superset reachable").count() == 1,
    )
    users = page.get_by_role("table", name="Users, roles and modules")
    check(
        "Administration: users with roles and branches",
        users.get_by_text("odoo:odoo-sandbox:1").count() == 1,
    )
    page.screenshot(path=SHOTS / "admin-desktop.png", full_page=True)
    page.goto(f"{base}/app/manage")
    table = page.get_by_role("table", name="Dashboards shown in the website")
    table.wait_for(timeout=15_000)
    check(
        "Manage dashboards: the administrator sees both modules' official dashboards",
        table.get_by_text("Official", exact=True).count() == 2,
    )
    check("Administration: no console errors", not errors, "; ".join(errors)[:300])
    page.context.close()

    # ADR-044: the HR Manager builds (Superset) and publishes HR dashboards, nothing else.
    page = signed_in_page(browser, base, "demo_hr", password)
    errors = []
    watch_console(page, errors)
    page.goto(f"{base}/app/hr")
    editor = page.get_by_role("link", name="Edit in Superset (separate sign-in)")
    editor.wait_for(timeout=15_000)
    check(
        "HR Manager: editor link to the HR dashboard in Superset",
        "/superset/dashboard/druksmart-hr/" in (editor.get_attribute("href") or ""),
    )
    page.goto(f"{base}/app/manage")
    table = page.get_by_role("table", name="Dashboards shown in the website")
    table.wait_for(timeout=15_000)
    rows = table.locator("tbody tr")
    check(
        "HR Manager: manages the HR page only",
        rows.count() == 1
        and "HR" in rows.first.inner_text()
        and "Accounts" not in table.inner_text(),
        table.inner_text()[:200],
    )
    options = page.get_by_label("Module page").locator("option").all_inner_texts()
    check("HR Manager: can publish on the HR page only", options == ["HR"], str(options))
    page.screenshot(path=SHOTS / "manage-hr-manager.png", full_page=True)
    check("HR Manager pages: no console errors", not errors, "; ".join(errors)[:300])
    page.context.close()

    page = signed_in_page(browser, base, "demo_executive", password)
    page.goto(f"{base}/app/hr")
    embedded_frame(page)
    check(
        "Executive: no editor link (view only)",
        page.get_by_role("link", name="Edit in Superset (separate sign-in)").count() == 0,
    )
    page.context.close()


# ------------------------------------------------------------------------- accessibility
def check_accessibility(
    browser, base: str, password: str, admin: tuple[str, str], check: Check
) -> None:
    """axe-core WCAG 2.1 A/AA audit of every page. Superset's iframe content is excluded (it is
    Superset's own interface). bypass_csp only lets the test inject axe; the app is unchanged."""
    print("- accessibility (axe-core, WCAG 2.1 A/AA)")
    tags = ["wcag2a", "wcag2aa", "wcag21a", "wcag21aa"]

    def audit(page: Page, name: str) -> None:
        page.add_script_tag(path=str(AXE))
        result = page.evaluate(
            "tags => axe.run({exclude: [['iframe']]}, {runOnly: {type: 'tag', values: tags}})",
            tags,
        )
        found = [f"{v['id']} ({v['impact']}, {len(v['nodes'])}x)" for v in result["violations"]]
        check(f"accessibility: {name}", not found, "; ".join(found)[:400])

    context = browser.new_context(viewport={"width": 1440, "height": 1000}, bypass_csp=True)
    page = context.new_page()
    page.goto(f"{base}/app/login")
    page.get_by_role("heading", name="Sign in").wait_for()
    audit(page, "sign-in page")
    context.close()

    page = signed_in_page(browser, base, "demo_executive", password, bypass_csp=True)
    audit(page, "overview")
    for path, name in (("/app/hr", "HR analytics"), ("/app/accounts", "Accounts analytics")):
        page.goto(f"{base}{path}")
        embedded_frame(page)
        audit(page, name)
    page.goto(f"{base}/app/ask")
    ask(page, "Show the ageing of receivables.")
    audit(page, "Ask AI with an answer")
    page.goto(f"{base}/app/reports")
    page.get_by_role("button", name="Preview").first.click()
    page.get_by_role("table").first.wait_for(timeout=15_000)
    audit(page, "reports with a preview")
    page.goto(f"{base}/app/nowhere")
    page.get_by_role("heading", name="Page not found").wait_for()
    audit(page, "not-found page")
    page.context.close()

    page = signed_in_page(browser, base, *admin, bypass_csp=True)
    page.goto(f"{base}/app/admin")
    page.get_by_text("Embedding service account works").wait_for(timeout=20_000)
    audit(page, "administration")
    page.context.close()


# --------------------------------------------------------------------- the 12-step journey
def check_journey(browser, base: str, password: str, username: str, check: Check) -> None:
    """The 12-step user journey of the Milestone 10 brief, numbers checked at each step."""
    print(f"- user journey (12 steps) as {username}")
    context = browser.new_context(viewport={"width": 1440, "height": 1000}, accept_downloads=True)
    page = context.new_page()
    errors: list[str] = []
    watch_console(page, errors)
    j = f"journey {username}"

    page.goto(f"{base}/app/")  # 1. open the website
    page.wait_for_url("**/app/login*")
    check(f"{j}: 1 opening the website asks to sign in", "/app/login" in page.url)
    sign_in(page, base, username, password)  # 2. log in
    at(page, f"{base}/app/")
    overview = page.evaluate("fetch('/api/v1/portal/overview/').then(r => r.json())")
    headcount = expected_value(overview, "headcount", "active_headcount", None)
    receivables = expected_value(overview, "receivables", "outstanding_amount", None)
    tile = page.locator(".stat", has=page.get_by_text("Active employees", exact=True))  # 3.
    check(
        f"{j}: 2-3 signed in; the overview shows the authorised headcount",
        tile.locator(".stat__value").inner_text() == f"{int(headcount)}",
    )

    page.locator("nav[aria-label=Main] a", has_text="HR Analytics").click()  # 4. HR analytics
    frame = embedded_frame(page)
    cell = frame.locator('[data-test-chart-name="Active headcount"] .header-line')
    cell.wait_for(timeout=30_000)
    check(
        f"{j}: 4 the HR dashboard shows the same headcount",
        float(cell.inner_text().replace(",", "")) == headcount,
    )
    chart = frame.locator('[data-test-chart-name="Headcount by organisation and branch"]')
    content = download_text(
        page, lambda: open_chart_download(frame, chart).dispatch_event("click")
    )  # 5. interact
    exported = list(csv.reader(io.StringIO(content)))
    active = sum(int(r[2]) for r in exported[1:])
    check(
        f"{j}: 5 a chart's CSV export from the dashboard matches the headcount",
        active == headcount,
        f"{active} vs {headcount}",
    )

    page.locator("nav[aria-label=Main] a", has_text="Accounts Analytics").click()  # 6-7.
    frame = embedded_frame(page)
    cell = frame.locator('[data-test-chart-name="Outstanding receivables"] .header-line')
    cell.wait_for(timeout=30_000)
    check(
        f"{j}: 6-7 the Accounts dashboard shows the same receivables",
        float(cell.inner_text().replace(",", "")) == receivables,
    )

    page.locator("nav[aria-label=Main] a", has_text="Ask AI").click()  # 8-10. Ask AI
    text = ask(page, "What is the outstanding receivables balance?")
    check(
        f"{j}: 8-10 Ask AI answers with the verified receivables",
        money(receivables) in text,
        text[:200],
    )

    page.locator("nav[aria-label=Main] a", has_text="Reports").click()  # 11. reports
    card = page.locator(
        "section.report", has=page.get_by_role("heading", name="Outstanding receivables by branch")
    )
    content = download_text(page, lambda: card.get_by_role("link", name="Download CSV").click())
    rows = list(csv.reader(io.StringIO(content)))
    amount = rows[0].index("Outstanding balance")
    total = sum(float(r[amount]) for r in rows[1:])
    check(
        f"{j}: 11 the report export sums to the receivables",
        abs(total - receivables) < 0.005,
        f"{total} vs {receivables}",
    )

    page.get_by_role("button", name="Sign out").click()  # 12. log out
    page.wait_for_url(f"{base}/app/login")
    status = page.evaluate("fetch('/api/v1/portal/overview/').then(r => r.status)")
    check(f"{j}: 12 signed out; the API refuses the old session", status == 401)
    check(f"{j}: no console errors", not errors, "; ".join(errors)[:300])
    context.close()


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--base", default="http://127.0.0.1:8000")
    parser.add_argument("--task", default="10.9", help="evidence folder suffix, e.g. 10.9")
    parser.add_argument(
        "--env-file", default=str(REPO / ".env"), help="stack to test (clean-start tests)"
    )
    args = parser.parse_args()
    global SHOTS, RESULTS, ENV_FILE
    ENV_FILE = Path(args.env_file).resolve()
    SHOTS = REPO / "docs" / "web" / "screenshots" / f"task-{args.task}"
    RESULTS = REPO / "docs" / "web" / "results" / f"task_{args.task.replace('.', '_')}_browser.json"
    load_dotenv(ENV_FILE)
    password = os.environ.get("BACKEND_DEMO_USER_PASSWORD", "")
    if not password:
        print("BACKEND_DEMO_USER_PASSWORD is not set in .env (demo users needed)", file=sys.stderr)
        return 2

    check = Check()
    with sync_playwright() as pw:
        browser = pw.chromium.launch(channel="msedge", headless=True)
        try:
            for username in ROLES:
                check_role(browser, args.base, username, password, check)
            check_sign_in_errors(browser, args.base, check)
            SHOTS.mkdir(parents=True, exist_ok=True)
            check_embedded(browser, args.base, password, check, {})
            with temporary_admin() as admin:
                check_pages(browser, args.base, password, admin, check)
                check_accessibility(browser, args.base, password, admin, check)
            for username in ("demo_executive", "demo_branch"):
                check_journey(browser, args.base, password, username, check)
            check_layouts(browser, args.base, password, check)
        finally:
            browser.close()

    failed = [r for r in check.results if not r["ok"]]
    RESULTS.parent.mkdir(parents=True, exist_ok=True)
    RESULTS.write_text(
        json.dumps(
            {
                "checked_at": datetime.now(UTC).isoformat(timespec="seconds"),
                "base": args.base,
                "passed": len(check.results) - len(failed),
                "failed": len(failed),
                "results": check.results,
            },
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )
    passed = len(check.results) - len(failed)
    print(f"\n{passed}/{len(check.results)} checks passed -> {RESULTS.relative_to(REPO)}")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
