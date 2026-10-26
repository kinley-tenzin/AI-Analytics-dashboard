# ingestion/: extraction runs and loading into `raw`

**Owner:** Member 1 with Member 2 · **Status:** working (Milestone 3)

| File | Purpose |
|------|---------|
| `migrations/001_raw_tables.sql` | Raw tables: run log, versioned records, quarantine, checkpoints, current view |
| `migrate.py` | Applies migrations once (`raw.schema_migration`) |
| `store.py` | `RawStore`: advisory lock, per-page transactional writes, checkpoints |
| `runner.py` | `run_extraction` / `run_module`: window + overlap, validation, quarantine, recovery |
| `cli.py` | `python -m ingestion migrate | check | extract | runs | summary | quarantine` |

Every raw row carries `source_system`, `source_instance`, `source_entity`, `source_id`,
`payload` (original JSON), `payload_sha256`, `source_modified_at`, run ids and extraction times.
Re-running an extraction never duplicates identical records.

Connects as the **pipeline** role. Documentation: [docs/connectors/CONNECTORS.md](../docs/connectors/CONNECTORS.md).
