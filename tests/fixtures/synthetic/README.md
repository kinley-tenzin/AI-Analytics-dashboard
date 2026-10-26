# Synthetic ERP fixtures

> **All data in this folder is SYNTHETIC.** The companies, people, partners, tax numbers and amounts
> are fictional and were created for testing. Nothing here was extracted from a real ERP.

## Scenario

One client group (fictional "DTG") runs two ERPs:

| Source instance | ERP | Legal company | Branches |
|-----------------|-----|---------------|----------|
| `odoo-dtg-retail` | Odoo 19 | DTG Retail Pvt Ltd (BTN) | Head office (company 1), Phuentsholing branch (company 2) |
| `erpnext-dtg-services` | ERPNext 16 | DTG Services Pvt Ltd (BTN) | Paro, Bumthang (Branch master) |

## Files

`<erp>/<batch date>/<entity>.json`, each `{"_meta": {...}, "response": <API body>}`:
- Odoo `response` is a bare array (JSON-2). ERPNext `response` is `{"data": [...]}` (Frappe).
- `_meta` holds the extraction metadata: instance, batch id, `extracted_at` (UTC), mode
  (`full` / `incremental`), checkpoint, and the request that would produce it.

| Batch | Content |
|-------|---------|
| `2026-09-30` | Full extraction of partners, accounting documents, payments |
| `2026-10-31` | Full extraction of HR data; **incremental** accounting extraction (changed records only) |

## Deliberate edge cases

| Edge case | Where |
|-----------|-------|
| Active / archived / left / inactive / suspended / future-joiner employees | Odoo 103, 108, 109, 113; ERPNext 00006, 00007, 00008, 00013 |
| Same name, different person across ERPs (must NOT merge) | Pema Wangmo (Odoo 106 / ERPNext HR-EMP-00001) |
| Same department name in two branches | Odoo departments 2 and 5 ("Sales") |
| Missing department / branch (warning) | Odoo 110; ERPNext 00009, 00010 |
| Leave: approved, pending, second approval, refused, cancelled, unsubmitted-approved, spanning months, half day | Odoo 201–209; ERPNext 00001–00008 |
| Invoices: paid, unpaid, partially paid, overdue in every bucket, draft, cancelled with stale balance, reversed, foreign currency (USD, INR) | Odoo 401–456; ERPNext SINV/PINV |
| Credit notes: applied against invoice, standalone unapplied | ERPNext RET-00001 / RET-00002; Odoo 407, 456, 414 |
| Draft → posted between batches; paid between batches; unchanged records absent from the incremental batch | Odoo 404, 403, 406; ERPNext 00004 |
| Payments: full, partial, foreign currency, draft, unallocated advance | Odoo 501–508; ERPNext ACC-PAY-00001–00007 |
| Verified cross-ERP customer vs same-name unverified customer | Lhaki Traders (same TPN) vs Norbu Hardware (different TPN) |
| **Invalid records (must be rejected)** | Odoo employee 112 (bad type), leave 210 (end before start), bill 457 (no currency); ERPNext HR-EMP-00011 (bad status), HR-EMP-00012 (no company), HR-LAP-2026-00009 (no leave type), ACC-SINV-2026-00010 (no customer) |

## Expected results

[`expected_kpis.json`](expected_kpis.json) was calculated **by hand** (working included) and is
independently re-derived in code by `tests/support/kpi_reference.py`; the tests require both to agree.
Future dbt marts must reproduce the same numbers.

## Regenerating

```powershell
python tests\fixtures\synthetic\generate_fixtures.py
pytest tests/unit
```

A test fails if the committed JSON differs from the generator output, so always edit the
generator rather than the JSON files.
