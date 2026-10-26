"""Render the dashboards in a real (headless) browser as each role and report what users see.

    pip install playwright           # once (dev only); uses the installed Microsoft Edge
    python superset/scripts/browser_check.py [--screenshots docs/bi/screenshots]

For each user it logs in through the normal login page, opens both default dashboards, waits for
every chart to finish, and reports: whether the dashboard opened or was denied, how many charts
rendered, the big-number KPI values shown, and any chart error messages. Exit code 1 if a
dashboard the role SHOULD see fails to render cleanly, or one it should NOT see opens, or a KPI
card shows a different value than the warehouse facts (computed independently, for the latest
snapshot date and, for the branch manager, only the RLS branch).
"""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

import yaml
from dotenv import load_dotenv
from playwright.sync_api import TimeoutError as PlaywrightTimeout
from playwright.sync_api import sync_playwright

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO))

from druksmart_common.config import load_settings  # noqa: E402
from druksmart_common.db import connect  # noqa: E402

# user -> dashboards (slug) the role must be able to open (access.yml)
EXPECTED = {
    "admin": {"druksmart-hr", "druksmart-accounts"},
    "demo_hr": {"druksmart-hr"},
    "demo_accounts": {"druksmart-accounts"},
    "demo_executive": {"druksmart-hr", "druksmart-accounts"},
    "demo_branch": {"druksmart-hr", "druksmart-accounts"},
}
DASHBOARDS = ["druksmart-hr", "druksmart-accounts"]
ERROR_SELECTORS = '[data-test="error-alert"], .alert-danger, [role="alert"].ant-alert-error'


def expected_kpis(branch_keys: list[str] | None) -> dict[str, float]:
    """KPI card values straight from the dbt FACT tables (latest snapshot date)."""
    where = " and branch_key = any(%s)" if branch_keys else ""
    args = (branch_keys,) if branch_keys else ()
    with connect(load_settings().pipeline(), autocommit=True) as conn:
        hc, not_active = conn.execute(
            "select count(*) filter (where employment_status = 'active'), "
            "count(*) filter (where employment_status <> 'active') "
            "from marts.fct_headcount_snapshot "
            "where snapshot_date = (select max(snapshot_date) from marts.fct_headcount_snapshot)"
            + where,
            args,
        ).fetchone()
        ar, ar_due, ap, ap_due = conn.execute(
            "select coalesce(sum(outstanding_company) filter (where ledger = 'receivable'), 0), "
            "coalesce(sum(outstanding_company) "
            "filter (where ledger = 'receivable' and is_overdue), 0), "
            "coalesce(sum(outstanding_company) filter (where ledger = 'payable'), 0), "
            "coalesce(sum(outstanding_company) "
            "filter (where ledger = 'payable' and is_overdue), 0) "
            "from marts.fct_receivable_payable_snapshot where snapshot_date = "
            "(select max(snapshot_date) from marts.fct_receivable_payable_snapshot)" + where,
            args,
        ).fetchone()
    return {
        "Active headcount": hc,
        "Not-active employee records": not_active,
        "Outstanding receivables": float(ar),
        "Overdue receivables": float(ar_due),
        "Outstanding payables": float(ap),
        "Overdue payables": float(ap_due),
    }


def as_number(text: str) -> float | None:
    cleaned = "".join(ch for ch in text if ch.isdigit() or ch in ".-")
    try:
        return float(cleaned)
    except ValueError:
        return None


def login(page, base: str, username: str, password: str) -> None:
    page.goto(f"{base}/login/")
    page.fill('input[name="username"], #username', username)
    page.fill('input[name="password"], #password', password)
    page.keyboard.press("Enter")
    page.wait_for_url(lambda url: "/login" not in url, timeout=30000)


def check_dashboard(page, base: str, slug: str, shot: Path | None) -> dict:
    resp = page.goto(f"{base}/superset/dashboard/{slug}/", wait_until="domcontentloaded")
    result = {"status": resp.status if resp else None, "charts": 0, "numbers": {}, "errors": []}
    try:
        page.wait_for_selector(
            '[data-test="dashboard-header-container"], .dashboard-header', timeout=30000
        )
    except PlaywrightTimeout:
        body = page.inner_text("body")[:300].replace("\n", " ")
        result["denied"] = True
        result["page"] = body
        return result
    # Wait until no chart is still loading.
    page.wait_for_load_state("networkidle", timeout=60000)
    page.wait_for_function(
        "() => !document.querySelector('.loading, [data-test=\"loading-indicator\"]')",
        timeout=60000,
    )
    holders = page.locator(".dashboard-component-chart-holder")
    names = set()
    for i in range(holders.count()):
        h = holders.nth(i)
        title = h.locator('[data-test="editable-title"], .header-title, [data-test="slice-header"]')
        # First line only: the header also shows a badge with the number of applied filters.
        name = title.first.inner_text().strip().splitlines()[0] if title.count() else f"chart {i}"
        names.add(name)
        number = h.locator(".header-line")
        if number.count():
            result["numbers"][name] = number.first.inner_text().strip()
        err = h.locator(ERROR_SELECTORS)
        if err.count():
            result["errors"].append(f"{name}: {err.first.inner_text().strip()[:150]}")
    result["charts"] = len(names)
    if shot:
        shot.parent.mkdir(parents=True, exist_ok=True)
        page.screenshot(path=str(shot), full_page=True)
    return result


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--screenshots", type=Path, help="save full-page screenshots here")
    parser.add_argument("--users", nargs="*", default=list(EXPECTED))
    args = parser.parse_args(argv)
    load_dotenv(REPO / ".env", override=False)
    base = f"http://127.0.0.1:{os.environ.get('SUPERSET_PORT', '8088')}"
    access = yaml.safe_load((REPO / "superset" / "definitions" / "access.yml").read_text("utf-8"))
    rls_keys = [k for r in access["row_level_security"] for k in r["branch_keys"]]
    full, restricted = expected_kpis(None), expected_kpis(rls_keys)
    failures = 0
    with sync_playwright() as pw:
        browser = pw.chromium.launch(channel="msedge", headless=True)
        for user in args.users:
            password = (
                os.environ["SUPERSET_ADMIN_PASSWORD"]
                if user == "admin"
                else os.environ["SUPERSET_DEMO_USER_PASSWORD"]
            )
            username = os.environ["SUPERSET_ADMIN_USER"] if user == "admin" else user
            context = browser.new_context(viewport={"width": 1600, "height": 1000})
            page = context.new_page()
            login(page, base, username, password)
            for slug in DASHBOARDS:
                shot = args.screenshots / f"{user}_{slug}.png" if args.screenshots else None
                r = check_dashboard(page, base, slug, shot)
                allowed = slug in EXPECTED[user]
                opened = not r.get("denied")
                expected = restricted if user == "demo_branch" else full
                wrong = {
                    name: (shown, expected[name])
                    for name, shown in r["numbers"].items()
                    if name in expected and as_number(shown) != expected[name]
                }
                ok = (
                    (opened and not r["errors"] and r["charts"] > 0 and not wrong)
                    if allowed
                    else not opened
                )
                failures += not ok
                state = "OPENED" if opened else "DENIED"
                print(
                    f"[{'PASS' if ok else 'FAIL'}] {user:<15} {slug:<20} {state} "
                    f"charts={r['charts']} errors={len(r['errors'])}"
                )
                for name, value in r["numbers"].items():
                    check = ""
                    if name in expected:
                        check = (
                            "  (= warehouse)"
                            if name not in wrong
                            else (f"  MISMATCH: warehouse says {expected[name]}")
                        )
                    print(f"         {name}: {value}{check}")
                for e in r["errors"]:
                    print(f"         ERROR {e}")
                if not opened and allowed:
                    print(f"         page: {r.get('page')}")
            context.close()
        browser.close()
    print("browser check:", "all passed" if not failures else f"{failures} failure(s)")
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
