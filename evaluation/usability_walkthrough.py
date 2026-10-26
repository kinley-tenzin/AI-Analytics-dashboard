"""Automated usability WALKTHROUGH of the user tasks (Milestone 8, Task 7). NOT a user study.

    python evaluation/usability_walkthrough.py

Performs each realistic user task through the real browser UI (headless Microsoft Edge) as the
appropriate role, and records whether it can be completed, the expert path (number of user
actions) and the time. It proves the tasks are feasible and the UI shows the right numbers; it
says NOTHING about clarity or satisfaction. That needs real participants (docs/evaluation/USABILITY.md).
Screenshots: docs/evaluation/screenshots/. Results: docs/evaluation/results/usability_walkthrough.json.
"""

from __future__ import annotations

import os
import sys
import time
from pathlib import Path

from playwright.sync_api import sync_playwright

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

import evaltools as et  # noqa: E402

SHOTS = et.REPO / "docs" / "evaluation" / "screenshots"


def warehouse_value(sql: str, *params):
    with et.warehouse() as conn:
        return conn.execute(sql, params).fetchone()[0]


def latest(table: str):
    return warehouse_value(f"select max(snapshot_date) from marts.{table}")


def number(text: str) -> float:
    return float("".join(c for c in text if c.isdigit() or c == "."))


def superset_login(page, user: str) -> int:
    page.goto(f"{et.SUPERSET_URL}/login/")
    password = os.environ["SUPERSET_DEMO_USER_PASSWORD"]
    page.fill('input[name="username"], #username', user)
    page.fill('input[name="password"], #password', password)
    page.keyboard.press("Enter")
    page.wait_for_url(lambda u: "/login" not in u)
    return 3  # type user, type password, press enter


def open_dashboard(page, slug: str) -> int:
    page.goto(f"{et.SUPERSET_URL}/superset/dashboard/{slug}/")
    page.wait_for_selector(".dashboard-component-chart-holder", timeout=60000)
    page.wait_for_load_state("networkidle")
    page.wait_for_function("() => !document.querySelector('.loading')", timeout=60000)
    return 2  # open Dashboards menu, click the dashboard


def card(page, title: str) -> str:
    return page.locator(".dashboard-component-chart-holder", has_text=title).first.locator(".header-line").inner_text()


def task_headcount(page) -> dict:
    actions = superset_login(page, "demo_hr") + open_dashboard(page, "druksmart-hr")
    shown = number(card(page, "Active headcount"))
    expected = warehouse_value(
        "select count(*) from marts.fct_headcount_snapshot where snapshot_date = %s and employment_status = 'active'",
        latest("fct_headcount_snapshot"),
    )
    return {
        "role": "HR Manager",
        "ui": "Superset HR dashboard",
        "actions": actions,
        "shown": shown,
        "expected": expected,
        "completed": shown == expected,
    }


def task_filter_department(page) -> dict:
    actions = superset_login(page, "demo_hr") + open_dashboard(page, "druksmart-hr")
    page.locator(".ant-form-item", has_text="Department").locator(".ant-select").first.click()
    page.locator(".ant-select-item-option", has_text="Sales").first.click()
    page.keyboard.press("Escape")
    page.get_by_role("button", name="Apply filters").click()
    page.wait_for_load_state("networkidle")
    time.sleep(3)
    actions += 4  # open Department filter, choose Sales, close, Apply filters
    shown = number(card(page, "Active headcount"))
    expected = warehouse_value(
        "select count(*) from marts.fct_headcount_snapshot f join marts.dim_department d "
        "using (department_key) where f.snapshot_date = %s and f.employment_status = 'active' "
        "and d.department_name = 'Sales'",
        latest("fct_headcount_snapshot"),
    )
    page.screenshot(path=str(SHOTS / "task2_filter_department.png"), full_page=True)
    return {
        "role": "HR Manager",
        "ui": "Superset HR dashboard, Department filter",
        "actions": actions,
        "shown": shown,
        "expected": expected,
        "completed": shown == expected,
    }


def task_receivables(page) -> dict:
    actions = superset_login(page, "demo_accounts") + open_dashboard(page, "druksmart-accounts")
    shown = number(card(page, "Outstanding receivables"))
    expected = float(
        warehouse_value(
            "select sum(outstanding_company) from marts.fct_receivable_payable_snapshot "
            "where snapshot_date = %s and ledger = 'receivable'",
            latest("fct_receivable_payable_snapshot"),
        )
    )
    page.screenshot(path=str(SHOTS / "task3_accounts_dashboard.png"), full_page=True)
    return {
        "role": "Accounts Manager",
        "ui": "Superset Accounts dashboard",
        "actions": actions,
        "shown": shown,
        "expected": expected,
        "completed": abs(shown - expected) < 0.01,
    }


def task_overdue_categories(page) -> dict:
    actions = superset_login(page, "demo_accounts") + open_dashboard(page, "druksmart-accounts")
    chart = page.locator(".dashboard-component-chart-holder", has_text="Ageing of open balances by ledger").first
    visible = chart.locator("canvas, svg").count() > 0
    buckets = warehouse_value(
        "select count(distinct ageing_bucket) from marts.fct_receivable_payable_snapshot "
        "where snapshot_date = %s and is_overdue",
        latest("fct_receivable_payable_snapshot"),
    )
    return {
        "role": "Accounts Manager",
        "ui": "Superset ageing chart",
        "actions": actions,
        "shown": "ageing chart rendered" if visible else "not rendered",
        "expected": f"{buckets} overdue buckets in the data",
        "completed": visible,
    }


def task_export(page) -> dict:
    actions = superset_login(page, "demo_accounts") + open_dashboard(page, "druksmart-accounts")
    holder = page.locator(
        ".dashboard-component-chart-holder", has_text="Open balances by organisation and branch"
    ).first
    holder.hover()
    holder.locator('[aria-label="More Options"], [data-test="slice-header"] .ant-dropdown-trigger').first.click()
    page.get_by_text("Download", exact=True).first.hover()
    with page.expect_download(timeout=60000) as info:
        page.get_by_text("Export to .CSV").first.click()
    download = info.value
    path = SHOTS.parent / "results" / "task5_export.csv"
    download.save_as(path)
    content = path.read_text(encoding="utf-8-sig")
    actions += 4  # hover chart, open menu, Download, Export to .CSV
    ok = "Outstanding receivables" in content and "DTG" in content
    return {
        "role": "Accounts Manager",
        "ui": "Superset chart menu -> Download -> Export to .CSV",
        "actions": actions,
        "shown": f"{len(content.splitlines())} CSV lines",
        "expected": "header + rows of the permitted table",
        "completed": ok,
    }


def task_ask_ai(page) -> dict:
    # Milestone 10: the assistant is the "Ask AI" page of the DrukSmart website.
    page.goto(f"{et.DJANGO_URL}/app/login?next=/ask")
    page.get_by_label("Username").fill("demo_executive")
    page.get_by_label("Password", exact=True).fill(os.environ["BACKEND_DEMO_USER_PASSWORD"])
    page.get_by_role("button", name="Sign in").click()
    page.get_by_label("Your question").fill("How much is overdue?")
    page.keyboard.press("Enter")
    answer = page.get_by_role("article", name="Assistant answer").first
    answer.wait_for(timeout=30000)
    text = answer.locator(".answer__text").inner_text()
    page.screenshot(path=str(SHOTS / "task6_ask_ai.png"), full_page=True)
    expected = float(
        warehouse_value(
            "select sum(outstanding_company) from marts.fct_receivable_payable_snapshot "
            "where snapshot_date = %s and ledger = 'receivable' and is_overdue",
            latest("fct_receivable_payable_snapshot"),
        )
    )
    return {
        "role": "Executive",
        "ui": "DrukSmart website, Ask AI page",
        "actions": 6,
        "shown": text,
        "expected": f"overdue receivables BTN {expected:,.2f}",
        "completed": f"{expected:,.2f}" in text,
    }


TASKS = [
    ("T1 Find the current HR headcount", task_headcount),
    ("T2 Filter employees by department (Sales)", task_filter_department),
    ("T3 View outstanding receivables", task_receivables),
    ("T4 Identify overdue invoice categories", task_overdue_categories),
    ("T5 Export permitted analytical results (CSV)", task_export),
    ("T6 Ask an AI question and read the answer", task_ask_ai),
]


def main() -> int:
    SHOTS.mkdir(parents=True, exist_ok=True)
    results = []
    with sync_playwright() as pw:
        browser = pw.chromium.launch(channel="msedge", headless=True)
        for name, fn in TASKS:
            context = browser.new_context(viewport={"width": 1500, "height": 1000}, accept_downloads=True)
            page = context.new_page()
            t = time.perf_counter()
            try:
                r = fn(page)
            except Exception as exc:
                r = {"completed": False, "error": f"{type(exc).__name__}: {str(exc)[:200]}"}
            r["task"], r["seconds"] = name, round(time.perf_counter() - t, 1)
            results.append(r)
            print(f"[{'DONE' if r['completed'] else 'FAIL'}] {name}: {r.get('shown', r.get('error'))}")
            context.close()
        browser.close()
    et.save_result("usability_walkthrough", results)
    return 0 if all(r["completed"] for r in results) else 1


if __name__ == "__main__":
    sys.exit(main())
