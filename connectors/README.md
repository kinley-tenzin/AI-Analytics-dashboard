# connectors/: ERP integration adapters

**Owner:** Member 1 (ERP integration and data extraction) · **Status:** working (Milestone 3)

Read-only Python adapters behind one interface (`base.py: SourceConnector`):

| File | Purpose |
|------|---------|
| `base.py` | Interface, `ExtractionWindow`, `Page`, reports, error types |
| `http.py` | `ApiClient`: timeouts, retry with exponential backoff, `Retry-After` |
| `config.py` | `SourceConfig` from `.env` (secrets hidden from `repr`) |
| `odoo.py` | Odoo 19 JSON-2 adapter (only `search_read`, `search_count`, `fields_get`, `context_get`) |
| `erpnext.py` | ERPNext 16 Frappe REST adapter (GET only) |

Rules:
- Connectors **never write** to an ERP and never touch PostgreSQL (that is `ingestion/`).
- Field lists, filters and entity options come from `contracts/sources/*.yaml`.
- Tests: `tests/unit/connectors/` (fake APIs) and `tests/live/` (real sandboxes).

Full documentation: [docs/connectors/CONNECTORS.md](../docs/connectors/CONNECTORS.md).
