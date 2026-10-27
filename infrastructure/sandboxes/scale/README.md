# Loading scale data INTO the ERP sandboxes (synthetic data only)

Fills the local Odoo and ERPNext **sandboxes** with a slice of the medium synthetic data, through
each ERP's own business logic, so the pipeline can extract it with the real connectors
(`source_mode=configured`). Results: [docs/evaluation/SCALE_TEST.md](../../../docs/evaluation/SCALE_TEST.md).

```powershell
python tests\fixtures\synthetic_medium\generate_medium.py                  # the source data (3 s)
python infrastructure\sandboxes\scale\plan.py --slice 0.10                  # 10 % plan (1.0 = everything)
python infrastructure\sandboxes\scale\load_odoo_run.py                      # Odoo ORM, inside `odoo shell`
python infrastructure\sandboxes\scale\load_erpnext.py --workers 3           # ERPNext REST API
python infrastructure\sandboxes\scale\load_erpnext.py --workers 2 --phases leaves,invoices,returns,payments  # fill gaps
```

| File | Role |
|---|---|
| `plan.py` | Final-state load plan with stable refs; slices keep references intact |
| `load_odoo.py` / `load_odoo_run.py` | Odoo loader (piped into `odoo shell`) and its host-side runner |
| `load_erpnext.py` | ERPNext loader (REST as Administrator, retries, parallel workers, local URLs only) |

- **Idempotent:** every record carries a `SCALE-<ref>` marker (Odoo external id `druksmart_scale.<ref>`;
  ERPNext `po_no` / `bill_no` / `reference_no` / `employee_number` / leave `description`). Running again
  only creates what is missing.
- **Adds data only.** It never deletes or edits existing sandbox records. The ERPs refuse some records
  (overlapping leave, inactive employees, returns above the open balance); those are counted and skipped.
- **Sandboxes only.** The ERPNext loader refuses non-local URLs; the Odoo loader runs inside the sandbox container.
- **ERPNext prerequisite found during the test:** `sites/apps.txt` in the sandbox listed only `erpnext` and
  `frappe`, so writing HR documents failed ("Module HR not found"). `hrms` was added (backup:
  `sites/apps.txt.bak-scale`) and `bench --site frontend clear-cache` run. A sandbox rebuilt from scratch
  needs the same.
- Speed (this laptop): Odoo 0.05 s per document and 0.5 s per payment; ERPNext about 0.4-1 s per
  document, with parallel workers causing some `tabSeries` lock retries (hence `--workers 2-3`).
