# contracts/: version-controlled data contracts

**Owners:** Member 1 (source contracts) and Member 2 (canonical models). Changes need both to review.

| File | Purpose |
|------|---------|
| `raw_record.yaml` | Envelope every raw row carries (provenance, batch, hash, identity rules) |
| `sources/odoo.yaml` | Odoo 19 JSON-2: API usage, value conventions, entities and fields |
| `sources/erpnext.yaml` | ERPNext/HRMS 16 Frappe REST: same structure |
| `canonical/hr.yaml` | Canonical employee, department and leave models plus status maps |
| `canonical/accounts.yaml` | Canonical accounting document and payment models, value maps, sign and currency rules |
| `mappings/entity_mappings.yaml` | The **only** place cross-ERP identities are declared (verified, with evidence) |

## Field specification keys (source contracts)

| Key | Meaning |
|-----|---------|
| `type` | `integer`, `number`, `string`, `boolean`, `date`, `datetime`, `selection`, `many2one` (Odoo `[id, name]`), `link` (ERPNext name), `check` (0/1), `id_list`, `table` (child rows, with `child_fields`) |
| `required: true` | Missing/empty → **error** (record quarantined) |
| `expected: true` | Missing/empty → **warning** (record loaded, flagged) |
| `values` | Allowed selection values |
| `verification` | `source_code`, `documentation` or `assumption` (assumptions must be checked in the sandbox) |

"Empty" follows each ERP's convention: Odoo `false` (except boolean fields), ERPNext `null`/`""`.

## Using them

```python
from druksmart_common.contracts import load_source_contract, validate_record, build_raw_record

contract = load_source_contract("odoo")
issues = validate_record(contract, "hr.employee", payload)  # [] when valid
```

## Changing a contract

1. Edit the YAML and bump `contract_version` (minor for additive changes, major for breaking).
2. Update fixtures (`tests/fixtures/synthetic/generate_fixtures.py`) and docs in `docs/data/`.
3. Run `pytest`. The mapping-completeness tests fail if a new source value has no canonical mapping.
