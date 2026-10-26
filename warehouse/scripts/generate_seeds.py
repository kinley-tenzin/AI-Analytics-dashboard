"""Render dbt seed CSVs from the canonical contracts (single source of truth).

    python warehouse/scripts/generate_seeds.py

The mappings live in contracts/canonical/*.yaml and contracts/mappings/entity_mappings.yaml.
dbt needs them as tables, so they are rendered into warehouse/seeds/. Never edit the CSVs by hand;
tests/unit/test_warehouse_seeds.py fails if they differ from this rendering.
"""

from __future__ import annotations

import csv
import io
from pathlib import Path

import yaml

REPO_ROOT = Path(__file__).resolve().parents[2]
CANONICAL = REPO_ROOT / "contracts" / "canonical"
SEEDS = REPO_ROOT / "warehouse" / "seeds"


def _load(name: str) -> dict:
    return yaml.safe_load((CANONICAL / f"{name}.yaml").read_text("utf-8"))["entities"]


def _csv(header: list[str], rows: list[list]) -> str:
    out = io.StringIO()
    writer = csv.writer(out, lineterminator="\n")
    writer.writerow(header)
    writer.writerows(sorted(rows, key=lambda r: [str(v) for v in r]))
    return out.getvalue()


def render() -> dict[str, str]:
    hr, acc = _load("hr"), _load("accounts")
    files: dict[str, str] = {}

    status_map = hr["employee"]["status_rules"]["erpnext"]["status_map"]
    files["map_erpnext_employee_status.csv"] = _csv(
        ["source_status", "employment_status"], [[k, v] for k, v in status_map.items()]
    )

    leave = hr["leave_request"]["status_rules"]
    leave_rows = [["odoo", "", s, a] for s, a in leave["odoo"]["status_map"].items()]
    erp = leave["erpnext"]
    for status in erp["docstatus_1_status_map"]:
        leave_rows.append(["erpnext", 0, status, erp["docstatus_0"]])
        leave_rows.append(["erpnext", 1, status, erp["docstatus_1_status_map"][status]])
        leave_rows.append(["erpnext", 2, status, erp["docstatus_2"]])
    files["map_leave_approval_status.csv"] = _csv(
        ["source_system", "docstatus", "source_status", "approval_status"], leave_rows
    )

    doc = acc["accounting_document"]
    type_rows = [["odoo", t, "", led, kind] for t, (led, kind) in doc["type_map"]["odoo"].items()]
    for doctype, by_return in doc["type_map"]["erpnext"].items():
        type_rows += [["erpnext", doctype, r, led, kind] for r, (led, kind) in by_return.items()]
    files["map_document_type.csv"] = _csv(
        ["source_system", "source_document_type", "is_return", "ledger", "document_kind"], type_rows
    )

    state_rows = [["odoo", s, c] for s, c in doc["state_map"]["odoo"].items()]
    state_rows += [["erpnext", str(s), c] for s, c in doc["state_map"]["erpnext_docstatus"].items()]
    files["map_document_state.csv"] = _csv(
        ["source_system", "source_state", "document_state"], state_rows
    )
    files["map_document_sign.csv"] = _csv(
        ["document_kind", "document_sign"], [[k, v] for k, v in doc["document_sign"].items()]
    )

    pay = acc["payment"]
    pay_rows = [["odoo", s, c] for s, c in pay["state_map"]["odoo"].items()]
    pay_rows += [["erpnext", str(s), c] for s, c in pay["state_map"]["erpnext_docstatus"].items()]
    files["map_payment_state.csv"] = _csv(
        ["source_system", "source_state", "document_state"], pay_rows
    )
    dir_rows = [
        [sys_, t, d] for sys_ in ("odoo", "erpnext") for t, d in pay["direction_map"][sys_].items()
    ]
    files["map_payment_direction.csv"] = _csv(
        ["source_system", "source_payment_type", "direction"], dir_rows
    )

    mappings = yaml.safe_load(
        (REPO_ROOT / "contracts/mappings/entity_mappings.yaml").read_text("utf-8")
    )
    map_rows = [
        [m["entity"], m["unified_id"], member, m["verified_by"], str(m["verified_on"])]
        for m in mappings["mappings"]
        for member in m["members"]
    ]
    files["verified_entity_mappings.csv"] = _csv(
        ["entity", "unified_id", "member_key", "verified_by", "verified_on"], map_rows
    )
    return files


def main() -> None:
    SEEDS.mkdir(parents=True, exist_ok=True)
    for name, text in render().items():
        (SEEDS / name).write_text(text, encoding="utf-8", newline="\n")
        print(f"wrote warehouse/seeds/{name}")


if __name__ == "__main__":
    main()
