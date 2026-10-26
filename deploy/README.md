# deploy/: platform operations

`druksmart.py` is the single entry point for installing and operating the local demonstration
deployment. Full guide: [docs/DEPLOYMENT.md](../docs/DEPLOYMENT.md).

```powershell
python deploy\druksmart.py check                 # prerequisites
python deploy\druksmart.py setup [--build]       # first-time / repeat-safe setup
python deploy\druksmart.py up [--minimal]        # ordered start with health checks
python deploy\druksmart.py status                # services, data freshness, DAG
python deploy\druksmart.py run-pipeline [--synthetic]
python deploy\druksmart.py demo-data live|synthetic
python deploy\druksmart.py backup [--include-env]
python deploy\druksmart.py restore-check backups\<ts>
python deploy\druksmart.py restore backups\<ts> --yes   # destructive
python deploy\druksmart.py stop                  # keeps all data
```

Rules:
- Run the script with the project `.venv`.
- No command deletes Docker volumes. Only `restore --yes` overwrites data.
- `--env-file other.env` (with another `COMPOSE_PROJECT_NAME` and other ports) deploys a fully separate stack. Milestone 9 used this for the clean-start tests.
