# infrastructure/ — Docker and database infrastructure

| Path | Purpose |
|------|---------|
| `../compose.yaml` | Development stack (kept at the repo root so `docker compose` works from there) |
| `postgres/init/01_init_databases_roles_schemas.sh` | Creates databases, least-privilege roles and the `raw/staging/intermediate/marts` schemas. Idempotent |
| `scripts/create_local_env.py` | Creates `.env` from `.env.example` with random passwords (never printed) |

## Database layout (Milestone 1)

| Database | Purpose | Roles |
|----------|---------|-------|
| `druksmart_analytics` | ERP analytical data: `raw`, `staging`, `intermediate`, `marts` | `pipeline` owns all four schemas; `bi_reader` has USAGE + SELECT on `marts` only |
| `druksmart_app` | Django application metadata | `app` owns it; no other service role can connect |

`POSTGRES_USER` is a bootstrap superuser used only inside the container. Application code never uses it.

## Re-running initialisation

The init script runs automatically only when the data volume is **empty**. After editing passwords
in `.env`, re-apply them without losing data:

```powershell
docker compose up -d
docker compose exec postgres bash /docker-entrypoint-initdb.d/01_init_databases_roles_schemas.sh
```
