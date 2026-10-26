"""End-to-end warehouse test: synthetic fixtures -> (fake ERP APIs) -> raw -> dbt -> marts.

The marts must reproduce tests/fixtures/synthetic/expected_kpis.json, which was calculated by
hand in Milestone 2. Runs ONLY in the isolated `<analytics db>_test` database.

Requires: docker compose up -d, dbt installed (pip install -e ".[dev,warehouse]").
Run with: pytest -m warehouse -v
"""

import json
import subprocess
import sys
from dataclasses import replace
from datetime import date

import pytest
from fake_erp import ERP_KEY, ERP_SECRET, ODOO_KEY, FakeFrappe, FakeOdoo, fixture_records
from kpi_reference import FIXTURES_DIR, load_fixtures

from connectors.config import SourceConfig
from connectors.erpnext import ERPNextConnector
from connectors.http import RetryPolicy
from connectors.odoo import OdooConnector
from druksmart_common.config import REPO_ROOT, load_settings
from druksmart_common.db import connect
from ingestion.migrate import apply_migrations
from ingestion.runner import run_extraction
from ingestion.store import RawStore

pytestmark = pytest.mark.warehouse

EXPECTED = json.loads((FIXTURES_DIR / "expected_kpis.json").read_text("utf-8"))
SEP, OCT = date(2026, 9, 30), date(2026, 10, 31)
NO_WAIT = {"retry": RetryPolicy(max_attempts=2, base_delay=0), "sleep": lambda s: None}


def _replay_fixture_batches(store: RawStore) -> None:
    """Re-create each synthetic extraction batch through the real connectors and runner."""
    batches = sorted({(f.meta["extracted_at"], f.meta["source_system"]) for f in load_fixtures()})
    for extracted_at, system in batches:
        batch = [
            f
            for f in load_fixtures()
            if f.meta["extracted_at"] == extracted_at and f.meta["source_system"] == system
        ]
        when = batch[0].extracted_at
        records = fixture_records(system, when.date())
        instance = batch[0].meta["source_instance"]
        if system == "odoo":
            fake = FakeOdoo(records)
            cfg = SourceConfig("odoo", instance, "http://odoo.test", api_key=ODOO_KEY)
            connector = OdooConnector(cfg, transport=fake.transport(), **NO_WAIT)
        else:
            fake = FakeFrappe(records)
            cfg = SourceConfig(
                "erpnext",
                instance,
                "http://erp.test",
                api_key=ERP_KEY,
                api_secret=ERP_SECRET,
                timezone=batch[0].meta["instance_timezone"],
            )
            connector = ERPNextConnector(cfg, transport=fake.transport(), **NO_WAIT)
        for fixture in batch:  # only the entities that were extracted in this batch
            result = run_extraction(connector, store, fixture.meta["entity"], now=lambda w=when: w)
            assert result.status == "succeeded", result.error


@pytest.fixture(scope="module")
def marts():
    settings = load_settings()
    with connect(settings.pipeline_test(), autocommit=True) as conn:
        db = conn.execute("select current_database()").fetchone()[0]
        assert db.endswith("_test"), f"refusing to reset non-test database {db}"
        apply_migrations(conn)
        conn.execute(
            "TRUNCATE raw.quarantined_record, raw.extraction_checkpoint, "
            "raw.source_record, raw.extraction_run"
        )
        _replay_fixture_batches(RawStore(conn))

        dbt = subprocess.run(
            [
                sys.executable,
                str(REPO_ROOT / "warehouse" / "run_dbt.py"),
                "build",
                "--target",
                "test",
            ],
            capture_output=True,
            text=True,
            timeout=900,
        )
        assert dbt.returncode == 0, dbt.stdout[-6000:] + dbt.stderr[-2000:]
        yield conn


def rows(conn, sql, *params):
    return conn.execute(sql, params).fetchall()


def as_dict(conn, sql, *params):
    return {k: (float(v) if not isinstance(v, int) else v) for k, v in rows(conn, sql, *params)}


def strip(d):
    return {k: v for k, v in d.items() if k != "working"}


# -------------------------------------------------------------------------- raw / dq


def test_quarantined_records_never_reach_the_marts(marts):
    quarantined = rows(
        marts,
        "select source_system, source_entity, source_id "
        "from raw.quarantined_record order by 1, 2, 3",
    )
    expected = {
        (s, e, i)
        for s, ents in strip(EXPECTED["rejected_records"]).items()
        for e, ids in ents.items()
        for i in ids
    }
    assert {tuple(r) for r in quarantined} == expected
    keys = {r[0] for r in rows(marts, "select employee_key from marts.dim_employee")}
    assert "odoo:odoo-dtg-retail:112" not in keys
    assert "erpnext:erpnext-dtg-services:HR-EMP-00011" not in keys


def test_snapshots_exist_only_for_extracted_dates(marts):
    hr = {
        r[0] for r in rows(marts, "select distinct snapshot_date from marts.fct_headcount_snapshot")
    }
    acc = {
        r[0]
        for r in rows(
            marts, "select distinct snapshot_date from marts.fct_receivable_payable_snapshot"
        )
    }
    assert hr == {OCT}  # HR was only extracted in the October batch: no fabricated September
    assert acc == {SEP, OCT}


# --------------------------------------------------------------------------------- HR


def test_hr01_active_headcount(marts):
    want = EXPECTED["HR-01_active_headcount"]
    by_instance = as_dict(
        marts,
        "select source_instance, sum(active_headcount)::int from marts.kpi_headcount "
        "where snapshot_date = %s group by 1",
        OCT,
    )
    by_branch = as_dict(
        marts,
        "select branch_key, sum(active_headcount)::int from marts.kpi_headcount "
        "where snapshot_date = %s group by 1 having sum(active_headcount) > 0",
        OCT,
    )
    assert by_instance == want["by_instance"]
    assert sum(by_instance.values()) == want["total"]
    assert by_branch == want["by_branch"]


def test_hr01_alternative_policy_figure(marts):
    got = as_dict(
        marts,
        "select source_instance, sum(active_headcount)::int from marts.kpi_headcount "
        "where snapshot_date = %s and source_system = 'odoo' "
        "and employee_category in ('employee', 'worker') group by 1",
        OCT,
    )
    assert got == strip(
        EXPECTED["HR-01_active_headcount"]["policy_alternative_odoo_employee_and_worker_only"]
    )


def test_hr02_headcount_by_department(marts):
    got = as_dict(
        marts,
        "select department_key, sum(active_headcount)::int from marts.kpi_headcount "
        "where snapshot_date = %s group by 1 having sum(active_headcount) > 0",
        OCT,
    )
    assert got == EXPECTED["HR-02_headcount_by_department"]["counts"]


def test_hr03_approved_leave(marts):
    want = EXPECTED["HR-03_approved_leave"]
    start, end = want["period"]["start"], want["period"]["end"]
    per_instance = rows(
        marts,
        """
        select source_instance, count(*)::int, sum(leave_days)::float,
               count(distinct employee_key)::int
        from marts.fct_leave_request
        where approval_status = 'approved' and start_date between %s and %s group by 1""",
        start,
        end,
    )
    got = {i: {"requests": r, "days": d, "employees": e} for i, r, d, e in per_instance}
    assert got == want["by_instance"]
    total = rows(
        marts,
        """select count(*)::int, sum(leave_days)::float, count(distinct employee_key)::int
                           from marts.fct_leave_request
                           where approval_status = 'approved' and start_date between %s and %s""",
        start,
        end,
    )[0]
    assert dict(zip(["requests", "days", "employees"], total, strict=True)) == want["total"]
    monthly = as_dict(
        marts,
        "select source_instance, sum(approved_requests)::int "
        "from marts.kpi_approved_leave_monthly where period_month = %s group by 1",
        start,
    )
    assert monthly == {i: v["requests"] for i, v in want["by_instance"].items()}


# --------------------------------------------------------------------------- Accounts


def _by_instance(marts, snapshot, ledger, column):
    got = as_dict(
        marts,
        f"select source_instance, sum({column}) from marts.kpi_receivables_payables "
        "where snapshot_date = %s and ledger = %s group by 1",
        snapshot,
        ledger,
    )
    got["total"] = sum(got.values())
    return got


@pytest.mark.parametrize("snapshot", [SEP, OCT], ids=str)
def test_ac01_to_ac03_balances(marts, snapshot):
    want = EXPECTED["accounts"][snapshot.isoformat()]
    assert (
        _by_instance(marts, snapshot, "receivable", "outstanding_amount")
        == want["AC-01_outstanding_receivables"]
    )
    assert (
        _by_instance(marts, snapshot, "payable", "outstanding_amount")
        == want["AC-02_outstanding_payables"]
    )
    assert (
        _by_instance(marts, snapshot, "receivable", "overdue_amount")
        == want["AC-03_overdue_receivables"]
    )
    assert (
        _by_instance(marts, snapshot, "payable", "overdue_amount") == want["AC-03_overdue_payables"]
    )


@pytest.mark.parametrize("snapshot", [SEP, OCT], ids=str)
@pytest.mark.parametrize("ledger", ["receivable", "payable"])
def test_ac04_ageing_distribution(marts, snapshot, ledger):
    kpi = "AC-04_receivables_ageing" if ledger == "receivable" else "AC-04_payables_ageing"
    want = EXPECTED["accounts"][snapshot.isoformat()][kpi]
    got = {}
    for instance, bucket, amount in rows(
        marts,
        """
            select source_instance, ageing_bucket, sum(outstanding_amount)
            from marts.kpi_receivables_payables
            where snapshot_date = %s and ledger = %s group by 1, 2""",
        snapshot,
        ledger,
    ):
        got.setdefault(instance, dict.fromkeys(EXPECTED["accounts"]["ageing_buckets"], 0.0))[
            bucket
        ] = float(amount)
    assert got == want


def test_balances_by_branch_and_verified_counterparty(marts):
    want = EXPECTED["accounts"]["2026-10-31"]
    for ledger, key in (
        ("receivable", "AC-01_receivables_by_branch"),
        ("payable", "AC-02_payables_by_branch"),
    ):
        got = as_dict(
            marts,
            "select branch_key, sum(outstanding_amount) from marts.kpi_receivables_payables "
            "where snapshot_date = %s and ledger = %s group by 1",
            OCT,
            ledger,
        )
        assert got == strip(want[key])
    by_party = as_dict(
        marts,
        "select unified_counterparty_id, sum(outstanding_company) "
        "from marts.fct_receivable_payable_snapshot "
        "where snapshot_date = %s and ledger = 'receivable' group by 1",
        OCT,
    )
    wanted = strip(want["AC-01_receivables_by_counterparty_selected"])
    assert {k: by_party.get(k) for k in wanted} == wanted
    assert "odoo:odoo-dtg-retail:303" not in by_party  # merged into the verified unified id


def test_unallocated_advances_are_separate_from_receivables(marts):
    got = as_dict(
        marts,
        "select source_instance, sum(unallocated_amount) from marts.fct_payment "
        "where direction = 'received' and document_state = 'posted' group by 1",
    )
    assert got == strip(EXPECTED["accounts"]["2026-10-31"]["unallocated_advances_received"])


def test_invoice_totals_are_not_treated_as_outstanding(marts):
    totals = as_dict(
        marts,
        "select source_instance, sum(amount_total_company) from marts.fct_accounting_document "
        "where ledger = 'receivable' and document_state = 'posted' group by 1",
    )
    outstanding = _by_instance(marts, OCT, "receivable", "outstanding_amount")
    assert all(totals[i] != outstanding[i] for i in totals)


def test_bi_reader_can_read_kpis_but_not_raw_or_staging(marts):
    settings = load_settings()
    with connect(replace(settings.bi_reader(), dbname=settings.analytics_test_db)) as bi:
        assert bi.execute("select count(*) from marts.kpi_headcount").fetchone()[0] > 0
        for table in (
            "raw.source_record",
            "staging.stg_odoo__hr_employee",
            "intermediate.int_partners",
        ):
            with pytest.raises(Exception, match="permission denied"):
                bi.execute(f"select 1 from {table} limit 1")
            bi.rollback()


# ------------------------------------------------------- Django KPI service (Milestone 8)


@pytest.fixture(scope="module")
def kpi_service(marts):
    """The REAL Django KPI service, reading the _test marts as the restricted KPI reader."""
    import importlib.util

    import psycopg
    from access.scope import Scope
    from kpi.service import KpiService

    settings = load_settings()
    if not settings.kpi_reader_user or settings.kpi_reader_password in ("", "CHANGE_ME"):
        pytest.skip("KPI reader not configured")
    spec = importlib.util.spec_from_file_location("publish", REPO_ROOT / "warehouse/publish.py")
    publish = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(publish)
    relations = publish.approved_relations(REPO_ROOT / "backend" / "approved_datasets.yml")
    publish.grant_reader(marts, "marts", settings.kpi_reader_user, relations, "KPI service")

    # Test marts are built by dbt directly (never published), so results carry a "stale" note;
    # only the values are compared here.
    reader = replace(settings.kpi_reader(), dbname=settings.analytics_test_db)

    def connect_test():
        return psycopg.connect(
            **reader.conninfo(), autocommit=True, options="-c default_transaction_read_only=on"
        )

    admin = Scope("eval", ("Administrator",), frozenset({"hr", "accounts"}), None)
    return lambda request: KpiService(connect=connect_test).run(request, admin)


def test_kpi_service_reproduces_hand_calculated_headcount_and_leave(kpi_service):
    from kpi.service import KpiRequest

    hc = kpi_service(KpiRequest("hr.active_headcount", as_of=OCT.isoformat())).rows
    assert hc == [{"active_headcount": EXPECTED["HR-01_active_headcount"]["total"]}]
    want = EXPECTED["HR-03_approved_leave"]
    leave = kpi_service(
        KpiRequest(
            "hr.approved_leave",
            period_start=want["period"]["start"],
            period_end=want["period"]["end"],
        )
    ).rows[0]
    assert {
        "requests": leave["approved_requests"],
        "days": float(leave["approved_leave_days"]),
        "employees": leave["employees_on_leave"],
    } == want["total"]


@pytest.mark.parametrize("snapshot", [SEP, OCT], ids=str)
def test_kpi_service_reproduces_hand_calculated_balances(kpi_service, snapshot):
    from kpi.service import KpiRequest

    want = EXPECTED["accounts"][snapshot.isoformat()]
    a = {"as_of": snapshot.isoformat()}

    def total(function, measure):
        return sum(r[measure] for r in kpi_service(KpiRequest(function, **a)).rows)

    assert total("ac.outstanding_receivables", "outstanding_amount") == pytest.approx(
        want["AC-01_outstanding_receivables"]["total"]
    )
    assert total("ac.outstanding_payables", "outstanding_amount") == pytest.approx(
        want["AC-02_outstanding_payables"]["total"]
    )
    overdue = {
        r["ledger"]: r["overdue_amount"]
        for r in kpi_service(KpiRequest("ac.overdue_balance", **a)).rows
    }
    assert overdue.get("receivable", 0) == pytest.approx(
        sum(v for k, v in want["AC-03_overdue_receivables"].items() if k != "total")
    )
    assert overdue.get("payable", 0) == pytest.approx(
        sum(v for k, v in want["AC-03_overdue_payables"].items() if k != "total")
    )
    ageing = kpi_service(KpiRequest("ac.ageing", **a)).rows
    for ledger, kpi in (
        ("receivable", "AC-04_receivables_ageing"),
        ("payable", "AC-04_payables_ageing"),
    ):
        expected: dict = {}
        for buckets in want[kpi].values():
            for b, amount in buckets.items():
                expected[b] = expected.get(b, 0) + amount
        got = {r["ageing"]: r["outstanding_amount"] for r in ageing if r["ledger"] == ledger}
        labels = {
            "not_due": "0 Not yet due",
            "1_30": "1 1-30 days overdue",
            "31_60": "2 31-60 days overdue",
            "61_90": "3 61-90 days overdue",
            "91_plus": "4 Over 90 days overdue",
            "no_due_date": "5 No due date",
            "unapplied_credit": "6 Unapplied credit",
        }
        assert {b: got.get(labels[b], 0) for b in expected} == pytest.approx(expected), ledger
