"""Reconcile every KPI across ALL layers of the platform for one snapshot date.

    source ERPs (oracle) -> dbt fact tables -> Superset (certified metrics) -> Django KPI API
    -> AI assistant (structured result AND the number written in the answer text)

    python evaluation/reconcile.py [--as-of 2026-10-25] [--name reconciliation]

Totals are compared across all layers; per-source-system figures between the source oracle, the
dbt facts and Superset (the only layers that expose the source instance). Writes
docs/evaluation/results/<name>.json and exits 1 on any mismatch.
"""

from __future__ import annotations

import argparse
import calendar
import re
import sys
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import evaltools as et  # noqa: E402
import source_oracle  # noqa: E402

TOL = 0.005
ASK = {
    "headcount": "How many active employees are there?",
    "by_department": "How many employees work in each department?",
    "leave": "How many employees are on approved leave?",
    "receivable": "What is the outstanding receivables balance?",
    "payable": "What is the outstanding payables balance?",
    "overdue": "How much is overdue?",
    "overdue_ageing": "Show overdue balances by ageing category.",
}
LABEL = {
    "1_30": "1 1-30 days overdue",
    "31_60": "2 31-60 days overdue",
    "61_90": "3 61-90 days overdue",
    "91_plus": "4 Over 90 days overdue",
    "not_due": "0 Not yet due",
    "no_due_date": "5 No due date",
    "unapplied_credit": "6 Unapplied credit",
}


def same(a, b) -> bool:
    if isinstance(a, dict) and isinstance(b, dict):
        keys = {k for k, v in {**a, **b}.items() if v}
        return all(abs(float(a.get(k, 0)) - float(b.get(k, 0))) <= TOL for k in keys)
    return a is not None and b is not None and abs(float(a) - float(b)) <= TOL


def warehouse_layer(conn, as_of: date, period) -> dict:
    """dbt fact tables (NOT the KPI views), per source instance."""
    out: dict = {}
    for inst, n in conn.execute(
        "select source_instance, count(*) from marts.fct_headcount_snapshot "
        "where snapshot_date = %s and employment_status = 'active' group by 1",
        (as_of,),
    ).fetchall():
        out.setdefault(inst, {})["headcount"] = n
    for inst, emp, req, days in conn.execute(
        "select source_instance, count(distinct employee_key), count(*), sum(leave_days) "
        "from marts.fct_leave_request where approval_status = 'approved' "
        "and start_date between %s and %s group by 1",
        period,
    ).fetchall():
        out.setdefault(inst, {})["leave"] = {"employees": emp, "requests": req, "days": float(days)}
    for inst, ledger, total, overdue in conn.execute(
        "select source_instance, ledger, sum(outstanding_company), "
        "sum(outstanding_company) filter (where is_overdue) "
        "from marts.fct_receivable_payable_snapshot where snapshot_date = %s group by 1, 2",
        (as_of,),
    ).fetchall():
        out.setdefault(inst, {})[ledger] = float(total)
        out[inst][f"overdue_{ledger}"] = float(overdue or 0)
    for inst, ledger, bucket_, amount in conn.execute(
        "select source_instance, ledger, ageing_bucket, sum(outstanding_company) "
        "from marts.fct_receivable_payable_snapshot where snapshot_date = %s group by 1, 2, 3",
        (as_of,),
    ).fetchall():
        out.setdefault(inst, {}).setdefault("ageing", {})[f"{ledger}|{bucket_}"] = float(amount)
    dept = conn.execute(
        "select d.department_name, count(*) from marts.fct_headcount_snapshot f "
        "join marts.dim_department d using (department_key) "
        "where f.snapshot_date = %s and f.employment_status = 'active' group by 1",
        (as_of,),
    ).fetchall()
    out["_by_department"] = {k: v for k, v in dept}
    return out


def superset_layer(api, as_of: date, period) -> dict:
    at = {"col": "snapshot_date", "op": "==", "val": str(as_of)}
    out: dict = {}
    for r in et.superset_rows(api, "kpi_headcount", ["active_headcount"], columns=["source_instance"], filters=[at]):
        out.setdefault(r["source_instance"], {})["headcount"] = r["active_headcount"]
    metrics = [
        "outstanding_receivables",
        "outstanding_payables",
        "overdue_receivables",
        "overdue_payables",
    ]
    for r in et.superset_rows(api, "kpi_receivables_payables", metrics, columns=["source_instance"], filters=[at]):
        d = out.setdefault(r["source_instance"], {})
        d["receivable"], d["payable"] = r["outstanding_receivables"], r["outstanding_payables"]
        d["overdue_receivable"], d["overdue_payable"] = (
            r["overdue_receivables"],
            r["overdue_payables"],
        )
    for r in et.superset_rows(
        api,
        "kpi_receivables_payables",
        ["outstanding_amount"],
        columns=["source_instance", "ledger", "ageing_bucket"],
        filters=[at],
    ):
        out.setdefault(r["source_instance"], {}).setdefault("ageing", {})[f"{r['ledger']}|{r['ageing_bucket']}"] = r[
            "outstanding_amount"
        ]
    month = {"col": "period_month", "op": "==", "val": str(period[0])}
    for r in et.superset_rows(
        api,
        "kpi_approved_leave_monthly",
        ["approved_requests", "approved_leave_days"],
        columns=["source_instance"],
        filters=[month],
    ):
        out.setdefault(r["source_instance"], {})["leave"] = {
            "requests": r["approved_requests"],
            "days": r["approved_leave_days"],
        }
    out["_by_department"] = {
        r["department_name"]: r["active_headcount"]
        for r in et.superset_rows(api, "kpi_headcount", ["active_headcount"], columns=["department_name"], filters=[at])
        if r["active_headcount"]
    }
    return out


def _rows(resp) -> list[dict]:
    resp.raise_for_status()
    return resp.json()["result"]["rows"]


def django_layer(dj: et.Django, as_of: date, period) -> dict:
    a, p = {"as_of": str(as_of)}, {"period_start": str(period[0]), "period_end": str(period[1])}
    leave = _rows(dj.kpi("hr.approved_leave", **p))[0]
    overdue = {r["ledger"]: r["overdue_amount"] for r in _rows(dj.kpi("ac.overdue_balance", **a))}
    return {
        "headcount": _rows(dj.kpi("hr.active_headcount", **a))[0]["active_headcount"],
        "by_department": {
            r["department"]: r["active_headcount"]
            for r in _rows(dj.kpi("hr.active_headcount", group_by="department", **a))
        },
        "leave": {
            "employees": leave["employees_on_leave"],
            "requests": leave["approved_requests"],
            "days": leave["approved_leave_days"],
        },
        "receivable": sum(r["outstanding_amount"] for r in _rows(dj.kpi("ac.outstanding_receivables", **a))),
        "payable": sum(r["outstanding_amount"] for r in _rows(dj.kpi("ac.outstanding_payables", **a))),
        "overdue_receivable": overdue.get("receivable", 0),
        "overdue_payable": overdue.get("payable", 0),
        "overdue_ageing": {
            f"{r['ledger']}|{r['ageing']}": r["overdue_amount"] for r in _rows(dj.kpi("ac.overdue_by_ageing", **a))
        },
    }


def _in_text(value, text: str) -> bool:
    """The number appears in the answer text (formatted with separators, optionally .00)."""
    candidates = (
        {f"{value:,.2f}", f"{value:,.0f}", f"{int(value):,}"}
        if float(value).is_integer()
        else {f"{value:,.2f}", f"{value:,.1f}"}
    )
    return any(re.search(rf"(?<![\d,.]){re.escape(c)}(?![\d])", text) for c in candidates)


def ai_layer(dj: et.Django) -> dict:
    out, texts = {}, {}
    for key, question in ASK.items():
        a = dj.ask(question)
        texts[key] = {"status": a["status"], "answer": a["answer"], "interpreter": a["interpreter"]}
        if a["status"] != "answered":
            continue
        rows = a["result"]["rows"]
        if key == "headcount":
            out[key] = rows[0]["active_headcount"]
        elif key == "by_department":
            out[key] = {r["department"]: r["active_headcount"] for r in rows}
        elif key == "leave":
            out[key] = {
                "employees": rows[0]["employees_on_leave"],
                "requests": rows[0]["approved_requests"],
                "days": rows[0]["approved_leave_days"],
            }
        elif key in ("receivable", "payable"):
            out[key] = sum(r["outstanding_amount"] for r in rows)
        elif key == "overdue":
            for r in rows:
                out[f"overdue_{r['ledger']}"] = r["overdue_amount"]
        elif key == "overdue_ageing":
            out[key] = {f"{r['ledger']}|{r['ageing']}": r["overdue_amount"] for r in rows}
    return {"values": out, "answers": texts}


def total(per_instance: dict, key: str):
    vals = [v[key] for k, v in per_instance.items() if not k.startswith("_") and key in v]
    if not vals:
        return None
    if isinstance(vals[0], dict):
        merged: dict = {}
        for v in vals:
            for k2, x in v.items():
                merged[k2] = merged.get(k2, 0) + x
        return merged
    return sum(vals)


def reconcile(as_of: date) -> dict:
    period = (
        as_of.replace(day=1),
        as_of.replace(day=calendar.monthrange(as_of.year, as_of.month)[1]),
    )
    src = source_oracle.figures(as_of, period)
    with et.warehouse() as conn:
        wh = warehouse_layer(conn, as_of, period)
        pub = et.publication(conn)
    ss = superset_layer(et.superset("admin"), as_of, period)
    dj = et.Django("demo_executive")
    dj_vals = django_layer(dj, as_of, period)
    ai = ai_layer(dj)
    dj.close()

    def overdue_ageing(per_instance):
        ageing = total(per_instance, "ageing") or {}
        return {
            f"{k.split('|')[0]}|{LABEL[k.split('|')[1]]}": v
            for k, v in ageing.items()
            if k.split("|")[1] in ("1_30", "31_60", "61_90", "91_plus") and v
        }

    checks = []

    def check(kpi, layers: dict):
        ref = layers["source"]
        results = {name: (val, same(ref, val) if val is not None else None) for name, val in layers.items()}
        ok = all(m is not False for _, m in results.values()) and all(v is not None for v, _ in results.values())
        checks.append(
            {
                "kpi": kpi,
                "ok": ok,
                "layers": {n: v for n, (v, _) in results.items()},
                "mismatch": [n for n, (_, m) in results.items() if m is False],
            }
        )

    for k in ("headcount", "receivable", "payable", "overdue_receivable", "overdue_payable"):
        check(
            k,
            {
                "source": total(src, k),
                "dbt": total(wh, k),
                "superset": total(ss, k),
                "django": dj_vals[k],
                "ai": ai["values"].get(k),
            },
        )
    src_dept: dict = {}
    for inst in src.values():
        for d, n in inst["by_department"].items():
            src_dept[d] = src_dept.get(d, 0) + n
    check(
        "headcount_by_department",
        {
            "source": src_dept,
            "dbt": wh["_by_department"],
            "superset": ss["_by_department"],
            "django": dj_vals["by_department"],
            "ai": ai["values"].get("by_department"),
        },
    )
    src_leave, wh_leave = total(src, "leave"), total(wh, "leave")
    check(
        "approved_leave_employees",
        {
            "source": src_leave["employees"],
            "dbt": wh_leave["employees"],
            "django": dj_vals["leave"]["employees"],
            "ai": (ai["values"].get("leave") or {}).get("employees"),
        },
    )
    for m in ("requests", "days"):
        check(
            f"approved_leave_{m}",
            {
                "source": src_leave[m],
                "dbt": wh_leave[m],
                "superset": total(ss, "leave")[m],
                "django": dj_vals["leave"][m],
                "ai": (ai["values"].get("leave") or {}).get(m),
            },
        )
    check(
        "ageing_all_buckets",
        {
            "source": total(src, "ageing"),
            "dbt": total(wh, "ageing"),
            "superset": total(ss, "ageing"),
        },
    )
    check(
        "overdue_by_ageing",
        {
            "source": overdue_ageing(src),
            "dbt": overdue_ageing(wh),
            "django": dj_vals["overdue_ageing"],
            "ai": ai["values"].get("overdue_ageing"),
        },
    )
    # Per source system: source oracle vs dbt facts vs Superset.
    for inst in src:
        for k in (
            "headcount",
            "receivable",
            "payable",
            "overdue_receivable",
            "overdue_payable",
            "ageing",
        ):
            check(
                f"{inst}:{k}",
                {
                    "source": src[inst].get(k),
                    "dbt": wh.get(inst, {}).get(k),
                    "superset": ss.get(inst, {}).get(k),
                },
            )
        check(
            f"{inst}:leave_requests",
            {
                "source": src[inst]["leave"]["requests"],
                "dbt": wh.get(inst, {}).get("leave", {}).get("requests"),
                "superset": ss.get(inst, {}).get("leave", {}).get("requests"),
            },
        )
    # The numbers must also be the ones WRITTEN in the AI answers (not only in the result rows).
    text_checks = {
        "headcount": _in_text(total(src, "headcount"), ai["answers"]["headcount"]["answer"]),
        "receivable": _in_text(total(src, "receivable"), ai["answers"]["receivable"]["answer"]),
        "payable": _in_text(total(src, "payable"), ai["answers"]["payable"]["answer"]),
        "overdue_receivable": _in_text(total(src, "overdue_receivable"), ai["answers"]["overdue"]["answer"]),
        "leave_employees": _in_text(src_leave["employees"], ai["answers"]["leave"]["answer"]),
    }
    return {
        "as_of": str(as_of),
        "period": [str(period[0]), str(period[1])],
        "publication": pub,
        "checks": checks,
        "ai_answer_text_contains_source_number": text_checks,
        "ai_answers": ai["answers"],
        "passed": sum(c["ok"] for c in checks) + sum(text_checks.values()),
        "total": len(checks) + len(text_checks),
    }


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--as-of", help="snapshot date (default: latest published)")
    parser.add_argument("--name", default="reconciliation")
    args = parser.parse_args(argv)
    if args.as_of:
        as_of = date.fromisoformat(args.as_of)
    else:
        with et.warehouse() as conn:
            as_of = conn.execute("select max(snapshot_date) from marts.fct_headcount_snapshot").fetchone()[0]
    report = reconcile(as_of)
    path = et.save_result(args.name, report)
    for c in report["checks"]:
        print(f"[{'PASS' if c['ok'] else 'FAIL'}] {c['kpi']:<40} {c['layers'] if not c['ok'] else ''}")
    for k, ok in report["ai_answer_text_contains_source_number"].items():
        print(f"[{'PASS' if ok else 'FAIL'}] ai text contains source value: {k}")
    print(f"{report['passed']}/{report['total']} reconciliation checks passed -> {path}")
    return 0 if report["passed"] == report["total"] else 1


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
